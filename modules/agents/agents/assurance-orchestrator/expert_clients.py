"""Fan-out clients for the Assurance Orchestrator coordinator.

Assurance Orchestrator is the workflow agent for the invoice-assurance pipeline. It does not
gather evidence or write to Waypoint itself. Instead it fans out to
single-purpose experts, collects their structured evidence, then hands the fused
bundle to the waypoint-recorder agent, which runs the final policy check and performs
the governed Waypoint write.

Each downstream agent is reached over its OpenAI-Responses-compatible endpoint.
Endpoints are supplied per-agent via environment variables and resolved at deploy
time. When an endpoint is not configured (e.g. local dev before the pipeline is
wired), the corresponding tool degrades to a clear "not configured" response so
Assurance Orchestrator still runs as a read-only scout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
from agent_framework import FunctionTool, tool
from azure.identity import DefaultAzureCredential
from opentelemetry import trace

from telemetry import rft_reference_attributes, set_span_attribute, trace_span

logger = logging.getLogger("assurance_orchestrator.expert_clients")

DEFAULT_AGENT_SCOPE = "https://ai.azure.com/.default"
DEFAULT_PROMPT_EXPERT_AGENT_NAMES = {
    "workiq": "collaboration-evidence-expert",
    "webiq": "market-evidence-expert",
    "foundryiq": "contract-policy-expert",
    "fabriciq": "operations-data-expert",
}
REPO_ROOT = next(
    (parent for parent in Path(__file__).resolve().parents if (parent / "agents").is_dir()),
    Path(__file__).resolve().parent,
)
PROMPT_EXPERT_MODE_ENV = "ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE"
PROMPT_EXPERT_PROJECT_ENDPOINT_ENV = "ASSURANCE_ORCHESTRATOR_EXPERT_PROJECT_ENDPOINT"
PROMPT_EXPERT_MODEL_ENV = "ASSURANCE_ORCHESTRATOR_EXPERT_MODEL"
PROMPT_EXPERT_SCOPE_ENV = "ASSURANCE_ORCHESTRATOR_EXPERT_SCOPE"
PROMPT_EXPERT_AGENT_ENV = {
    "workiq": "COLLABORATION_EVIDENCE_EXPERT_AGENT_NAME",
    "webiq": "MARKET_EVIDENCE_EXPERT_AGENT_NAME",
    "foundryiq": "CONTRACT_POLICY_EXPERT_AGENT_NAME",
    "fabriciq": "OPERATIONS_DATA_EXPERT_AGENT_NAME",
}
PROMPT_EXPERT_PATHS = {
    "workiq": REPO_ROOT / "agents" / "collaboration-evidence-expert" / "prompt.md",
    "webiq": REPO_ROOT / "agents" / "market-evidence-expert" / "prompt.md",
    "foundryiq": REPO_ROOT / "agents" / "contract-policy-expert" / "prompt.md",
    "fabriciq": REPO_ROOT / "agents" / "operations-data-expert" / "prompt.md",
}

# Foundry hosted-agent Responses bridge. A deployed hosted agent is addressed as
# <project_endpoint>/agents/<name>; its OpenAI-Responses surface is reached at the
# endpoint-scoped bridge below, which REQUIRES the api-version query parameter and
# the Foundry-Features preview header. Local dev (the ResponsesHostServer bound to
# http://localhost:<port>) instead serves the bare "/responses" path with no
# api-version and no preview header, so the two cases are handled separately.
FOUNDRY_RESPONSES_API_VERSION = "2025-11-15-preview"
FOUNDRY_RESPONSES_SUFFIX = "/endpoint/protocols/openai/responses"
FOUNDRY_FEATURES_HEADER = "HostedAgents=V1Preview,AgentEndpoints=V1Preview"

# name -> environment variable that carries that agent's Responses endpoint.
EXPERT_ENDPOINT_ENV = {
    "workiq": "WORKIQ_EXPERT_ENDPOINT",
    "webiq": "WEBIQ_EXPERT_ENDPOINT",
    "foundryiq": "FOUNDRYIQ_EXPERT_ENDPOINT",
    "fabriciq": "FABRICIQ_EXPERT_ENDPOINT",
}
EXPERT_ENABLED_ENV = {
    "workiq": "ASSURANCE_ORCHESTRATOR_WORKIQ_ENABLED",
    "webiq": "ASSURANCE_ORCHESTRATOR_WEBIQ_ENABLED",
    "foundryiq": "ASSURANCE_ORCHESTRATOR_FOUNDRYIQ_ENABLED",
    "fabriciq": "ASSURANCE_ORCHESTRATOR_FABRICIQ_ENABLED",
}
EXPERT_ENABLED_DEFAULTS = {
    "workiq": False,
    "webiq": False,
    "foundryiq": True,
    "fabriciq": False,
}
WAYPOINT_RECORDER_ENDPOINT_ENV = "WAYPOINT_RECORDER_ENDPOINT"

# Each downstream call (an expert evidence gather, or the waypoint-recorder handoff) is a
# synchronous Responses round-trip. Experts that do web-search bursts can take
# 30-60s apiece and the waypoint-recorder handoff fuses + persists, so the per-call HTTP
# timeout must be generous. Assurance Orchestrator itself is meant to be driven in *background*
# mode (no ~120s sync server cap), so this only bounds the individual fan-out legs.
DEFAULT_EXPERT_RESPONSES_TIMEOUT = 150.0
EXPERT_RESPONSES_TIMEOUT_ENV = "EXPERT_RESPONSES_TIMEOUT"


def _expert_timeout() -> float:
    raw = _usable_env(EXPERT_RESPONSES_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_EXPERT_RESPONSES_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; falling back to %.0fs",
            EXPERT_RESPONSES_TIMEOUT_ENV,
            raw,
            DEFAULT_EXPERT_RESPONSES_TIMEOUT,
        )
        return DEFAULT_EXPERT_RESPONSES_TIMEOUT
    return value if value > 0 else DEFAULT_EXPERT_RESPONSES_TIMEOUT


# Graceful degradation: a single transient downstream blip (a gpt-5.5 rate-limit
# 429, a cold-start 503, a gateway 502) should NOT permanently fail an expert lane
# or the recorder handoff. Bounded retry-with-backoff lets a lane self-heal; if it
# still fails the caller degrades it to an `ok:false` tool result (see _consult_expert)
# instead of aborting the whole assurance run.
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
DEFAULT_EXPERT_MAX_ATTEMPTS = 3
EXPERT_MAX_ATTEMPTS_ENV = "EXPERT_RESPONSES_MAX_ATTEMPTS"
EXPERT_RETRY_BASE_BACKOFF_SECONDS = 1.5
EXPERT_RETRY_MAX_BACKOFF_SECONDS = 20.0


def _expert_max_attempts() -> int:
    raw = _usable_env(EXPERT_MAX_ATTEMPTS_ENV)
    if raw is None:
        return DEFAULT_EXPERT_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; falling back to %d",
            EXPERT_MAX_ATTEMPTS_ENV,
            raw,
            DEFAULT_EXPERT_MAX_ATTEMPTS,
        )
        return DEFAULT_EXPERT_MAX_ATTEMPTS
    return value if value >= 1 else DEFAULT_EXPERT_MAX_ATTEMPTS


def _retry_after_seconds(response: "httpx.Response", attempt: int) -> float:
    """Honor a server Retry-After header when present, else exponential backoff."""
    header = response.headers.get("Retry-After") if response is not None else None
    if header:
        try:
            return max(0.0, min(float(header), EXPERT_RETRY_MAX_BACKOFF_SECONDS))
        except ValueError:
            pass
    return min(
        EXPERT_RETRY_BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
        EXPERT_RETRY_MAX_BACKOFF_SECONDS,
    )


def _post_responses_with_retry(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    *,
    label: str,
    span: Any = None,
    max_attempts: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> "httpx.Response":
    """POST to a Responses endpoint with bounded retry on transient failures.

    Returns the final httpx.Response (success, or the last error response after the
    retry budget is exhausted / a non-transient error). The caller is responsible
    for raising on `response.is_error` so a still-failing lane degrades cleanly.
    """
    attempts = max_attempts if max_attempts is not None else _expert_max_attempts()
    response: "httpx.Response | None" = None
    for attempt in range(1, attempts + 1):
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
        if not response.is_error:
            return response
        if response.status_code not in TRANSIENT_STATUS_CODES or attempt >= attempts:
            return response
        delay = _retry_after_seconds(response, attempt)
        logger.warning(
            "%s transient HTTP %s (attempt %d/%d); retrying in %.1fs",
            label,
            response.status_code,
            attempt,
            attempts,
            delay,
        )
        if span is not None:
            set_span_attribute(span, "forge.downstream.retry.attempts", attempt)
            set_span_attribute(span, "forge.downstream.retry.last_status", response.status_code)
        sleep(delay)
    return response  # type: ignore[return-value]


_PLANE_BRIEF = {
    "workiq": "workplace evidence (mail, meetings, documents) from Microsoft 365 / Work IQ",
    "webiq": "external/web evidence and public corroboration",
    "foundryiq": "grounded knowledge retrieved from the Foundry knowledge index",
    "fabriciq": "structured operational data (POs, receipts, batch, capacity) from Microsoft Fabric",
}


@dataclass(frozen=True)
class _AgentEndpoint:
    name: str
    url: str
    scope: str


@dataclass(frozen=True)
class _PromptExpertSpec:
    validator_id: str
    agent_name: str
    model: str


def _resolve_endpoint(name: str, env_var: str) -> _AgentEndpoint | None:
    if name in EXPERT_ENABLED_ENV and not is_expert_enabled(name):
        return None
    url = _usable_env(env_var)
    if not url:
        return None
    scope = _usable_env("EXPERT_AGENT_SCOPE") or DEFAULT_AGENT_SCOPE
    return _AgentEndpoint(name=name, url=url.rstrip("/"), scope=scope)


def is_expert_enabled(name: str) -> bool:
    env_var = EXPERT_ENABLED_ENV.get(name)
    if env_var is None:
        return True
    raw = _usable_env(env_var)
    if raw is None:
        return EXPERT_ENABLED_DEFAULTS.get(name, True)
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


class _ResponsesAgentClient:
    """Minimal OpenAI-Responses client for one downstream pipeline agent."""

    def __init__(self, endpoint: _AgentEndpoint, timeout: float | None = None) -> None:
        self._endpoint = endpoint
        self._timeout = _expert_timeout() if timeout is None else timeout
        self._credential: DefaultAzureCredential | None = None

    def run(self, prompt: str) -> str:
        with trace_span(
            f"assurance_orchestrator.responses_agent {self._endpoint.name}",
            {
                **rft_reference_attributes(
                    agent_name="assurance-orchestrator",
                    task_family="invoice_assurance_fanout",
                    messages=[{"role": "user", "content": prompt}],
                    expected_tools=[f"{self._endpoint.name}.responses"],
                    grader_reference={"expected_status": "completed"},
                ),
                "gen_ai.agent.name": "assurance-orchestrator",
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.tool.name": f"{self._endpoint.name}.responses",
                "forge.downstream.agent": self._endpoint.name,
                "forge.downstream.endpoint.kind": "foundry" if self._is_foundry_endpoint() else "local",
            },
        ) as span:
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            token = self._token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if self._is_foundry_endpoint():
                # The Foundry hosted-agent Responses bridge gates on this preview header.
                headers["Foundry-Features"] = FOUNDRY_FEATURES_HEADER
            payload = {"input": prompt, "store": False}
            response = _post_responses_with_retry(
                self._responses_url(),
                headers,
                payload,
                self._timeout,
                label=self._endpoint.name,
                span=span,
            )
            set_span_attribute(span, "http.response.status_code", response.status_code)
            if response.is_error:
                raise RuntimeError(
                    f"{self._endpoint.name} agent call failed with HTTP "
                    f"{response.status_code}: {response.text[:300]}"
                )
            body = response.json()
            set_span_attribute(span, "gen_ai.response.id", body.get("id") if isinstance(body, dict) else None)
            output = _extract_output_text(body)
            set_span_attribute(span, "forge.downstream.output.characters", len(output))
            return output

    def _token(self) -> str | None:
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        return self._credential.get_token(self._endpoint.scope).token

    def _is_foundry_endpoint(self) -> bool:
        # Cloud hosted-agent endpoints are self-computed by forge deploy as
        # "<project_endpoint>/agents/<name>"; local dev endpoints are bare
        # "http://localhost:<port>" with no "/agents/" path segment.
        return "/agents/" in self._endpoint.url

    def _responses_url(self) -> str:
        url = self._endpoint.url
        base, _, query = url.partition("?")
        base = base.rstrip("/")
        if not self._is_foundry_endpoint():
            # Local dev: the ResponsesHostServer serves the bare "/responses" path
            # with no api-version and no preview header.
            if not base.endswith("/responses"):
                base = f"{base}/responses"
            return f"{base}?{query}" if query else base
        # Foundry hosted-agent bridge. FOUNDRY_RESPONSES_SUFFIX already ends in
        # "/responses", so a base ending in "/responses" is treated as complete.
        if not base.endswith("/responses"):
            base = f"{base}{FOUNDRY_RESPONSES_SUFFIX}"
        if "api-version=" in query:
            return f"{base}?{query}"
        return f"{base}?api-version={FOUNDRY_RESPONSES_API_VERSION}"


class FoundryPromptExpertClient:
    """Workflow-owned adapter over Foundry prompt-agent experts.

    AssuranceOrchestrator passes the validation request to an expert prompt agent. Foundry owns
    that expert's tool calls, tool-output loop, and auth; AssuranceOrchestrator only normalizes
    the expert's final evidence contract.
    """

    execution_path = "foundry_prompt_agent"

    def __init__(
        self,
        project_endpoint: str,
        *,
        model: str | None = None,
        credential: DefaultAzureCredential | None = None,
        timeout: float | None = None,
    ) -> None:
        self._project_endpoint = project_endpoint.rstrip("/")
        self._model = model
        self._credential = credential or DefaultAzureCredential()
        self._timeout = _expert_timeout() if timeout is None else timeout
        self._specs: dict[str, _PromptExpertSpec] | None = None

    @classmethod
    def from_env(cls) -> "FoundryPromptExpertClient | None":
        if not _prompt_experts_enabled():
            return None
        project_endpoint = _prompt_expert_project_endpoint()
        if not project_endpoint or not _looks_like_http_url(project_endpoint):
            message = (
                "Prompt expert mode requires a valid Foundry project endpoint "
                f"from {PROMPT_EXPERT_PROJECT_ENDPOINT_ENV}, AZURE_AI_PROJECT_ENDPOINT, "
                "AZURE_AIPROJECT_ENDPOINT, or FOUNDRY_PROJECT_ENDPOINT."
            )
            if _prompt_expert_mode_requested():
                raise RuntimeError(message)
            logger.warning(message)
            return None
        return cls(project_endpoint, model=_usable_env(PROMPT_EXPERT_MODEL_ENV))

    async def resolve_tool_name(self, validator_id: str) -> str | None:
        if not is_expert_enabled(validator_id):
            return None
        spec = self._resolve_spec(validator_id)
        return f"{spec.agent_name}.agent_reference" if spec else None

    async def call_validator(self, validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not is_expert_enabled(validator_id):
            raise RuntimeError(f"{validator_id}-expert is disabled by configuration.")
        spec = self._resolve_spec(validator_id)
        if spec is None:
            raise ValueError(f"No prompt expert is registered for validator '{validator_id}'.")
        prompt = _workflow_expert_prompt(validator_id, arguments)
        output = await asyncio.to_thread(self._invoke_prompt_expert, spec, prompt)
        return {"structuredContent": _normalize_expert_contract(validator_id, output, self.execution_path)}

    def _invoke_prompt_expert(self, spec: _PromptExpertSpec, prompt: str) -> str:
        with trace_span(
            f"assurance_orchestrator.prompt_expert {spec.validator_id}",
            {
                **rft_reference_attributes(
                    agent_name="assurance-orchestrator",
                    task_family="invoice_assurance_fanout",
                    messages=[{"role": "user", "content": prompt}],
                    expected_tools=[f"{spec.agent_name}.agent_reference"],
                    grader_reference={"expected_status": "completed"},
                ),
                "gen_ai.agent.name": "assurance-orchestrator",
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.tool.name": f"{spec.agent_name}.agent_reference",
                "forge.downstream.agent": spec.agent_name,
                "forge.downstream.endpoint.kind": "foundry_prompt_agent",
            },
        ) as span:
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._credential.get_token(_prompt_expert_scope()).token}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self._model or spec.model,
                "input": prompt,
                "store": False,
                "agent_reference": {
                    "name": spec.agent_name,
                    "type": "agent_reference",
                },
            }
            response = _post_responses_with_retry(
                self._responses_url(),
                headers,
                payload,
                self._timeout,
                label=spec.agent_name,
                span=span,
            )
            set_span_attribute(span, "http.response.status_code", response.status_code)
            if response.is_error:
                raise RuntimeError(
                    f"{spec.agent_name} prompt expert call failed with HTTP "
                    f"{response.status_code}: {response.text[:300]}"
                )
            body = response.json()
            set_span_attribute(span, "gen_ai.response.id", body.get("id") if isinstance(body, dict) else None)
            output = _extract_output_text(body)
            set_span_attribute(span, "forge.downstream.output.characters", len(output))
            return output

    def _responses_url(self) -> str:
        base = self._project_endpoint
        if base.endswith("/openai/v1"):
            return f"{base}/responses"
        if base.endswith("/openai/v1/responses"):
            return base
        return f"{base}/openai/v1/responses"

    def _resolve_spec(self, validator_id: str) -> _PromptExpertSpec | None:
        if self._specs is None:
            self._specs = _load_prompt_expert_specs()
        return self._specs.get(validator_id)


# ── run lifecycle (Design B2 early-open) ──────────────────────────────────────
# The orchestrator never writes to Waypoint itself. To make the multi-minute expert
# fan-out visible on Waypoint's Activity page, it asks the waypoint-recorder — over the
# SAME Responses endpoint used for the final handoff — to open the run early
# (running/pending). The recorder's final `waypoint_record_assurance` reuses the same
# operation_id-derived idempotency keys, so the early-open and the final write resolve to
# ONE run + case (no duplicates). If the recorder endpoint isn't wired (local scout mode)
# or the early-open call fails, the final write still opens+completes the run — the
# lifecycle just won't show the in-flight window for that invoice.
#
# Idempotency key formats are replicated from
# waypoint_recorder.waypoint_write_client (separate Python package) and MUST stay in sync:
#   run key:  assurance:{invoice_ref}:{operation_id}
#   case key: assurance-case:{invoice_ref}:{operation_id}

_OPERATION_IDS: dict[str, str] = {}   # invoice_ref -> stable per-execution operation id
_RUNNING_OPENED: set[str] = set()     # invoice_refs whose run was already flipped to running


def _current_operation_id() -> str:
    """Derive a stable per-execution operation id for idempotency/correlation.

    Prefers the current OpenTelemetry trace id (App Insights operation id, shared across
    this orchestrator turn's fan-out), then APP_INSIGHTS_OPERATION_ID, then a uuid.
    """
    span = trace.get_current_span()
    context = span.get_span_context() if span is not None else None
    if context is not None and getattr(context, "is_valid", False) and context.trace_id:
        return format(context.trace_id, "032x")
    env_value = _usable_env("APP_INSIGHTS_OPERATION_ID")
    if env_value:
        return env_value
    return uuid.uuid4().hex


def _operation_id_for(invoice_ref: str) -> str:
    """Return (and cache) the stable operation id for an invoice so the early-open, the
    running-flip, and the final handoff all derive identical idempotency keys."""
    invoice_ref = (invoice_ref or "").strip()
    existing = _OPERATION_IDS.get(invoice_ref)
    if existing:
        return existing
    op = _current_operation_id()
    _OPERATION_IDS[invoice_ref] = op
    return op


def _ask_recorder_open(instruction: str, span_name: str, attributes: dict[str, Any]) -> str | None:
    """Fire a single-purpose Responses call to the waypoint-recorder (best-effort)."""
    endpoint = _resolve_endpoint("waypoint-recorder", WAYPOINT_RECORDER_ENDPOINT_ENV)
    if endpoint is None:
        return None
    with trace_span(span_name, attributes) as span:
        try:
            output = _ResponsesAgentClient(endpoint).run(instruction)
            set_span_attribute(span, "forge.waypoint_recorder.open.status", "completed")
            return output
        except Exception:
            logger.warning("recorder open-run call failed: %s", span_name, exc_info=True)
            set_span_attribute(span, "forge.waypoint_recorder.open.status", "failed")
            return None


def _ensure_run_open(invoice_id: str) -> None:
    """Open the run as `running` on first fan-out touch of an invoice (once per invoice).

    Guarded by ``_RUNNING_OPENED`` so only the first expert consult fires it. Safe to call
    for an invoice already enrolled as `pending`: the recorder advances it to `running`.
    """
    invoice_ref = (invoice_id or "").strip()
    if not invoice_ref or invoice_ref in _RUNNING_OPENED:
        return
    if not _usable_env(WAYPOINT_RECORDER_ENDPOINT_ENV):
        return
    _RUNNING_OPENED.add(invoice_ref)  # guard before the call so a failure can't retry-storm
    op = _operation_id_for(invoice_ref)
    instruction = (
        "Open the Waypoint assurance run for this invoice at the START of processing.\n"
        "Call waypoint_open_run EXACTLY ONCE with these arguments, then STOP; do NOT call "
        "waypoint_record_assurance or any other tool.\n"
        f'invoice_id: "{invoice_ref}"\n'
        f'operation_id: "{op}"\n'
        'status: "running"'
    )
    _ask_recorder_open(
        instruction,
        "assurance-orchestrator.open_run",
        {
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.tool.name": "waypoint_open_run",
            "forge.invoice.id": invoice_ref,
            "forge.waypoint.status": "running",
        },
    )


def resolve_run_identity(invoice_id: str) -> str:
    """F2 SEAM — resolve the stable operation id that keys this invoice's Waypoint run.

    The whole lifecycle (early-open, handoff, finalize-failed) derives its run/case
    idempotency keys from this value AND passes it to the recorder as the
    ``app_insights_operation_id`` correlation id stamped on the run anchor.

    W2 RESOLUTION (received, REUSE semantics): run convergence is now **server-side by
    run name**. The recorder always opens with the stable ``name = "assurance:{invoice_id}"``
    (see ``waypoint_write_client.open_assurance_run``), and Waypoint's ``POST /api/runs``
    resolves in order: (1) exact ``idempotency_key`` reuse, (2) reuse an existing ACTIVE
    run (running/pending) with the same name, (3) else create. So two SEPARATE orchestrator
    turns for the same invoice — the real prod double-trigger — converge onto ONE active run
    WITHOUT this seam needing to change its keying: we keep returning the per-execution op id
    (still the idempotency_key + the app_insights correlation id), and the server dedupes by
    name. No client-side "query for the active run" round-trip is required.

    What F2 actually fixes is downstream of here: the recorder now threads this op id onto
    the run as ``app_insights_operation_id`` at early-open (previously sourced from an unset
    env → the prod null op-id), which is what Waypoint W3 backfills from.

    Residual (flagged to Waypoint): W2 covers ``/api/runs`` only. The CASE key stays
    per-trace (``assurance-case:{invoice}:{op}``), so sequential turns may still mint two
    case anchors even though the RUN is single. Not owned by this seam.
    """
    return _operation_id_for(invoice_id)


def open_run_for_invoice(invoice_id: str) -> None:
    """Deterministically open an invoice's run as `running` (code-owned early-open).

    The run harness calls this at the START of a run so the invoice shows a `running`
    window on Waypoint's Activity page AND so there is always a run to finalize (complete
    or fail). Idempotent and best-effort: guarded by ``_RUNNING_OPENED`` and a no-op when
    the recorder endpoint is unconfigured.
    """
    _ensure_run_open(invoice_id)


def finalize_run_failed(invoice_id: str, reason: str) -> str | None:
    """Deterministically mark an invoice's run `failed` so it never orphans at `running`.

    Code-owned finalize-failure path: instructs the waypoint-recorder (over its Responses
    endpoint) to call ``waypoint_fail_run`` for the SAME run the early-open opened (shared
    operation id). Best-effort — returns None when the recorder endpoint is unconfigured or
    the call fails; the harness's durable outbox handles retry of the terminal write.
    """
    invoice_ref = (invoice_id or "").strip()
    if not invoice_ref:
        return None
    if not _usable_env(WAYPOINT_RECORDER_ENDPOINT_ENV):
        return None
    op = resolve_run_identity(invoice_ref)
    safe_reason = reason.replace('"', "'").replace("\n", " ")[:400] if reason else "assurance run failed"
    instruction = (
        "The assurance run for this invoice could not be completed and MUST be marked "
        "failed so it does not orphan at 'running'.\n"
        "Call waypoint_fail_run EXACTLY ONCE with these arguments, then STOP; do NOT call "
        "waypoint_record_assurance, waypoint_open_run, or any other tool.\n"
        f'invoice_id: "{invoice_ref}"\n'
        f'operation_id: "{op}"\n'
        f'reason: "{safe_reason}"'
    )
    return _ask_recorder_open(
        instruction,
        "assurance-orchestrator.finalize_failed",
        {
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.tool.name": "waypoint_fail_run",
            "forge.invoice.id": invoice_ref,
            "forge.waypoint.status": "failed",
        },
    )


def enroll_assurance_batch(invoice_ids_json: str) -> str:
    """Pre-open every invoice in a multi-invoice run as `pending` on Waypoint's Activity
    page, BEFORE fan-out begins. Call this ONCE at the very start whenever you will process
    more than one invoice. Each invoice then flips to `running` when you consult experts for
    it, and to `completed`/`failed` when the waypoint-recorder records its result.

    Args:
        invoice_ids_json: A JSON array of the invoice ids to enroll, e.g.
            ["INV-2026-08034", "INV-2026-08120"].
    """
    if not _usable_env(WAYPOINT_RECORDER_ENDPOINT_ENV):
        return json.dumps(
            {
                "ok": False,
                "error": f"waypoint-recorder endpoint is not configured ({WAYPOINT_RECORDER_ENDPOINT_ENV}).",
            }
        )
    try:
        parsed = json.loads(invoice_ids_json)
    except (TypeError, json.JSONDecodeError) as exc:
        return json.dumps({"ok": False, "error": f"invalid invoice_ids_json: {exc}"})
    if isinstance(parsed, dict):
        parsed = parsed.get("invoice_ids") or parsed.get("invoices") or []
    if not isinstance(parsed, list) or not parsed:
        return json.dumps({"ok": False, "error": "invoice_ids_json must be a non-empty JSON array of invoice ids."})

    invoices: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in parsed:
        if isinstance(entry, str):
            ref = entry.strip()
        elif isinstance(entry, dict):
            ref = str(entry.get("invoice_id") or entry.get("invoice_number") or "").strip()
        else:
            ref = ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        invoices.append({"invoice_id": ref, "operation_id": _operation_id_for(ref)})
    if not invoices:
        return json.dumps({"ok": False, "error": "no valid invoice ids found in invoice_ids_json."})

    instruction = (
        "Enroll this batch of invoices as pending on Waypoint before fan-out.\n"
        "Call waypoint_enroll_batch EXACTLY ONCE with the invoices_json below, then STOP; "
        "do NOT call any other tool.\n"
        f"invoices_json: {json.dumps(invoices, ensure_ascii=False)}"
    )
    output = _ask_recorder_open(
        instruction,
        "assurance-orchestrator.enroll_assurance_batch",
        {
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.tool.name": "waypoint_enroll_batch",
            "forge.batch.size": len(invoices),
        },
    )
    if output is None:
        return json.dumps({"ok": False, "error": "waypoint-recorder enroll call failed or endpoint unavailable."})
    return json.dumps({"ok": True, "enrolled": len(invoices), "waypoint_recorder_result": output}, ensure_ascii=False)


_MARKET_CONTEXT_CACHE: dict[str, str] = {}


def _supplier_name(invoice: dict[str, Any]) -> str | None:
    supplier = invoice.get("supplier")
    if isinstance(supplier, dict):
        name = supplier.get("name")
        if name:
            return str(name)
    if isinstance(supplier, str) and supplier.strip():
        return supplier.strip()
    name = invoice.get("supplier_name")
    return str(name) if name else None


def _format_market_context(context: object) -> str:
    """Render the market-relevant slice of a Waypoint invoice context as a prompt block."""
    if not isinstance(context, dict):
        return ""
    invoice = context.get("invoice") if isinstance(context.get("invoice"), dict) else {}
    findings = _as_dicts(invoice.get("findings")) or _as_dicts(context.get("findings"))
    lines = _as_dicts(invoice.get("lines"))
    supplier = _supplier_name(invoice)
    categories = _unique(f.get("category") for f in findings if f.get("category"))
    finding_summaries = _unique(f.get("summary") for f in findings if f.get("summary"))
    line_descs = _unique(item.get("description") for item in lines if item.get("description"))
    total = invoice.get("total_amount")
    currency = invoice.get("currency")

    parts: list[str] = []
    if supplier:
        parts.append(f"Supplier: {supplier}")
    if categories:
        parts.append("Spend category: " + "; ".join(categories))
    if line_descs:
        parts.append("Line items: " + "; ".join(line_descs[:6]))
    if total:
        parts.append(f"Invoice total: {total} {currency or ''}".strip())
    if finding_summaries:
        parts.append("Dispute context: " + "; ".join(finding_summaries[:3]))
    return "\n".join(parts)


def _market_context_block(invoice_id: str) -> str:
    """Best-effort supplier/market context for the market-evidence (webiq) lane.

    The market-evidence-expert is bound to a single web-search tool and cannot look up the
    invoice itself, so it can only ground real market/rate/supplier-financial queries if we
    hand it the invoice's semantic context (supplier, category, line items, amount). Pull
    that from Waypoint here and degrade to "" on any failure so the lane never hard-fails.
    """
    ref = (invoice_id or "").strip()
    if not ref:
        return ""
    if ref in _MARKET_CONTEXT_CACHE:
        return _MARKET_CONTEXT_CACHE[ref]
    block = ""
    try:
        from waypoint_client import WaypointConfig, WaypointReadOnlyClient

        config = WaypointConfig.try_from_env()
        if config is not None:
            context = WaypointReadOnlyClient(config).get_invoice_context(ref)
            block = _format_market_context(context)
    except Exception:
        logger.debug("market context fetch failed for %s", ref, exc_info=True)
        block = ""
    _MARKET_CONTEXT_CACHE[ref] = block
    return block


def _consult_expert(name: str, invoice_id: str, question: str) -> str:
    _ensure_run_open(invoice_id)
    endpoint = _resolve_endpoint(name, EXPERT_ENDPOINT_ENV[name])
    if endpoint is None:
        return json.dumps(
            {
                "ok": False,
                "expert": name,
                "error": f"{name}-expert endpoint is not configured ({EXPERT_ENDPOINT_ENV[name]}).",
            }
        )
    brief = _PLANE_BRIEF[name]
    prompt_lines = [
        f"Invoice id: {invoice_id.strip() or 'unspecified'}.",
        f"Gather {brief} relevant to this invoice's assurance review.",
        f"Coordinator question: {question.strip() or 'Provide all relevant evidence.'}",
    ]
    # The market-evidence (webiq) lane grounds on the PUBLIC web, which knows nothing about
    # internal invoice ids. Steer it away from searching the id and hand it the supplier /
    # market context so it can build real market/rate/supplier-financial queries instead.
    if name == "webiq":
        prompt_lines.append(
            "Do NOT search the web for the invoice id or invoice number — it has no public "
            "presence. Build market / rate / supplier-financial queries from the supplier "
            "name, spend category, line items, and amounts in the market context below."
        )
        market_context = _market_context_block(invoice_id)
        if market_context:
            prompt_lines.append("Market context:\n" + market_context)
    prompt_lines.append(
        "Return repairable expert_evidence JSON with source refs, confidence, "
        "and unsupported/unknown items."
    )
    prompt = "\n".join(prompt_lines)
    with trace_span(
        f"assurance_orchestrator.consult_expert {name}",
        {
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": f"consult_{name}_expert",
            "forge.expert.name": f"{name}-expert",
            "forge.invoice.id": invoice_id.strip() or None,
            "forge.rft.agent": "assurance-orchestrator",
            "forge.rft.task_family": "invoice_assurance_expert_fanout",
            "forge.rft.expected_tools": [f"{name}-expert.responses"],
        },
    ) as span:
        try:
            output = _ResponsesAgentClient(endpoint).run(prompt)
        except Exception as exc:
            logger.exception("consult %s-expert failed", name)
            set_span_attribute(span, "forge.expert.status", "failed")
            return json.dumps({"ok": False, "expert": name, "error": str(exc)})
        set_span_attribute(span, "forge.expert.status", "completed")
        set_span_attribute(span, "forge.expert.output.characters", len(output))
        return json.dumps({"ok": True, "expert": name, "evidence": output}, ensure_ascii=False)


class HostedResponsesExpertClient:
    """Workflow-owned adapter over the hosted expert Responses endpoints."""

    execution_path = "responses_agent"

    def __init__(self, timeout: float | None = None) -> None:
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "HostedResponsesExpertClient | None":
        if any(_resolve_endpoint(name, env_var) for name, env_var in EXPERT_ENDPOINT_ENV.items()):
            return cls()
        return None

    async def resolve_tool_name(self, validator_id: str) -> str | None:
        if validator_id not in EXPERT_ENDPOINT_ENV:
            return None
        endpoint = _resolve_endpoint(validator_id, EXPERT_ENDPOINT_ENV[validator_id])
        if endpoint is None:
            return None
        return f"{validator_id}-expert.responses"

    async def call_validator(self, validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if validator_id not in EXPERT_ENDPOINT_ENV:
            raise ValueError(f"No hosted Responses expert is registered for validator '{validator_id}'.")
        endpoint = _resolve_endpoint(validator_id, EXPERT_ENDPOINT_ENV[validator_id])
        if endpoint is None:
            raise RuntimeError(
                f"{validator_id}-expert endpoint is not configured ({EXPERT_ENDPOINT_ENV[validator_id]})."
            )

        output = await asyncio.to_thread(
            _ResponsesAgentClient(endpoint, timeout=self._timeout).run,
            _workflow_expert_prompt(validator_id, arguments),
        )
        return {"structuredContent": _normalize_expert_contract(validator_id, output, self.execution_path)}


def consult_collaboration_evidence_expert(invoice_id: str = "", question: str = "") -> str:
    """Fan out to the collaboration-evidence-expert for Microsoft 365 / Work IQ workplace evidence."""
    return _consult_expert("workiq", invoice_id, question)


def consult_market_evidence_expert(invoice_id: str = "", question: str = "") -> str:
    """Fan out to the market-evidence-expert for external/web evidence and corroboration."""
    return _consult_expert("webiq", invoice_id, question)


def consult_contract_policy_expert(invoice_id: str = "", question: str = "") -> str:
    """Fan out to the contract-policy-expert for grounded Foundry knowledge retrieval."""
    return _consult_expert("foundryiq", invoice_id, question)


def consult_operations_data_expert(invoice_id: str = "", question: str = "") -> str:
    """Fan out to the operations-data-expert for structured Microsoft Fabric operational data."""
    return _consult_expert("fabriciq", invoice_id, question)


def handoff_to_waypoint_recorder(evidence_bundle_json: str) -> str:
    """Hand the fused expert evidence bundle to the waypoint-recorder for the final
    policy check and the governed Waypoint write.

    Assurance Orchestrator never writes to Waypoint itself. The waypoint-recorder is the only agent
    that fuses evidence, applies policy, and writes the run/case/recommendation.

    Args:
        evidence_bundle_json: JSON string containing the invoice id and the
            structured evidence returned by the four experts.
    """
    endpoint = _resolve_endpoint("waypoint-recorder", WAYPOINT_RECORDER_ENDPOINT_ENV)
    if endpoint is None:
        return json.dumps(
            {
                "ok": False,
                "error": f"waypoint-recorder endpoint is not configured ({WAYPOINT_RECORDER_ENDPOINT_ENV}).",
            }
        )
    bundle = _parse_json_object(evidence_bundle_json)
    invoice_ref = ""
    if isinstance(bundle, dict):
        invoice_ref = str(bundle.get("invoice_id") or bundle.get("invoice_number") or "").strip()
        # Carry the shared operation id into the bundle so the recorder's final write
        # rebuilds the SAME run + case idempotency keys the early-open used and reuses
        # that run (PATCH running->completed/failed) instead of creating a duplicate.
        #
        # ALWAYS override with the orchestrator's cached per-invoice operation id — never
        # trust a value the model placed in the bundle. A model-supplied operation_id (or
        # a second fan-out/handoff that mints a fresh one) diverges from the early-open key
        # and opens a duplicate/orphaned run+case (observed as stuck "running" anchors with
        # no recommendation). Forcing the cached op makes the record resolve to the SAME
        # run_key as the early-open, so a duplicate handoff is an idempotent no-op.
        if invoice_ref:
            bundle["operation_id"] = _operation_id_for(invoice_ref)
            evidence_bundle_json = json.dumps(bundle, ensure_ascii=False)
    prompt = (
        "You are receiving fused evidence from the domain experts for one invoice.\n"
        "Run the final policy check and perform the governed Waypoint write.\n"
        f"Evidence bundle JSON:\n{evidence_bundle_json}"
    )
    with trace_span(
        "assurance-orchestrator.handoff_to_waypoint_recorder",
        {
            **rft_reference_attributes(
                agent_name="assurance-orchestrator",
                task_family="invoice_assurance_aggregation",
                expected_tools=["waypoint-recorder.responses"],
                grader_reference={
                    "expected_decisions": ["approve", "recover", "escalate", "review"],
                    "expected_write_boundary": "waypoint-recorder",
                },
            ),
            "gen_ai.agent.name": "assurance-orchestrator",
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.tool.name": "handoff_to_waypoint_recorder",
            "forge.invoice.id": bundle.get("invoice_id") if isinstance(bundle, dict) else None,
        },
    ) as span:
        try:
            output = _ResponsesAgentClient(endpoint).run(prompt)
        except Exception as exc:
            logger.exception("handoff to waypoint-recorder failed")
            set_span_attribute(span, "forge.waypoint_recorder.status", "failed")
            return json.dumps({"ok": False, "error": str(exc)})
        set_span_attribute(span, "forge.waypoint_recorder.status", "completed")
        set_span_attribute(span, "forge.waypoint_recorder.output.characters", len(output))
        return json.dumps({"ok": True, "waypoint_recorder_result": output}, ensure_ascii=False)


def build_expert_tools() -> list[FunctionTool]:
    """Return the coordinator fan-out tools whose downstream endpoints are configured."""
    tools: list[FunctionTool] = []
    consult_funcs = {
        "workiq": consult_collaboration_evidence_expert,
        "webiq": consult_market_evidence_expert,
        "foundryiq": consult_contract_policy_expert,
        "fabriciq": consult_operations_data_expert,
    }
    for name, func in consult_funcs.items():
        if is_expert_enabled(name) and _usable_env(EXPERT_ENDPOINT_ENV[name]):
            tools.append(tool(func))
    if _usable_env(WAYPOINT_RECORDER_ENDPOINT_ENV):
        tools.append(tool(enroll_assurance_batch))
        tools.append(tool(handoff_to_waypoint_recorder))
    if not tools:
        logger.info("No pipeline endpoints configured; fan-out tools disabled.")
    return tools


def _extract_output_text(body: object) -> str:
    """Pull assistant text out of an OpenAI-Responses-style payload."""
    if isinstance(body, str):
        return body
    if not isinstance(body, dict):
        return json.dumps(body, ensure_ascii=False)
    if isinstance(body.get("output_text"), str) and body["output_text"]:
        return body["output_text"]
    chunks: list[str] = []
    for item in _as_list(body.get("output")):
        if not isinstance(item, dict):
            continue
        for content in _as_list(item.get("content")):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    return json.dumps(body, ensure_ascii=False)


def _workflow_expert_prompt(name: str, arguments: dict[str, Any]) -> str:
    invoice_ids = ", ".join(
        str(target.get("invoice_id"))
        for target in _as_dicts(arguments.get("targets"))
        if target.get("invoice_id")
    )
    payload = {
        "validator_id": name,
        "targets": arguments.get("targets", []),
        "invoice_contexts": arguments.get("invoice_contexts", []),
        "deterministic_checks": arguments.get("deterministic_checks", []),
        "read_only": True,
    }
    webiq_guidance = (
        "Do NOT search the web for the invoice id or invoice number — it has no public "
        "presence. Build market / rate / supplier-financial queries from the supplier "
        "name, spend category, line items, and amounts in the invoice_contexts below.\n"
        if name == "webiq"
        else ""
    )
    return (
        f"Invoice id(s): {invoice_ids or 'unspecified'}.\n"
        f"Gather {_PLANE_BRIEF[name]} relevant to this invoice assurance review.\n"
        f"{webiq_guidance}"
        "Use the provided deterministic checks and Waypoint context. Do not write, "
        "stage approvals, or perform side effects.\n"
        "Return repairable expert_evidence JSON with source refs, confidence, "
        "and unsupported/unknown items. Assurance Orchestrator will normalize it.\n"
        f"Context JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _normalize_expert_contract(
    name: str,
    output: str,
    execution_path: str = "responses_agent",
) -> dict[str, Any]:
    parsed = _parse_json_object(output)
    if not parsed:
        return {
            "status": "partial",
            "output_quality": "malformed",
            "summary": output.strip() or f"{name}-expert returned no structured evidence.",
            "confidence": 0.35,
            "findings": [],
            "evidence_ids": [],
            "citations": [],
            "unsupported": [],
            "execution_path": execution_path,
            "raw_reference": _default_raw_reference(name, execution_path),
        }

    evidence = _expert_evidence_items(parsed)
    evidence_ids = _unique(
        item.get("id") or _source_ref(item) or item.get("source") for item in evidence
    )
    findings = [
        {
            "invoice_id": parsed.get("invoice_id"),
            "category": name,
            "summary": _claim_text(item),
            "status": item.get("supports") or "unknown",
            "evidence_ids": _unique([item.get("id"), _source_ref(item), item.get("source")]),
            "classification": item.get("classification"),
        }
        for item in evidence
        if _claim_text(item)
    ]
    citations = [
        {
            "title": _source_ref(item) or item.get("source") or item.get("id"),
            "source": parsed.get("plane") or name,
            "classification": item.get("classification"),
        }
        for item in evidence
        if _source_ref(item) or item.get("source") or item.get("id")
    ]

    return {
        "status": _expert_status(parsed),
        "output_quality": _expert_output_quality(parsed, evidence),
        "summary": parsed.get("summary") or f"{name}-expert returned {len(evidence)} evidence item(s).",
        "confidence": _evidence_confidence(parsed, evidence),
        "findings": findings,
        "evidence_ids": evidence_ids,
        "citations": citations,
        "unsupported": _unique(parsed.get("unsupported") or parsed.get("unknowns") or []),
        "execution_path": execution_path,
        "raw_reference": parsed.get("agent") or _default_raw_reference(name, execution_path),
    }


def _default_raw_reference(name: str, execution_path: str) -> str:
    suffix = "agent_reference" if execution_path == "foundry_prompt_agent" else "responses"
    return f"{name}-expert.{suffix}"


def _prompt_experts_enabled() -> bool:
    if _prompt_expert_mode_requested():
        return True
    mode = _usable_env(PROMPT_EXPERT_MODE_ENV)
    if mode:
        return False
    return any(_usable_env(env_var) for env_var in PROMPT_EXPERT_AGENT_ENV.values())


def _prompt_expert_mode_requested() -> bool:
    mode = _usable_env(PROMPT_EXPERT_MODE_ENV)
    return bool(mode and mode.strip().lower() in {"prompt", "prompt_agent", "foundry_prompt", "foundry_prompt_agent"})


def _prompt_expert_project_endpoint() -> str | None:
    return _usable_env(
        PROMPT_EXPERT_PROJECT_ENDPOINT_ENV,
        "AZURE_AI_PROJECT_ENDPOINT",
        "AZURE_AIPROJECT_ENDPOINT",
        "FOUNDRY_PROJECT_ENDPOINT",
    )


def _looks_like_http_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def _prompt_expert_scope() -> str:
    return _usable_env(PROMPT_EXPERT_SCOPE_ENV, "EXPERT_AGENT_SCOPE") or DEFAULT_AGENT_SCOPE


def _load_prompt_expert_specs() -> dict[str, _PromptExpertSpec]:
    try:
        from prompty import load as load_prompty
    except ImportError as exc:
        raise RuntimeError(
            "Prompty is required to resolve prompt expert metadata; install the "
            "agent requirements or set hosted expert endpoints for rollback."
        ) from exc

    specs: dict[str, _PromptExpertSpec] = {}
    for validator_id, prompt_path in PROMPT_EXPERT_PATHS.items():
        if not is_expert_enabled(validator_id):
            continue
        prompt = load_prompty(prompt_path) if prompt_path.exists() else None
        metadata = prompt.metadata if prompt is not None and isinstance(prompt.metadata, dict) else {}
        forge = metadata.get("forge", {}) if isinstance(metadata.get("forge"), dict) else {}
        deployment = forge.get("deployment", {}) if isinstance(forge.get("deployment"), dict) else {}
        prompt_deploy = deployment.get("prompt", {}) if isinstance(deployment.get("prompt"), dict) else {}
        agent_name = (
            _usable_env(PROMPT_EXPERT_AGENT_ENV[validator_id], f"ASSURANCE_ORCHESTRATOR_{validator_id.upper()}_EXPERT_AGENT_NAME")
            or prompt_deploy.get("agentName")
            or (prompt.name if prompt is not None else None)
            or DEFAULT_PROMPT_EXPERT_AGENT_NAMES[validator_id]
        )
        if not agent_name:
            raise RuntimeError(f"{prompt_path}: prompt expert agent name is not configured.")
        model = (
            _usable_env(PROMPT_EXPERT_MODEL_ENV, "AZURE_AI_MODEL_DEPLOYMENT_NAME")
            or (_prompty_model_id(prompt) if prompt is not None else None)
        )
        if not model:
            raise RuntimeError(f"{prompt_path}: prompt expert model is not configured.")
        specs[validator_id] = _PromptExpertSpec(
            validator_id=validator_id,
            agent_name=str(agent_name),
            model=model,
        )
    return specs


def _prompty_model_id(prompt: Any) -> str | None:
    model_id = getattr(prompt.model, "id", None)
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    text = model_id.strip()
    if text.startswith("${env:") and text.endswith("}"):
        parts = text[6:-1].split(":", 1)
        if len(parts) == 2 and parts[1]:
            return parts[1]
    return text


def _parse_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`")
        _, _, text = text.partition("\n")
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _expert_status(parsed: dict[str, Any]) -> str:
    status = str(parsed.get("status") or "completed").lower()
    return status if status in {"completed", "partial", "failed"} else "completed"


def _evidence_confidence(parsed: dict[str, Any], evidence: list[dict[str, Any]]) -> float:
    if isinstance(parsed.get("confidence"), int | float):
        return max(0.0, min(float(parsed["confidence"]), 1.0))
    scores = [
        float(item["confidence"])
        for item in evidence
        if isinstance(item.get("confidence"), int | float)
    ]
    if scores:
        return round(sum(scores) / len(scores), 2)
    return 0.75 if evidence else 0.5


def _expert_evidence_items(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = _as_dicts(parsed.get("evidence"))
    if evidence:
        return evidence
    return _as_dicts(parsed.get("expert_evidence"))


def _expert_output_quality(parsed: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    explicit = str(parsed.get("output_quality") or "").strip().lower()
    if explicit in {"valid", "partial", "malformed", "no_evidence"}:
        return explicit
    if not evidence:
        return "no_evidence"
    if all(_claim_text(item) and _source_ref(item) for item in evidence):
        return "valid"
    return "partial"


def _claim_text(item: dict[str, Any]) -> str:
    return str(item.get("claim") or item.get("summary") or item.get("snippet") or "").strip()


def _source_ref(item: dict[str, Any]) -> str:
    direct = item.get("source_ref") or item.get("source") or item.get("url")
    if direct:
        return str(direct)
    source_refs = _as_list(item.get("source_refs"))
    return str(source_refs[0]) if source_refs else ""


def _as_dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _unique(values) -> list[str]:
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


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _usable_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and not value.startswith("{{") and not value.startswith("${"):
            return value.strip()
    return None
