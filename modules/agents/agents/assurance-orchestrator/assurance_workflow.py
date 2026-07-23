"""Agent Framework workflow for read-only AssuranceOrchestrator invoice assurance runs."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from agent_framework import RunContext, step, workflow
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from expert_clients import FoundryPromptExpertClient, HostedResponsesExpertClient, is_expert_enabled
from telemetry import rft_reference_attributes, set_span_attribute, trace_span
from waypoint_client import WaypointReadOnlyClient


logger = logging.getLogger("assurance_orchestrator.workflow")

JsonDict = dict[str, Any]
WorkflowStatus = Literal["completed", "partial", "failed"]
StepStatus = Literal["completed", "partial", "failed"]
OutputQuality = Literal["valid", "partial", "malformed", "no_evidence", "unknown"]
AuthMode = Literal["placeholder", "delegated_obo", "agent_identity", "toolbox_managed"]

TOOLBOX_FEATURES_HEADER = "Toolboxes=V1Preview"
TOOLBOX_SCOPE = "https://ai.azure.com/.default"


class WaypointReader(Protocol):
    def get_work(self) -> Any: ...
    def get_action_types(self) -> Any: ...
    def get_runs(self) -> Any: ...
    def get_invoice_context(self, invoice_id: str) -> Any: ...
    def get_invoice(self, invoice_id: str) -> Any: ...
    def get_findings(self, invoice_id: str | None = None) -> Any: ...
    def get_evidence(self, invoice_id: str | None = None, finding_id: str | None = None) -> Any: ...


class ExpertValidatorClient(Protocol):
    async def resolve_tool_name(self, validator_id: str) -> str | None: ...

    async def call_validator(
        self,
        validator_id: str,
        arguments: JsonDict,
    ) -> Any: ...


class ToolNotConfiguredError(RuntimeError):
    pass


class ContentUnderstandingNotConfiguredError(RuntimeError):
    pass


class AssuranceOrchestratorRunJournal:
    def __init__(self, root_dir: str | os.PathLike[str]) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = Path(root_dir) / f"assurance_orchestrator-{timestamp}-{uuid.uuid4().hex[:8]}"
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._sequence = 0

    @classmethod
    def from_env(cls) -> "AssuranceOrchestratorRunJournal | None":
        root_dir = _first_env("ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR")
        return cls(root_dir) if root_dir else None

    def write(self, label: str, payload: JsonDict) -> JsonDict:
        self._sequence += 1
        entry = {
            "label": label,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": _redact_journal_payload(_to_json_safe(payload)),
        }
        path = self.run_dir / f"{self._sequence:02d}-{_safe_journal_label(label)}.json"
        _atomic_write_json(path, entry)
        _atomic_write_json(self.run_dir / "latest.json", entry)
        return {"path": str(path), "run_dir": str(self.run_dir)}


@dataclass(frozen=True)
class ExpertToolSpec:
    validator_id: str
    source_system: str
    auth_mode: AuthMode
    auth_audience: str
    env_var: str
    default_tool_name: str | None = None

    @property
    def tool_name(self) -> str | None:
        return _first_env(f"{self.env_var}_NAME", self.env_var) or self.default_tool_name

    @property
    def explicit_tool_name(self) -> str | None:
        return _first_env(f"{self.env_var}_NAME", self.env_var)


EXPERT_TOOL_SPECS: dict[str, ExpertToolSpec] = {
    "webiq": ExpertToolSpec(
        validator_id="webiq",
        source_system="webiq",
        auth_mode="toolbox_managed",
        auth_audience="Foundry WebIQ / web grounding connection",
        env_var="ASSURANCE_ORCHESTRATOR_WEBIQ_TOOL",
    ),
    "fabriciq": ExpertToolSpec(
        validator_id="fabriciq",
        source_system="fabriciq",
        auth_mode="delegated_obo",
        auth_audience="Microsoft Fabric IQ",
        env_var="ASSURANCE_ORCHESTRATOR_FABRICIQ_TOOL",
    ),
    "workiq": ExpertToolSpec(
        validator_id="workiq",
        source_system="workiq",
        auth_mode="delegated_obo",
        auth_audience="Microsoft 365 Work IQ",
        env_var="ASSURANCE_ORCHESTRATOR_WORKIQ_TOOL",
    ),
    "foundryiq": ExpertToolSpec(
        validator_id="foundryiq",
        source_system="foundryiq",
        auth_mode="agent_identity",
        auth_audience="Azure AI Foundry project resources",
        env_var="ASSURANCE_ORCHESTRATOR_FOUNDRYIQ_TOOL",
    ),
}

EXPERT_AGENT_NAMES: dict[str, str] = {
    "webiq": "market-evidence-expert",
    "fabriciq": "operations-data-expert",
    "workiq": "collaboration-evidence-expert",
    "foundryiq": "contract-policy-expert",
}


class _ToolboxAuth(httpx.Auth):
    def __init__(self, get_token: Callable[[], str]) -> None:
        self._get_token = get_token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._get_token()}"
        yield request


class ToolboxExpertClient:
    """Programmatic Foundry toolbox caller for validator steps.

    The model still sees the same toolbox as an Agent Framework MCP tool. This
    client is for workflow-owned fan-out steps where AssuranceOrchestrator must retry,
    normalize, and trace each expert result deterministically.
    """

    execution_path = "foundry_toolbox"

    def __init__(self, endpoint: str, credential: Any | None = None, timeout: float = 120.0) -> None:
        self.endpoint = endpoint
        self._credential = credential or DefaultAzureCredential()
        self._timeout = timeout
        self._tool_descriptors: list[JsonDict] | None = None

    @classmethod
    def from_env(cls) -> "ToolboxExpertClient | None":
        endpoint = _toolbox_endpoint()
        if not endpoint:
            return None
        return cls(endpoint)

    async def call_validator(self, validator_id: str, arguments: JsonDict) -> Any:
        spec = EXPERT_TOOL_SPECS.get(validator_id)
        if spec is None:
            raise ValueError(f"No expert tool spec is registered for validator '{validator_id}'.")
        tool_name = await self.resolve_tool_name(validator_id)
        if not tool_name:
            raise ToolNotConfiguredError(
                f"{validator_id} is not configured and no matching toolbox tool was discovered."
            )

        token_provider = get_bearer_token_provider(self._credential, TOOLBOX_SCOPE)
        http_client = httpx.AsyncClient(
            auth=_ToolboxAuth(token_provider),
            headers={"Foundry-Features": TOOLBOX_FEATURES_HEADER},
            timeout=self._timeout,
        )
        try:
            async with streamable_http_client(self.endpoint, http_client=http_client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await session.call_tool(tool_name, arguments)
        finally:
            await http_client.aclose()

    async def resolve_tool_name(self, validator_id: str) -> str | None:
        spec = EXPERT_TOOL_SPECS.get(validator_id)
        if spec is None:
            return None
        if spec.explicit_tool_name:
            return spec.explicit_tool_name
        descriptors = await self._get_tool_descriptors()
        return _select_expert_tool_name(validator_id, descriptors)

    async def _get_tool_descriptors(self) -> list[JsonDict]:
        if self._tool_descriptors is not None:
            return self._tool_descriptors

        token_provider = get_bearer_token_provider(self._credential, TOOLBOX_SCOPE)
        http_client = httpx.AsyncClient(
            auth=_ToolboxAuth(token_provider),
            headers={"Foundry-Features": TOOLBOX_FEATURES_HEADER},
            timeout=self._timeout,
        )
        try:
            async with streamable_http_client(self.endpoint, http_client=http_client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
        finally:
            await http_client.aclose()

        payload = _json_safe_payload(tools_result)
        tools = payload.get("tools") if isinstance(payload, dict) else None
        self._tool_descriptors = _as_dicts(tools)
        return self._tool_descriptors


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_seconds: float = 0.05


@dataclass(frozen=True)
class ContentUnderstandingConfig:
    endpoint: str
    api_version: str
    analyzer_id: str
    scope: str
    timeout_seconds: float
    poll_interval_seconds: float
    max_polls: int

    @classmethod
    def from_env(cls) -> "ContentUnderstandingConfig | None":
        endpoint = _first_env("CONTENT_UNDERSTANDING_ENDPOINT")
        if not endpoint:
            return None
        return cls(
            endpoint=endpoint.rstrip("/"),
            api_version=_first_env("CONTENT_UNDERSTANDING_API_VERSION") or "2025-11-01",
            analyzer_id=_first_env("CONTENT_UNDERSTANDING_ANALYZER_ID") or "prebuilt-invoice",
            scope=_first_env("CONTENT_UNDERSTANDING_SCOPE")
            or "https://cognitiveservices.azure.com/.default",
            timeout_seconds=_float_env("CONTENT_UNDERSTANDING_TIMEOUT_SECONDS", default=120.0),
            poll_interval_seconds=_float_env(
                "CONTENT_UNDERSTANDING_POLL_INTERVAL_SECONDS",
                default=1.0,
            ),
            max_polls=max(1, int(_float_env("CONTENT_UNDERSTANDING_MAX_POLLS", default=60))),
        )


class ContentUnderstandingClient:
    def __init__(
        self,
        config: ContentUnderstandingConfig | None = None,
        credential: Any | None = None,
    ) -> None:
        self._config = config or ContentUnderstandingConfig.from_env()
        if self._config is None:
            raise ContentUnderstandingNotConfiguredError(
                "CONTENT_UNDERSTANDING_ENDPOINT is not set."
            )
        self._credential = credential or DefaultAzureCredential()

    async def analyze_invoice_pdf(
        self,
        *,
        pdf_uri: str | None = None,
        pdf_base64: str | None = None,
    ) -> JsonDict:
        if not pdf_uri and not pdf_base64:
            raise ValueError("Either pdf_uri or pdf_base64 is required.")

        cfg = self._config
        assert cfg is not None
        token_provider = get_bearer_token_provider(self._credential, cfg.scope)
        input_type = "base64" if pdf_base64 else "url"
        headers = {
            "Authorization": f"Bearer {token_provider()}",
        }
        base_url = f"{cfg.endpoint}/contentunderstanding/analyzers/{cfg.analyzer_id}"
        params = {"api-version": cfg.api_version}
        if pdf_base64:
            analyze_url = f"{base_url}:analyzeBinary"
            headers["Content-Type"] = "application/pdf"
            request_kwargs: JsonDict = {
                "content": base64.b64decode(_normalized_content_understanding_base64(pdf_base64))
            }
        else:
            analyze_url = f"{base_url}:analyze"
            headers["Content-Type"] = "application/json"
            request_kwargs = {"json": {"inputs": [_content_understanding_url_input(pdf_uri)]}}

        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            with trace_span(
                "assurance_orchestrator.content_understanding.analyze",
                {
                    "gen_ai.agent.name": "assurance-orchestrator",
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "content_understanding_analyze",
                    "forge.content_understanding.analyzer_id": cfg.analyzer_id,
                    "forge.content_understanding.input_type": input_type,
                    "forge.rft.agent": "assurance-orchestrator",
                    "forge.rft.task_family": "invoice_pdf_extraction",
                },
            ) as span:
                response = await client.post(
                    analyze_url,
                    params=params,
                    headers=headers,
                    **request_kwargs,
                )
                set_span_attribute(span, "http.response.status_code", response.status_code)
                if response.is_error:
                    raise RuntimeError(
                        "Content Understanding analyze failed with "
                        f"HTTP {response.status_code}: "
                        f"{_content_understanding_error_message(response.text)}"
                    )
                operation_location = response.headers.get("Operation-Location")
                if not operation_location:
                    return _json_safe_payload(response.json())

                result = await self._poll_operation(
                    client,
                    operation_location,
                    headers=headers,
                )
                set_span_attribute(
                    span,
                    "forge.content_understanding.status",
                    result.get("status"),
                )
                return result

    async def _poll_operation(
        self,
        client: httpx.AsyncClient,
        operation_location: str,
        *,
        headers: dict[str, str],
    ) -> JsonDict:
        cfg = self._config
        assert cfg is not None
        terminal = {"succeeded", "failed", "canceled", "cancelled"}
        last_payload: JsonDict = {}
        for attempt in range(cfg.max_polls):
            if attempt:
                await asyncio.sleep(cfg.poll_interval_seconds)
            response = await client.get(operation_location, headers=headers)
            if response.is_error:
                raise RuntimeError(
                    "Content Understanding poll failed with "
                    f"HTTP {response.status_code}: {response.text[:500]}"
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Content Understanding poll returned a non-object payload.")
            last_payload = _json_safe_payload(payload)
            status = str(last_payload.get("status") or "").lower()
            if status in terminal:
                return last_payload
        raise TimeoutError(
            "Content Understanding analysis did not complete after "
            f"{cfg.max_polls} poll attempt(s). Last payload: {last_payload}"
        )


DEFAULT_MAX_RUNTIME_MINUTES = 30


def _default_max_runtime_minutes() -> int:
    """Resolve the default max_runtime_minutes from the environment.

    Ops can override the built-in 30-minute default via
    ``ASSURANCE_ORCHESTRATOR_MAX_RUNTIME_MINUTES``. This value MUST stay
    comfortably below the Waypoint stale-run reaper TTL
    (``APP_RUN_REAPER_TTL_SECONDS``) or legitimately-progressing runs get
    false-reaped. Invalid or non-positive values fall back to the default.
    """
    raw = os.environ.get("ASSURANCE_ORCHESTRATOR_MAX_RUNTIME_MINUTES")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_RUNTIME_MINUTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RUNTIME_MINUTES
    return value if value > 0 else DEFAULT_MAX_RUNTIME_MINUTES


@dataclass
class AssuranceOrchestratorRunConstraints:
    read_only: bool = True
    allowed_write_phase: str = "none"
    max_runtime_minutes: int = field(default_factory=_default_max_runtime_minutes)


@dataclass
class AssuranceOrchestratorRunItem:
    invoice_id: str | None = None
    finding_id: str | None = None
    pdf_uri: str | None = None
    pdf_base64: str | None = None
    document_id: str | None = None
    waypoint_case_id: str | None = None


@dataclass
class AssuranceOrchestratorWorkflowRequest:
    mode: Literal["run"] = "run"
    request_type: str = "invoice_assurance"
    batch_id: str | None = None
    source: str = "manual"
    items: list[AssuranceOrchestratorRunItem] = field(default_factory=list)
    constraints: AssuranceOrchestratorRunConstraints = field(default_factory=AssuranceOrchestratorRunConstraints)
    correlation: JsonDict = field(default_factory=dict)
    auth_context: JsonDict = field(default_factory=dict)
    limit: int = 1


@dataclass
class AssuranceOrchestratorWorkflowInput:
    request: AssuranceOrchestratorWorkflowRequest
    client: WaypointReader | None = None
    expert_client: ExpertValidatorClient | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    journal: AssuranceOrchestratorRunJournal | None = None


@dataclass
class StepRecord:
    name: str
    status: StepStatus
    attempts: int
    summary: str
    error: str | None = None


@dataclass
class WorkTarget:
    invoice_id: str
    finding_id: str | None
    waypoint_case_id: str | None
    summary: str | None
    pdf_uri: str | None = None
    pdf_base64: str | None = None
    document_id: str | None = None


@dataclass
class RunEnvelope:
    run_id: str
    batch_id: str
    source: str
    waypoint_case_id: str | None
    waypoint_run_id: str | None
    waypoint_action_id: str | None
    read_only: bool
    allowed_write_phase: str


@dataclass
class ValidatorResult:
    validator_id: str
    status: StepStatus
    summary: str
    findings: list[JsonDict] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    citations: list[JsonDict] = field(default_factory=list)
    confidence: float = 0.0
    source_system: str = "assurance_orchestrator"
    auth_mode: AuthMode = "placeholder"
    auth_audience: str | None = None
    execution_path: str = "placeholder"
    toolbox_tool_name: str | None = None
    latency_ms: int | None = None
    raw_reference: str | None = None
    error: str | None = None
    output_quality: OutputQuality = "unknown"
    unsupported: list[str] = field(default_factory=list)


@dataclass
class WorkflowRunResult:
    mode: Literal["run"]
    request_type: str
    status: WorkflowStatus
    run: JsonDict
    targets: list[JsonDict]
    documents: list[JsonDict]
    invoice_contexts: list[JsonDict]
    deterministic_checks: list[JsonDict]
    validators: list[JsonDict]
    judgements: list[JsonDict]
    write_plan: JsonDict
    auth_context: JsonDict
    steps: list[JsonDict]
    journal: JsonDict = field(default_factory=dict)
    side_effects_performed: bool = False


def run_assurance_orchestrator_invoice_assurance(
    request: str | dict[str, Any] | None = None,
    *,
    invoice_id: str | None = None,
    limit: int = 1,
    client: WaypointReader | None = None,
    expert_client: ExpertValidatorClient | None = None,
    retry_policy: RetryPolicy | None = None,
    max_runtime_seconds: float | None = None,
) -> dict[str, Any]:
    """Run the read-only invoice assurance workflow and return JSON-safe data."""
    return asyncio.run(
        run_assurance_orchestrator_invoice_assurance_async(
            request,
            invoice_id=invoice_id,
            limit=limit,
            client=client,
            expert_client=expert_client,
            retry_policy=retry_policy,
            max_runtime_seconds=max_runtime_seconds,
        )
    )


async def run_assurance_orchestrator_invoice_assurance_async(
    request: str | dict[str, Any] | None = None,
    *,
    invoice_id: str | None = None,
    limit: int = 1,
    client: WaypointReader | None = None,
    expert_client: ExpertValidatorClient | None = None,
    retry_policy: RetryPolicy | None = None,
    max_runtime_seconds: float | None = None,
) -> dict[str, Any]:
    """Run the read-only invoice assurance workflow from an existing event loop.

    The run is bounded by ``max_runtime_seconds`` (defaulting to the request's
    ``constraints.max_runtime_minutes``, 30 by default). Exceeding the budget cancels the
    in-flight fan-out and raises ``TimeoutError`` so a deterministic caller can finalize
    the run as ``failed`` instead of letting it orphan at ``running``.
    """
    workflow_request = normalize_workflow_request(request, invoice_id=invoice_id, limit=limit)
    workflow_input = AssuranceOrchestratorWorkflowInput(
        request=workflow_request,
        client=client,
        expert_client=expert_client,
        retry_policy=retry_policy or RetryPolicy(),
        journal=AssuranceOrchestratorRunJournal.from_env(),
    )
    budget = max_runtime_seconds
    if budget is None:
        minutes = workflow_request.constraints.max_runtime_minutes
        budget = minutes * 60 if minutes and minutes > 0 else None
    if budget is None or budget <= 0:
        return await _run_workflow(workflow_input)
    try:
        async with asyncio.timeout(budget):
            return await _run_workflow(workflow_input)
    except TimeoutError:
        # Cancelling the shared @workflow singleton mid-run leaves its internal
        # `_is_running` guard set, which would make EVERY subsequent run in this
        # long-lived hosted process fail with "Workflow is already running".
        # Reset the guard so the next run can proceed after a bounded timeout.
        _reset_workflow_running_guard()
        if workflow_input.journal is not None:
            workflow_input.journal.write(
                "failed",
                {"error": f"TimeoutError: workflow exceeded {budget:.0f}s runtime budget", "steps": []},
            )
        raise


def _reset_workflow_running_guard() -> None:
    """Best-effort clear the functional workflow's concurrency guard after a cancellation.

    ``asyncio.timeout`` cancels the in-flight ``run()`` await without letting the
    ResponseStream cleanup hook fire, so ``_is_running`` stays ``True`` on the module-level
    workflow singleton. A fresh ``message=`` run only needs that flag cleared; the run
    context is rebuilt per call. Guarded so a future framework change can't crash finalize.
    """
    workflow = assurance_orchestrator_invoice_assurance_workflow
    try:
        if getattr(workflow, "_is_running", False):
            workflow._is_running = False
    except Exception:  # never let guard-reset mask the TimeoutError we are finalizing
        logger.warning("could not reset assurance workflow running guard after timeout", exc_info=True)


async def _run_workflow(workflow_input: AssuranceOrchestratorWorkflowInput) -> dict[str, Any]:
    request = workflow_input.request
    invoice_ids = [item.invoice_id for item in request.items if item.invoice_id]
    enabled_validator_ids = _enabled_validator_ids()
    attrs = rft_reference_attributes(
        agent_name="assurance-orchestrator",
        task_family=request.request_type,
        scenario_id=request.batch_id,
        expected_tools=[
            "discover_work",
            "resolve_context",
            "deterministic_reconciliation",
            *[f"{validator_id}_validation" for validator_id in enabled_validator_ids],
            "prepare_waypoint_write_plan",
        ],
        grader_reference={
            "read_only": True,
            "side_effects_performed": False,
            "expected_validator_count": len(enabled_validator_ids),
        },
    )
    attrs.update(
        {
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "invoke_agent",
            "forge.assurance_orchestrator.request.source": request.source,
            "forge.assurance_orchestrator.request.limit": request.limit,
            "forge.assurance_orchestrator.invoice_ids": invoice_ids,
            "forge.assurance_orchestrator.read_only": True,
        }
    )
    journal = workflow_input.journal
    if journal is not None:
        journal.write("request_normalized", {"request": asdict(request)})
    with trace_span("assurance_orchestrator.workflow.run", attrs) as span:
        try:
            result = await assurance_orchestrator_invoice_assurance_workflow.run(workflow_input)
            outputs = result.get_outputs()
            if not outputs:
                raise RuntimeError("AssuranceOrchestrator workflow completed without an output.")
            output = outputs[-1]
            if isinstance(output, WorkflowRunResult):
                payload = _to_json_safe(asdict(output))
            elif isinstance(output, dict):
                payload = _to_json_safe(output)
            else:
                raise RuntimeError(f"Unexpected AssuranceOrchestrator workflow output: {type(output).__name__}")
            set_span_attribute(span, "forge.assurance_orchestrator.status", payload.get("status"))
            set_span_attribute(span, "forge.assurance_orchestrator.target_count", len(payload.get("targets", [])))
            set_span_attribute(span, "forge.assurance_orchestrator.validator_count", len(payload.get("validators", [])))
            set_span_attribute(span, "forge.assurance_orchestrator.side_effects_performed", payload.get("side_effects_performed"))
            return payload
        except Exception as exc:
            if journal is not None:
                journal.write(
                    "failed",
                    {"error": f"{type(exc).__name__}: {exc}", "steps": []},
                )
            raise


@workflow(
    name="assurance_orchestrator_invoice_assurance",
    description="Read-only invoice assurance workflow with fan-out validators and step retries.",
)
async def assurance_orchestrator_invoice_assurance_workflow(
    workflow_input: AssuranceOrchestratorWorkflowInput,
    ctx: RunContext,
) -> WorkflowRunResult:
    client = workflow_input.client or WaypointReadOnlyClient()
    expert_client = (
        workflow_input.expert_client
        or FoundryPromptExpertClient.from_env()
        or HostedResponsesExpertClient.from_env()
        or ToolboxExpertClient.from_env()
    )
    request = workflow_input.request
    steps: list[StepRecord] = []
    journal = workflow_input.journal

    await _event(ctx, "assurance_orchestrator.run.started", {"batch_id": request.batch_id, "source": request.source})

    work = await _run_with_retry(
        "discover_work",
        lambda: discover_work(request, client),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("work_discovered", {"targets": [asdict(target) for target in work]})
    run = await _run_with_retry(
        "prepare_run",
        lambda: prepare_run(request, work),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("run_prepared", {"run": asdict(run)})
    documents = await _run_with_retry(
        "resolve_documents",
        lambda: resolve_documents(work),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("documents_resolved", {"documents": documents})
    contexts = await _run_with_retry(
        "resolve_context",
        lambda: resolve_context(work, client),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("context_resolved", {"invoice_contexts": contexts})
    checks = await _run_with_retry(
        "deterministic_reconciliation",
        lambda: deterministic_reconciliation(work, contexts),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("deterministic_reconciliation", {"deterministic_checks": checks})

    validators = await fan_out_validators(
        work,
        contexts,
        checks,
        expert_client=expert_client,
        retry_policy=workflow_input.retry_policy,
        steps=steps,
    )
    if journal is not None:
        journal.write("validators_completed", {"validators": [asdict(validator) for validator in validators]})
    judgements = await _run_with_retry(
        "synthesize_judgement",
        lambda: synthesize_judgement(run, work, contexts, checks, validators),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("judgement_synthesized", {"judgements": judgements})
    write_plan = await _run_with_retry(
        "prepare_waypoint_write_plan",
        lambda: prepare_waypoint_write_plan(run, judgements, validators),
        workflow_input.retry_policy,
        steps,
    )
    if journal is not None:
        journal.write("write_plan_prepared", {"write_plan": write_plan})

    status: WorkflowStatus = "completed"
    if any(step.status == "failed" for step in steps):
        status = "partial"
    if not work:
        status = "failed"

    await _event(
        ctx,
        "assurance_orchestrator.run.completed",
        {
            "run_id": run.run_id,
            "status": status,
            "target_count": len(work),
            "side_effects_performed": False,
        },
    )

    result = WorkflowRunResult(
        mode="run",
        request_type=request.request_type,
        status=status,
        run=asdict(run),
        targets=[asdict(target) for target in work],
        documents=documents,
        invoice_contexts=contexts,
        deterministic_checks=checks,
        validators=[asdict(validator) for validator in validators],
        judgements=judgements,
        write_plan=write_plan,
        auth_context=_workflow_auth_context(request, expert_client),
        steps=[asdict(step) for step in steps],
        journal={"enabled": True, "run_dir": str(journal.run_dir)} if journal else {"enabled": False},
        side_effects_performed=False,
    )
    if journal is not None:
        journal.write("completed", asdict(result))
    return result


@step
async def discover_work(request: AssuranceOrchestratorWorkflowRequest, client: WaypointReader) -> list[WorkTarget]:
    requested_items = [item for item in request.items if item.invoice_id]
    if requested_items:
        return [
            WorkTarget(
                invoice_id=str(item.invoice_id),
                finding_id=item.finding_id,
                waypoint_case_id=item.waypoint_case_id,
                summary=None,
                pdf_uri=item.pdf_uri,
                pdf_base64=item.pdf_base64,
                document_id=item.document_id,
            )
            for item in requested_items
        ]

    work_items = _as_dicts(client.get_work())
    targets: list[WorkTarget] = []
    for item in work_items[: max(1, min(request.limit, 25))]:
        invoice_id = item.get("invoice_id")
        if not invoice_id:
            continue
        targets.append(
            WorkTarget(
                invoice_id=str(invoice_id),
                finding_id=_as_optional_str(item.get("finding_id")),
                waypoint_case_id=_as_optional_str(item.get("case_id")),
                summary=_as_optional_str(item.get("summary")),
                pdf_uri=_as_optional_str(item.get("pdf_uri")),
                pdf_base64=_as_optional_str(item.get("pdf_base64")),
                document_id=_as_optional_str(item.get("document_id")),
            )
        )
    return targets


@step
async def prepare_run(request: AssuranceOrchestratorWorkflowRequest, targets: list[WorkTarget]) -> RunEnvelope:
    first_case_id = next((target.waypoint_case_id for target in targets if target.waypoint_case_id), None)
    return RunEnvelope(
        run_id=f"assurance_orchestrator-{uuid.uuid4()}",
        batch_id=request.batch_id or f"batch-{uuid.uuid4()}",
        source=request.source,
        waypoint_case_id=_as_optional_str(request.correlation.get("waypoint_case_id")) or first_case_id,
        waypoint_run_id=_as_optional_str(request.correlation.get("waypoint_run_id")),
        waypoint_action_id=_as_optional_str(request.correlation.get("waypoint_action_id")),
        read_only=True,
        allowed_write_phase="none",
    )


@step
async def resolve_documents(targets: list[WorkTarget]) -> list[JsonDict]:
    documents = []
    cu_client = _content_understanding_client()
    for target in targets:
        has_inline_pdf = bool(target.pdf_base64)
        document = {
            "invoice_id": target.invoice_id,
            "pdf_uri": target.pdf_uri,
            "pdf_base64_present": has_inline_pdf,
            "pdf_base64_length": len(target.pdf_base64) if target.pdf_base64 else 0,
            "document_id": target.document_id,
            "status": "referenced"
            if target.pdf_uri or has_inline_pdf or target.document_id
            else "not_provided",
            "content_understanding_status": "not_invoked",
            "summary": (
                "No PDF/document reference was provided; using Waypoint invoice context only."
            ),
        }
        if target.pdf_uri or target.pdf_base64:
            if cu_client is None:
                document.update(
                    {
                        "content_understanding_status": "not_configured",
                        "summary": (
                            "PDF input was provided, but CONTENT_UNDERSTANDING_ENDPOINT "
                            "is not configured."
                        ),
                    }
                )
            else:
                try:
                    result = await cu_client.analyze_invoice_pdf(
                        pdf_uri=target.pdf_uri,
                        pdf_base64=target.pdf_base64,
                    )
                    status = str(result.get("status") or "succeeded").lower()
                    document.update(
                        {
                            "content_understanding_status": status,
                            "summary": _content_understanding_summary(result),
                            "analyzer_result": _content_understanding_summary_payload(result),
                        }
                    )
                except Exception as exc:
                    document.update(
                        {
                            "content_understanding_status": "failed",
                            "summary": "Content Understanding PDF extraction failed.",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
        elif target.document_id:
            document["summary"] = (
                "Document id captured, but no PDF URL or base64 bytes were provided "
                "for Content Understanding."
            )
        documents.append(document)
    return documents


@step
async def resolve_context(targets: list[WorkTarget], client: WaypointReader) -> list[JsonDict]:
    contexts = []
    for target in targets:
        context = client.get_invoice_context(target.invoice_id)
        if not isinstance(context, dict):
            context = {"invoice": {"id": target.invoice_id}, "metadata": {"context_shape": type(context).__name__}}
        contexts.append(_summarize_context(target.invoice_id, context))
    return contexts


@step
async def deterministic_reconciliation(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
) -> list[JsonDict]:
    checks = []
    context_by_invoice = {context.get("invoice_id"): context for context in contexts}
    for target in targets:
        context = context_by_invoice.get(target.invoice_id, {})
        invoice = context.get("invoice", {})
        findings = _as_dicts(context.get("findings"))
        lines = _as_dicts(invoice.get("lines"))
        total_amount = _decimal_or_none(invoice.get("total_amount"))
        line_sum = sum((_decimal_or_none(line.get("amount")) or Decimal("0")) for line in lines)
        math_status = "not_evaluated"
        math_delta: str | None = None
        if total_amount is not None and lines:
            delta = total_amount - line_sum
            math_delta = str(delta)
            math_status = "matched" if abs(delta) <= Decimal("0.01") else "variance"
        checks.append(
            {
                "invoice_id": target.invoice_id,
                "status": "variance" if findings or math_status == "variance" else "matched",
                "duplicate_check": "not_evaluated",
                "po_receipt_check": "not_evaluated",
                "line_math_check": math_status,
                "line_math_delta": math_delta,
                "known_finding_count": len(findings),
                "summary": _deterministic_summary(findings, math_status),
            }
        )
    return checks


async def fan_out_validators(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    *,
    expert_client: ExpertValidatorClient | None,
    retry_policy: RetryPolicy,
    steps: list[StepRecord],
) -> list[ValidatorResult]:
    validators: list[tuple[str, Callable[[], Any]]] = []
    for validator_id, validator in (
        ("webiq", webiq_validation),
        ("fabriciq", fabriciq_validation),
        ("workiq", workiq_validation),
        ("foundryiq", foundryiq_validation),
    ):
        if is_expert_enabled(validator_id):
            validators.append(
                (
                    f"{validator_id}_validation",
                    lambda validator=validator: validator(targets, contexts, checks, expert_client),
                )
            )
    results = await asyncio.gather(
        *(
            _run_with_retry(
                name,
                func,
                retry_policy,
                steps,
                failed_result_factory=_validator_failure(name, _expert_execution_path(expert_client)),
            )
            for name, func in validators
        )
    )
    return [result for result in results if isinstance(result, ValidatorResult)]


def _enabled_validator_ids() -> list[str]:
    return [validator_id for validator_id in EXPERT_TOOL_SPECS if is_expert_enabled(validator_id)]


@step
async def webiq_validation(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    expert_client: ExpertValidatorClient | None = None,
) -> ValidatorResult:
    live_result = await _call_live_expert("webiq", targets, contexts, checks, expert_client)
    if live_result is not None:
        return live_result
    del contexts, checks
    return ValidatorResult(
        validator_id="webiq",
        status="partial",
        summary=(
            "WebIQ market/financial trend validation is planned but not yet connected. "
            f"Captured {len(targets)} target invoice(s) for future external context checks."
        ),
        confidence=0.2,
        source_system="webiq",
        auth_mode="placeholder",
        auth_audience=EXPERT_TOOL_SPECS["webiq"].auth_audience,
        execution_path="placeholder",
        toolbox_tool_name=EXPERT_TOOL_SPECS["webiq"].tool_name,
    )


@step
async def fabriciq_validation(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    expert_client: ExpertValidatorClient | None = None,
) -> ValidatorResult:
    live_result = await _call_live_expert("fabriciq", targets, contexts, checks, expert_client)
    if live_result is not None:
        return live_result
    findings = [
        {
            "invoice_id": check.get("invoice_id"),
            "category": "deterministic_reconciliation",
            "summary": check.get("summary"),
            "status": check.get("status"),
        }
        for check in checks
        if check.get("status") != "matched"
    ]
    return ValidatorResult(
        validator_id="fabriciq",
        status="completed",
        summary=(
            "Fabric IQ placeholder used deterministic reconciliation outputs as the "
            "structured data integrity signal."
        ),
        findings=findings,
        confidence=0.65 if targets else 0.0,
        source_system="fabriciq",
        auth_mode="placeholder",
        auth_audience=EXPERT_TOOL_SPECS["fabriciq"].auth_audience,
        execution_path="placeholder",
        toolbox_tool_name=EXPERT_TOOL_SPECS["fabriciq"].tool_name,
    )


@step
async def workiq_validation(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    expert_client: ExpertValidatorClient | None = None,
) -> ValidatorResult:
    live_result = await _call_live_expert("workiq", targets, contexts, checks, expert_client)
    if live_result is not None:
        return live_result
    del checks
    evidence_ids = _unique(
        evidence.get("id")
        for context in contexts
        for evidence in _as_dicts(context.get("evidence"))
        if str(evidence.get("evidence_type", "")).lower() in {"email", "teams", "approval", "correspondence"}
    )
    return ValidatorResult(
        validator_id="workiq",
        status="completed" if evidence_ids else "partial",
        summary=(
            f"Found {len(evidence_ids)} communication/approval evidence item(s)."
            if evidence_ids
            else "No WorkIQ communication evidence was present in the Waypoint context bundle."
        ),
        evidence_ids=evidence_ids,
        confidence=0.7 if evidence_ids else 0.25,
        source_system="workiq",
        auth_mode="placeholder",
        auth_audience=EXPERT_TOOL_SPECS["workiq"].auth_audience,
        execution_path="placeholder",
        toolbox_tool_name=EXPERT_TOOL_SPECS["workiq"].tool_name,
    )


@step
async def foundryiq_validation(
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    expert_client: ExpertValidatorClient | None = None,
) -> ValidatorResult:
    live_result = await _call_live_expert("foundryiq", targets, contexts, checks, expert_client)
    if live_result is not None:
        return live_result
    del targets, checks
    evidence_ids = _unique(
        evidence.get("id")
        for context in contexts
        for evidence in _as_dicts(context.get("evidence"))
    )
    policy_ids = _unique(
        policy.get("id")
        for context in contexts
        for policy in _as_dicts(context.get("policies"))
    )
    contract_ids = _unique(
        document.get("id")
        for context in contexts
        for document in _as_dicts(context.get("contract_documents"))
    )
    return ValidatorResult(
        validator_id="foundryiq",
        status="completed" if policy_ids or contract_ids else "partial",
        summary=(
            f"Grounded context includes {len(contract_ids)} contract document(s), "
            f"{len(policy_ids)} policy document(s), and {len(evidence_ids)} evidence item(s)."
        ),
        evidence_ids=evidence_ids,
        confidence=0.8 if policy_ids or contract_ids else 0.35,
        source_system="foundryiq",
        auth_mode="placeholder",
        auth_audience=EXPERT_TOOL_SPECS["foundryiq"].auth_audience,
        execution_path="placeholder",
        toolbox_tool_name=EXPERT_TOOL_SPECS["foundryiq"].tool_name,
    )


@step
async def synthesize_judgement(
    run: RunEnvelope,
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    validators: list[ValidatorResult],
) -> list[JsonDict]:
    context_by_invoice = {context.get("invoice_id"): context for context in contexts}
    checks_by_invoice = {check.get("invoice_id"): check for check in checks}
    all_validator_evidence = _unique(
        evidence_id for validator in validators for evidence_id in validator.evidence_ids
    )
    judgements: list[JsonDict] = []
    for target in targets:
        context = context_by_invoice.get(target.invoice_id, {})
        findings = _as_dicts(context.get("findings"))
        check = checks_by_invoice.get(target.invoice_id, {})
        severity = _highest_severity(findings)
        status = _judgement_status(findings, check)
        decision = _waypoint_decision(status)
        money_at_risk = _money_at_risk(findings)
        evidence_ids = _unique(
            [
                *all_validator_evidence,
                *(evidence_id for finding in findings for evidence_id in _as_list(finding.get("evidence_ids"))),
            ]
        )
        judgements.append(
            {
                "invoice_id": target.invoice_id,
                "waypoint_case_id": target.waypoint_case_id or run.waypoint_case_id,
                "waypoint_run_id": run.waypoint_run_id,
                "waypoint_action_id": run.waypoint_action_id,
                "status": status,
                "waypoint_decision": decision,
                "severity": severity,
                "category": findings[0].get("category") if findings else "no_known_exception",
                "money_at_risk": str(money_at_risk),
                "confidence": _average_confidence(validators),
                "summary": _judgement_summary(target, findings, check),
                "basis_summary": _basis_summary(findings, validators),
                "evidence_ids": evidence_ids,
                "contract_document_ids": _unique(
                    document.get("id") for document in _as_dicts(context.get("contract_documents"))
                ),
                "policy_ids": _unique(policy.get("id") for policy in _as_dicts(context.get("policies"))),
                "contradictory_evidence_ids": [],
                "proposed_next_actions": _proposed_actions(decision, context),
                "side_effects_performed": False,
            }
        )
    return judgements


@step
async def prepare_waypoint_write_plan(
    run: RunEnvelope,
    judgements: list[JsonDict],
    validators: list[ValidatorResult],
) -> JsonDict:
    expert_evidence = _expert_evidence_metadata(validators)
    return {
        "read_only": True,
        "allowed_write_phase": run.allowed_write_phase,
        "side_effects_performed": False,
        "post_operations_prepared": [],
        "prohibited_operations": [
            "POST /api/cases",
            "POST /api/cases/{case_id}/recommendations",
            "POST /api/cases/{case_id}/drafts",
            "POST /api/cases/{case_id}/actions",
            "POST /api/cases/{case_id}/approvals",
            "POST /api/actions/{action_id}/authorize",
            "POST /api/runs",
        ],
        "future_payloads": [
            {
                "invoice_id": judgement.get("invoice_id"),
                "waypoint_case_id": judgement.get("waypoint_case_id"),
                "recommendation": {
                    "decision": judgement.get("waypoint_decision"),
                    "reasoning": judgement.get("basis_summary"),
                    "confidence": judgement.get("confidence"),
                    "money_at_risk": judgement.get("money_at_risk"),
                    "evidence_ids": judgement.get("evidence_ids", []),
                    "proposed_next_actions": judgement.get("proposed_next_actions", []),
                    "metadata": {
                        "assurance_orchestrator_run_id": run.run_id,
                        "read_only_preview": True,
                        "confidence_basis": "expert_evidence_mean",
                        "confidence_calibrated": False,
                        "expert_evidence": expert_evidence,
                    },
                },
            }
            for judgement in judgements
        ],
    }


def _expert_evidence_metadata(validators: list[ValidatorResult]) -> list[JsonDict]:
    lanes: list[JsonDict] = []
    for validator in validators:
        evidence = [
            {
                "claim": finding.get("summary"),
                "supports": finding.get("status") or "unknown",
                "source_ref": _first_evidence_ref(finding),
                "classification": finding.get("classification") or "standard",
                "confidence": validator.confidence,
            }
            for finding in validator.findings
            if finding.get("summary")
        ]
        lanes.append(
            {
                "agent": EXPERT_AGENT_NAMES.get(validator.validator_id, validator.validator_id),
                "plane": validator.validator_id,
                "summary": validator.summary,
                "status": validator.status,
                "output_quality": validator.output_quality,
                "unsupported": validator.unsupported,
                "evidence": evidence,
            }
        )
    return lanes


def _first_evidence_ref(finding: JsonDict) -> str:
    evidence_ids = _as_list(finding.get("evidence_ids"))
    return str(evidence_ids[0]) if evidence_ids else ""


async def _run_with_retry(
    name: str,
    func: Callable[[], Any],
    retry_policy: RetryPolicy,
    steps: list[StepRecord],
    *,
    failed_result_factory: Callable[[Exception, int], Any] | None = None,
) -> Any:
    attempts = 0
    while True:
        attempts += 1
        try:
            with trace_span(
                f"assurance_orchestrator.workflow.step {name}",
                {
                    "gen_ai.agent.name": "assurance-orchestrator",
                    "gen_ai.operation.name": "execute_tool",
                    "forge.workflow.step.name": name,
                    "forge.workflow.step.attempt": attempts,
                    "forge.rft.agent": "assurance-orchestrator",
                    "forge.rft.task_family": "invoice_assurance",
                },
            ) as span:
                result = await func()
                set_span_attribute(span, "forge.workflow.step.status", _result_status(result))
                set_span_attribute(span, "forge.workflow.step.summary", _result_summary(result))
            steps.append(
                StepRecord(
                    name=name,
                    status=_result_status(result),
                    attempts=attempts,
                    summary=_result_summary(result),
                )
            )
            return result
        except Exception as exc:
            if attempts >= retry_policy.max_attempts:
                steps.append(
                    StepRecord(
                        name=name,
                        status="failed",
                        attempts=attempts,
                        summary=f"{name} failed after {attempts} attempt(s).",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                if failed_result_factory:
                    return failed_result_factory(exc, attempts)
                raise
            await asyncio.sleep(retry_policy.backoff_seconds * attempts)


def _validator_failure(name: str, execution_path: str | None = None) -> Callable[[Exception, int], ValidatorResult]:
    def _factory(exc: Exception, attempts: int) -> ValidatorResult:
        validator_id = name.removesuffix("_validation")
        spec = EXPERT_TOOL_SPECS.get(validator_id)
        return ValidatorResult(
            validator_id=validator_id,
            status="failed",
            summary=f"{name} failed after {attempts} attempt(s).",
            confidence=0.0,
            source_system=spec.source_system if spec else validator_id,
            auth_mode=spec.auth_mode if spec else "placeholder",
            auth_audience=spec.auth_audience if spec else None,
            execution_path=execution_path or ("foundry_toolbox" if spec and spec.tool_name else "placeholder"),
            toolbox_tool_name=spec.tool_name if spec else None,
            error=f"{type(exc).__name__}: {exc}",
            output_quality="malformed",
        )

    return _factory


def _expert_execution_path(expert_client: ExpertValidatorClient | None) -> str | None:
    if expert_client is None:
        return None
    execution_path = getattr(expert_client, "execution_path", None)
    if execution_path in {"foundry_prompt_agent", "responses_agent", "foundry_toolbox"}:
        return execution_path
    return "foundry_toolbox"


async def _call_live_expert(
    validator_id: str,
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
    expert_client: ExpertValidatorClient | None,
) -> ValidatorResult | None:
    spec = EXPERT_TOOL_SPECS[validator_id]
    if expert_client is None:
        return None

    tool_name = await expert_client.resolve_tool_name(validator_id)
    if not tool_name:
        return None

    started = time.perf_counter()
    arguments = _expert_tool_arguments(validator_id, targets, contexts, checks)
    with trace_span(
        f"assurance_orchestrator.expert_validator {validator_id}",
        {
            **rft_reference_attributes(
                agent_name="assurance-orchestrator",
                task_family="invoice_assurance_validation",
                scenario_id=",".join(target.invoice_id for target in targets) or None,
                expected_tools=[tool_name],
                grader_reference={
                    "validator_id": validator_id,
                    "expected_status": "completed",
                    "read_only": True,
                },
            ),
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
            "forge.validator.id": validator_id,
            "forge.validator.execution_path": _expert_execution_path(expert_client),
            "forge.invoice.ids": [target.invoice_id for target in targets],
        },
    ) as span:
        try:
            raw_result = await expert_client.call_validator(validator_id, arguments)
        except ToolNotConfiguredError:
            set_span_attribute(span, "forge.validator.configured", False)
            return None
        latency_ms = round((time.perf_counter() - started) * 1000)
        result = _normalize_expert_result(
            validator_id,
            _json_safe_payload(raw_result),
            latency_ms=latency_ms,
            tool_name=tool_name,
        )
        set_span_attribute(span, "forge.validator.status", result.status)
        set_span_attribute(span, "forge.validator.confidence", result.confidence)
        set_span_attribute(span, "forge.validator.finding_count", len(result.findings))
        set_span_attribute(span, "forge.validator.evidence_count", len(result.evidence_ids))
        return result


def _expert_tool_arguments(
    validator_id: str,
    targets: list[WorkTarget],
    contexts: list[JsonDict],
    checks: list[JsonDict],
) -> JsonDict:
    invoice_ids = ", ".join(target.invoice_id for target in targets) or "none"
    return {
        "query": (
            f"Validate invoice assurance signals for invoice(s): {invoice_ids}. "
            "Use the provided deterministic checks and context. Return repairable "
            "expert_evidence JSON with claims, source refs, confidence, and unsupported items."
        ),
        "task": "invoice_assurance_validation",
        "validator_id": validator_id,
        "read_only": True,
        "targets": [asdict(target) for target in targets],
        "invoice_contexts": contexts,
        "deterministic_checks": checks,
        "instructions": (
            "Return a JSON object with status, summary, confidence, expert_evidence, "
            "citations, and unsupported/unknown items. Do not stage approvals, "
            "authorize actions, or perform side effects."
        ),
    }


def _normalize_expert_result(
    validator_id: str,
    payload: Any,
    *,
    latency_ms: int,
    tool_name: str,
) -> ValidatorResult:
    spec = EXPERT_TOOL_SPECS[validator_id]
    content = _extract_structured_content(payload)
    summary = _as_optional_str(content.get("summary")) or _as_optional_str(content.get("answer"))
    if not summary:
        summary = f"{spec.source_system} returned a live toolbox response."

    evidence = _expert_evidence_items(content)
    evidence_ids = _unique(
        [
            *_as_list(content.get("evidence_ids")),
            *(item.get("id") or _source_ref(item) for item in evidence),
        ]
    )
    findings = _as_dicts(content.get("findings")) or _findings_from_expert_evidence(
        validator_id,
        content,
        evidence,
    )
    status = str(content.get("status") or "completed").lower()
    if status not in {"completed", "partial", "failed"}:
        status = "completed"
    output_quality = _validator_output_quality(content, evidence, payload)
    if output_quality in {"malformed", "partial", "no_evidence"} and status == "completed":
        status = "partial"

    confidence = _float_or_default(content.get("confidence"), default=0.75)
    return ValidatorResult(
        validator_id=validator_id,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        findings=findings,
        evidence_ids=evidence_ids,
        citations=_as_dicts(content.get("citations")) or _extract_citations(payload),
        confidence=confidence,
        source_system=spec.source_system,
        auth_mode=spec.auth_mode,
        auth_audience=spec.auth_audience,
        execution_path=_as_optional_str(content.get("execution_path")) or "foundry_toolbox",
        toolbox_tool_name=tool_name,
        latency_ms=latency_ms,
        raw_reference=_as_optional_str(content.get("raw_reference"))
        or _as_optional_str(content.get("trace_id")),
        output_quality=output_quality,
        unsupported=_unique(content.get("unsupported") or content.get("unknowns") or []),
    )


def _extract_structured_content(payload: Any) -> JsonDict:
    if isinstance(payload, dict):
        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        if isinstance(result.get("structured_content"), dict):
            return result["structured_content"]
        parsed = _parse_text_content(result.get("content"))
        if parsed:
            return parsed
        return result
    return {}


def _extract_citations(payload: Any) -> list[JsonDict]:
    if not isinstance(payload, dict):
        return []
    content = payload.get("content")
    citations: list[JsonDict] = []
    for item in _as_list(content):
        if not isinstance(item, dict):
            continue
        resource = item.get("resource")
        if isinstance(resource, dict):
            meta = resource.get("_meta")
            if isinstance(meta, dict):
                citations.extend(_as_dicts(meta.get("annotations")))
        meta = item.get("_meta")
        if isinstance(meta, dict):
            citations.extend(_as_dicts(meta.get("annotations")))
    documents = _as_dicts(_extract_structured_content(payload).get("documents"))
    citations.extend(
        {
            "id": document.get("id"),
            "title": document.get("title"),
            "url": document.get("url"),
            "score": document.get("score"),
            "source": document.get("knowledgeSourceIndex"),
        }
        for document in documents
    )
    return citations


def _expert_evidence_items(content: JsonDict) -> list[JsonDict]:
    evidence = _as_dicts(content.get("evidence"))
    if evidence:
        return evidence
    return _as_dicts(content.get("expert_evidence"))


def _findings_from_expert_evidence(
    validator_id: str,
    content: JsonDict,
    evidence: list[JsonDict],
) -> list[JsonDict]:
    invoice_id = _as_optional_str(content.get("invoice_id"))
    findings: list[JsonDict] = []
    for item in evidence:
        summary = _claim_text(item)
        if not summary:
            continue
        findings.append(
            {
                "invoice_id": invoice_id,
                "category": validator_id,
                "summary": summary,
                "status": item.get("supports") or "unknown",
                "evidence_ids": _unique([item.get("id"), _source_ref(item), item.get("source")]),
                "classification": item.get("classification"),
            }
        )
    return findings


def _validator_output_quality(content: JsonDict, evidence: list[JsonDict], payload: Any) -> OutputQuality:
    explicit = str(content.get("output_quality") or "").strip().lower()
    if explicit in {"valid", "partial", "malformed", "no_evidence"}:
        return explicit  # type: ignore[return-value]
    findings = _as_dicts(content.get("findings"))
    evidence_ids = _as_list(content.get("evidence_ids"))
    if _has_unparsed_text_content(payload) and not evidence and not content.get("findings"):
        return "malformed"
    if findings and evidence_ids:
        return "valid"
    if findings:
        return "partial"
    if not evidence:
        return "no_evidence"
    if evidence and all(_claim_text(item) and _source_ref(item) for item in evidence):
        return "valid"
    return "partial"


def _has_unparsed_text_content(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    content = result.get("content")
    for item in _as_list(content):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return True
    return False


def _claim_text(item: JsonDict) -> str:
    return str(item.get("claim") or item.get("summary") or item.get("snippet") or "").strip()


def _source_ref(item: JsonDict) -> str:
    direct = item.get("source_ref") or item.get("source") or item.get("url")
    if direct:
        return str(direct)
    source_refs = _as_list(item.get("source_refs"))
    return str(source_refs[0]) if source_refs else ""


def _parse_text_content(content: Any) -> JsonDict:
    for item in _as_list(content):
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


async def _event(ctx: RunContext, name: str, payload: JsonDict) -> None:
    del ctx, name, payload
    # Agent Framework custom events require typed WorkflowEvent instances in this
    # preview build. Keep progress as a future enhancement and rely on @step
    # events plus the returned step records for now.
    return


def normalize_workflow_request(
    request: str | dict[str, Any] | None,
    *,
    invoice_id: str | None = None,
    limit: int = 1,
) -> AssuranceOrchestratorWorkflowRequest:
    payload: dict[str, Any]
    if isinstance(request, str) and request.strip():
        try:
            payload = json.loads(request)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "assurance_orchestrator_run_invoice_assurance_workflow: request_json is not valid JSON "
                f"at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from exc
    elif isinstance(request, dict):
        payload = request
    else:
        payload = {}
    if "assurance_orchestrator_request" in payload and isinstance(payload["assurance_orchestrator_request"], dict):
        payload = payload["assurance_orchestrator_request"]

    items_payload = payload.get("items")
    items: list[AssuranceOrchestratorRunItem] = []
    if isinstance(items_payload, list):
        for item in items_payload:
            if isinstance(item, dict):
                items.append(
                    AssuranceOrchestratorRunItem(
                        invoice_id=_as_optional_str(item.get("invoice_id")),
                        finding_id=_as_optional_str(item.get("finding_id")),
                        pdf_uri=_as_optional_str(item.get("pdf_uri")),
                        pdf_base64=_normalize_base64_input(item.get("pdf_base64")),
                        document_id=_as_optional_str(item.get("document_id")),
                        waypoint_case_id=_as_optional_str(item.get("waypoint_case_id")),
                    )
                )

    single_invoice_id = invoice_id or _as_optional_str(payload.get("invoice_id"))
    if single_invoice_id and not any(item.invoice_id == single_invoice_id for item in items):
        items.append(
            AssuranceOrchestratorRunItem(
                invoice_id=single_invoice_id,
                finding_id=_as_optional_str(payload.get("finding_id")),
                pdf_uri=_as_optional_str(payload.get("pdf_uri")),
                pdf_base64=_normalize_base64_input(payload.get("pdf_base64")),
                document_id=_as_optional_str(payload.get("document_id")),
                waypoint_case_id=_as_optional_str(payload.get("waypoint_case_id")),
            )
        )

    constraints_payload = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    constraints = AssuranceOrchestratorRunConstraints(
        read_only=True,
        allowed_write_phase="none",
        max_runtime_minutes=int(constraints_payload.get("max_runtime_minutes") or _default_max_runtime_minutes()),
    )
    return AssuranceOrchestratorWorkflowRequest(
        mode="run",
        request_type=str(payload.get("request_type") or "invoice_assurance"),
        batch_id=_as_optional_str(payload.get("batch_id")),
        source=str(payload.get("source") or "manual"),
        items=items,
        constraints=constraints,
        correlation=payload.get("correlation") if isinstance(payload.get("correlation"), dict) else {},
        auth_context=payload.get("auth_context") if isinstance(payload.get("auth_context"), dict) else {},
        limit=int(payload.get("limit") or limit),
    )


def _summarize_context(invoice_id: str, context: JsonDict) -> JsonDict:
    invoice = context.get("invoice") if isinstance(context.get("invoice"), dict) else {}
    invoice = dict(invoice)
    invoice.setdefault("id", invoice_id)
    return {
        "invoice_id": invoice_id,
        "invoice": invoice,
        "findings": _as_dicts(
            invoice.get("findings")
            if invoice.get("findings") is not None
            else context.get("findings")
        ),
        "evidence": _as_dicts(
            invoice.get("evidence")
            if invoice.get("evidence") is not None
            else context.get("evidence")
        ),
        "contract_documents": _as_dicts(context.get("contract_documents")),
        "policies": _as_dicts(context.get("policies")),
        "cases": _as_dicts(context.get("cases")),
        "allowed_actions": _as_dicts(context.get("allowed_actions")),
        "redactions": _as_list(context.get("redactions")),
        "metadata": context.get("metadata") if isinstance(context.get("metadata"), dict) else {},
    }


def _deterministic_summary(findings: list[JsonDict], math_status: str) -> str:
    if findings:
        return f"Waypoint context already includes {len(findings)} finding(s)."
    if math_status == "variance":
        return "Invoice line math does not match the invoice total."
    if math_status == "matched":
        return "Invoice line math matches and no existing findings were present."
    return "No deterministic variance was identified from the available context."


def _result_status(result: Any) -> StepStatus:
    if isinstance(result, ValidatorResult):
        return result.status
    if isinstance(result, list):
        return "completed" if result else "partial"
    return "completed"


def _result_summary(result: Any) -> str:
    if isinstance(result, ValidatorResult):
        return result.summary
    if isinstance(result, RunEnvelope):
        return f"Prepared run envelope {result.run_id}."
    if isinstance(result, list):
        return f"Produced {len(result)} item(s)."
    if isinstance(result, dict):
        return f"Produced {len(result)} field(s)."
    return "Step completed."


def _is_actionable_finding(finding: JsonDict) -> bool:
    """Return True when a finding should drive a variance/escalate decision.

    The Waypoint seed attaches a finding to every invoice, including clean ones
    (``status == "approved"`` with ``overpayment_amount == 0`` and ``severity
    "low"``). Those non-actionable findings must not force a truly clean invoice
    into ``variance``/``review`` — otherwise the ``matched`` -> ``approve`` branch
    is never reachable. High/critical severity findings are always treated as
    actionable so real exceptions still escalate.
    """
    severity = str(finding.get("severity") or "").lower()
    if severity in {"high", "critical"}:
        return True
    if str(finding.get("status") or "").lower() == "approved":
        return False
    overpayment = _decimal_or_none(finding.get("overpayment_amount"))
    if overpayment is not None and overpayment == 0:
        return False
    return True


def _judgement_status(findings: list[JsonDict], check: JsonDict) -> str:
    actionable = [finding for finding in findings if _is_actionable_finding(finding)]
    if actionable:
        if any(str(finding.get("severity", "")).lower() in {"high", "critical"} for finding in actionable):
            return "escalated"
        return "variance"
    # Fall back to the deterministic math signal only. ``check["status"]`` is
    # forced to "variance" whenever *any* finding is present (even a clean,
    # non-actionable one), so use ``line_math_check`` to avoid re-introducing
    # the variance a non-actionable finding would otherwise imply.
    if check.get("line_math_check") == "variance":
        return "variance"
    return "matched"


def _waypoint_decision(status: str) -> str:
    if status == "matched":
        return "approve"
    if status == "escalated":
        return "escalate"
    return "review"


def _highest_severity(findings: list[JsonDict]) -> str:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    best = "low"
    for finding in findings:
        severity = str(finding.get("severity") or "low").lower()
        if order.get(severity, 0) > order.get(best, 0):
            best = severity
    return best


def _money_at_risk(findings: list[JsonDict]) -> Decimal:
    total = Decimal("0")
    for finding in findings:
        total += _decimal_or_none(finding.get("overpayment_amount")) or Decimal("0")
    return total


def _average_confidence(validators: list[ValidatorResult]) -> float:
    if not validators:
        return 0.0
    return round(sum(validator.confidence for validator in validators) / len(validators), 2)


def _judgement_summary(target: WorkTarget, findings: list[JsonDict], check: JsonDict) -> str:
    if findings:
        return str(findings[0].get("summary") or f"Invoice {target.invoice_id} has a known exception.")
    return str(check.get("summary") or f"Invoice {target.invoice_id} has no known exception.")


def _basis_summary(findings: list[JsonDict], validators: list[ValidatorResult]) -> str:
    for finding in findings:
        basis = finding.get("basis_summary")
        if basis:
            return str(basis)
    completed = [validator.validator_id for validator in validators if validator.status == "completed"]
    if completed:
        return f"Based on completed validators: {', '.join(completed)}."
    return "Insufficient completed validator evidence for a firm basis."


def _workflow_auth_context(
    request: AssuranceOrchestratorWorkflowRequest,
    expert_client: ExpertValidatorClient | None,
) -> JsonDict:
    execution_path = _expert_execution_path(expert_client)
    configured = {
        validator_id: {
            "source_system": spec.source_system,
            "auth_mode": spec.auth_mode,
            "auth_audience": spec.auth_audience,
            "explicit_tool_name": spec.explicit_tool_name,
            "discovery_enabled": bool(expert_client),
            "configured": bool(expert_client),
            "execution_path": execution_path,
        }
        for validator_id, spec in EXPERT_TOOL_SPECS.items()
    }
    return {
        "read_only": True,
        "caller": request.auth_context,
        "expert_client_configured": bool(expert_client),
        "expert_execution_path": execution_path,
        "toolbox_endpoint_configured": bool(expert_client),
        "toolbox_endpoint_env": _toolbox_endpoint_source(),
        "agent_to_toolbox_scope": TOOLBOX_SCOPE if expert_client else None,
        "validators": configured,
        "production_note": (
            "Use Foundry prompt-agent experts for evidence tool execution when possible. "
            "Keep the selected auth mode explicit in validator traces."
        ),
    }


def _proposed_actions(decision: str, context: JsonDict) -> list[str]:
    allowed_ids = [
        str(action.get("id"))
        for action in _as_dicts(context.get("allowed_actions"))
        if action.get("id")
    ]
    if not allowed_ids:
        if decision == "approve":
            return ["prepare_approval_summary"]
        if decision == "escalate":
            return ["prepare_escalation_packet"]
        return ["prepare_review_packet"]
    if decision == "approve":
        return [action for action in allowed_ids if "approve" in action] or allowed_ids[:2]
    if decision == "escalate":
        return [action for action in allowed_ids if "escalate" in action] or allowed_ids[:2]
    return allowed_ids[:3]


def _select_expert_tool_name(validator_id: str, tools: list[JsonDict]) -> str | None:
    scored = [
        (_expert_tool_score(validator_id, tool), str(tool.get("name") or ""))
        for tool in tools
        if tool.get("name")
    ]
    scored = [(score, name) for score, name in scored if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def _expert_tool_score(validator_id: str, tool: JsonDict) -> int:
    name = str(tool.get("name") or "").lower()
    description = str(tool.get("description") or "").lower()
    tool_type = _toolbox_tool_type(tool)
    haystack = f"{name} {description} {tool_type}".lower()

    if validator_id == "workiq":
        return _score_terms(
            haystack,
            tool_type,
            preferred_types={"work_iq_preview"},
            required_any={"workiq", "work_iq", "work iq", "microsoft 365", "m365", "graph"},
        )
    if validator_id == "fabriciq":
        return _score_terms(
            haystack,
            tool_type,
            preferred_types={"fabric_iq_preview"},
            required_any={"fabriciq", "fabric_iq", "fabric iq", "power bi", "semantic model", "ontology"},
        )
    if validator_id == "foundryiq":
        return _score_terms(
            haystack,
            tool_type,
            preferred_types={"azure_ai_search", "file_search"},
            required_any={"foundryiq", "foundry_iq", "foundry iq", "azure_ai_search", "file_search", "policy", "contract", "knowledge"},
        )
    if validator_id == "webiq":
        return _score_terms(
            haystack,
            tool_type,
            preferred_types={"web_search", "bing_grounding", "bing_grounding_preview"},
            required_any={"webiq", "web_iq", "web iq", "web_search", "web search", "bing", "grounding"},
        )
    return 0


def _score_terms(
    haystack: str,
    tool_type: str,
    *,
    preferred_types: set[str],
    required_any: set[str],
) -> int:
    score = 0
    if tool_type in preferred_types:
        score += 100
    for term in required_any:
        if term in haystack:
            score += 10
    return score


def _toolbox_tool_type(tool: JsonDict) -> str:
    meta = tool.get("_meta")
    if not isinstance(meta, dict):
        return ""
    config = meta.get("tool_configuration")
    if not isinstance(config, dict):
        return ""
    return str(config.get("type") or "").lower()


def _as_dicts(value: Any) -> list[JsonDict]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _float_or_default(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(number, 1.0))


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and not value.startswith("{{") and not value.startswith("${"):
            return value.strip()
    return None


def _float_env(name: str, *, default: float) -> float:
    value = _first_env(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _content_understanding_client() -> ContentUnderstandingClient | None:
    if not ContentUnderstandingConfig.from_env():
        return None
    return ContentUnderstandingClient()


def _content_understanding_url_input(pdf_uri: str | None) -> JsonDict:
    if pdf_uri:
        return {"url": pdf_uri}
    raise ValueError("pdf_uri is required for URL Content Understanding analysis.")


def _normalized_content_understanding_base64(pdf_base64: str) -> str:
    normalized = _normalize_base64_input(pdf_base64)
    if normalized is None:
        raise ValueError("pdf_base64 was provided but was empty.")
    return normalized


def _normalize_base64_input(value: Any) -> str | None:
    text = _as_optional_str(value)
    if not text:
        return None
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("pdf_base64 must be valid base64 PDF bytes.") from exc
    return text


def _content_understanding_summary(result: JsonDict) -> str:
    status = str(result.get("status") or "succeeded")
    fields = _content_understanding_fields(result)
    field_names = sorted(fields)[:8]
    if field_names:
        return (
            f"Content Understanding {status}; extracted fields: "
            f"{', '.join(field_names)}."
        )
    error_message = _content_understanding_result_error(result)
    if error_message:
        return f"Content Understanding {status}; {error_message}"
    return f"Content Understanding {status}; no structured fields were found in the result."


def _content_understanding_summary_payload(result: JsonDict) -> JsonDict:
    fields = _content_understanding_fields(result)
    return {
        "status": result.get("status"),
        "analyzer_id": result.get("analyzerId") or result.get("analyzer_id"),
        "error": _to_json_safe(result.get("error")) if isinstance(result.get("error"), dict) else None,
        "fields": fields,
    }


def _content_understanding_result_error(result: JsonDict) -> str | None:
    error = result.get("error")
    if not isinstance(error, dict):
        return None
    return _content_understanding_error_message(json.dumps(error))


def _content_understanding_error_message(raw_error: str) -> str:
    try:
        payload = json.loads(raw_error)
    except json.JSONDecodeError:
        return raw_error[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return raw_error[:500]
    messages: list[str] = []
    current: Any = error
    while isinstance(current, dict):
        code = current.get("code")
        message = current.get("message")
        if code or message:
            messages.append(
                ": ".join(str(part) for part in (code, message) if part)
            )
        current = current.get("innererror")
    return " | ".join(messages)[:500] if messages else raw_error[:500]


def _content_understanding_fields(result: JsonDict) -> JsonDict:
    result_payload = result.get("result") if isinstance(result.get("result"), dict) else result
    contents = _as_dicts(result_payload.get("contents"))
    fields: JsonDict = {}
    for content in contents:
        candidate = content.get("fields")
        if isinstance(candidate, dict):
            fields.update(candidate)
    if isinstance(result_payload.get("fields"), dict):
        fields.update(result_payload["fields"])
    return _to_json_safe(fields)


def _toolbox_endpoint() -> str | None:
    return _first_env("TOOLBOX_ENDPOINT", "TOOLBOX_MCP_ENDPOINT")


def _toolbox_endpoint_source() -> str | None:
    for name in ("TOOLBOX_ENDPOINT", "TOOLBOX_MCP_ENDPOINT"):
        if _first_env(name):
            return name
    return None


def _json_safe_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if hasattr(value, "dict"):
        return value.dict()
    return _to_json_safe(value)


def _atomic_write_json(path: Path, payload: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _safe_journal_label(label: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in label.lower())
    return safe.strip("-") or "event"


def _redact_journal_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: JsonDict = {}
        for key, item in value.items():
            key_text = str(key)
            if _should_redact_journal_key(key_text):
                redacted[key_text] = _redacted_value(key_text, item)
            else:
                redacted[key_text] = _redact_journal_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_journal_payload(item) for item in value]
    return value


def _should_redact_journal_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {"pdf_base64", "content"} or normalized.endswith("_base64")


def _redacted_value(key: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    return f"<redacted:{key}>"


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    return value
