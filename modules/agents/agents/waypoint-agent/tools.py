"""Waypoint tools — the agent's read-only evidence and status capabilities.

castia is deliberately "No MCP": an outbound tool is a plain
``async def impl(activity, **kwargs) -> dict`` behind a typed spec. These tools
reach the Waypoint API directly (the same REST surface the old fleet's corpus /
status clients used), grounding the single agent against real invoices,
findings, contract documents and policies rather than a client-side MCP toolbox.

Everything here is read-only. The one write path — the governed
``record_assurance`` seam that is the sole writer to Waypoint — lands in a later
unit as its own tool.

``castia.Model.respond_with_tools`` wraps each call in an ``execute_tool`` span,
so these impls carry no telemetry of their own: the framework traces them.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from castia.tools import Tool
from dotenv import load_dotenv

load_dotenv()


# ── config / env ──────────────────────────────────────────────────────────────


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def _env_bool(name: str, *, default: bool) -> bool:
    raw = _usable_env(name)
    if raw is None:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def is_waypoint_configured() -> bool:
    return _usable_env("WAYPOINT_API_BASE_URL") is not None


# ── Waypoint client (read-only) ───────────────────────────────────────────────


class _WaypointClient:
    """A thin async reader over the Waypoint API.

    Auth mirrors the deployed agents: an ``x-api-key`` when one is configured,
    otherwise a bearer token minted from the agent's managed identity for
    ``WAYPOINT_API_SCOPE`` (``az login`` locally). No scope and no key means an
    unauthenticated GET, which the local dev API accepts.
    """

    def __init__(self) -> None:
        base = _usable_env("WAYPOINT_API_BASE_URL") or ""
        if base and not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        self._base = base.rstrip("/")
        self._scope = _usable_env("WAYPOINT_API_SCOPE")
        self._api_key = _usable_env("WAYPOINT_API_KEY")
        self._verify = _env_bool("WAYPOINT_API_VERIFY_SSL", default=True)
        self._credential: Any | None = None

    def _url(self, path: str) -> str:
        if self._base.endswith("/api") and path.startswith("/api/"):
            return f"{self._base}{path[4:]}"
        return f"{self._base}{path}"

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        # Prefer the agent-identity bearer when a scope is configured; only fall
        # back to an API key when no scope is set (the Waypoint API rejects
        # x-api-key when server-side key auth is disabled).
        if self._scope:
            if self._credential is None:
                from azure.identity.aio import DefaultAzureCredential

                self._credential = DefaultAzureCredential()
            token = await self._credential.get_token(self._scope)
            headers["Authorization"] = f"Bearer {token.token}"
        elif self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=30.0, verify=self._verify) as client:
            response = await client.get(self._url(path), headers=headers, params=params)
        if response.status_code in {401, 403, 404}:
            return None
        if response.is_error or not response.content:
            return None
        return response.json()

    async def resolve_invoice(self, ref: str) -> dict[str, Any] | None:
        ref = (ref or "").strip()
        if not ref:
            return None
        detail = await self._get(f"/api/invoices/{ref}")
        if isinstance(detail, dict):
            return detail
        target = ref.lower()
        for inv in _as_list(await self._get("/api/invoices")):
            if str(inv.get("id", "")).lower() == target or str(inv.get("invoice_number", "")).lower() == target:
                resolved = await self._get(f"/api/invoices/{inv.get('id')}")
                return resolved if isinstance(resolved, dict) else None
        return None

    async def list_findings(self, invoice_id: str) -> list[dict[str, Any]]:
        return _as_list(await self._get("/api/findings", {"invoice_id": invoice_id}))

    async def list_evidence(self, invoice_id: str) -> list[dict[str, Any]]:
        return _as_list(await self._get("/api/evidence", {"invoice_id": invoice_id}))

    async def get_contract_document(self, document_id: str) -> dict[str, Any] | None:
        value = await self._get(f"/api/contract-documents/{document_id}")
        return value if isinstance(value, dict) else None

    async def get_policy(self, policy_id: str) -> dict[str, Any] | None:
        value = await self._get(f"/api/policies/{policy_id}")
        return value if isinstance(value, dict) else None

    async def get_runs(self, case_id: str | None = None) -> Any:
        return await self._get("/api/runs", {"case_id": case_id} if case_id else None)

    async def get_cases(self) -> Any:
        return await self._get("/api/cases")


# ── tool impls ────────────────────────────────────────────────────────────────


async def _gather_evidence_impl(activity: Any, *, invoice_id: str = "") -> dict[str, Any]:
    """Ground an invoice against the Waypoint corpus: findings → contracts/policies."""
    if not is_waypoint_configured():
        return _evidence(invoice_id, [], "Waypoint corpus is not configured (WAYPOINT_API_BASE_URL unset).", "not_configured")

    client = _WaypointClient()
    detail = await client.resolve_invoice(invoice_id)
    if not detail:
        return _evidence(invoice_id, [], f"No invoice matched '{invoice_id}' in the Waypoint corpus.", "not_found")

    canonical = str(detail.get("id") or invoice_id)
    invoice_number = str(detail.get("invoice_number") or canonical)
    findings = await client.list_findings(canonical) or _as_list(detail.get("findings"))

    # Normalize findings so the model weighs real severity/status, not just docs.
    finding_view = [
        {
            "id": str(f.get("id") or ""),
            "category": str(f.get("category") or f.get("finding_type") or ""),
            "severity": str(f.get("severity") or "").strip().lower(),
            "status": str(f.get("status") or "").strip().lower(),
            "overpayment_amount": _float(f.get("overpayment_amount")),
        }
        for f in findings
    ]

    seen_docs: list[str] = []
    seen_policies: list[str] = []
    for finding in findings:
        for doc_id in _str_list(finding.get("contract_document_ids")):
            if doc_id not in seen_docs:
                seen_docs.append(doc_id)
        for policy_id in _str_list(finding.get("policy_ids")):
            if policy_id not in seen_policies:
                seen_policies.append(policy_id)

    documents = {doc_id: await client.get_contract_document(doc_id) for doc_id in seen_docs}
    policies = {policy_id: await client.get_policy(policy_id) for policy_id in seen_policies}

    # Only emit a grounded claim when the source actually retrieved. A reference
    # we could not fetch is reported as a gap, never dressed up as evidence.
    evidence: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for doc_id, doc in documents.items():
        if not doc:
            unresolved.append(doc_id)
            continue
        doc_type = str(doc.get("document_type") or "contract")
        evidence.append(
            {
                "claim": f"Governing {doc_type} '{doc.get('title') or doc_id}' applies to this charge.",
                "supports": "governs",
                "source_ref": doc_id,
                "classification": "confidential",
                "confidence": 0.85,
            }
        )
    for policy_id, policy in policies.items():
        if not policy:
            unresolved.append(policy_id)
            continue
        desc = str(policy.get("description") or "")
        evidence.append(
            {
                "claim": f"Policy '{policy.get('name') or policy_id}' governs billability: {desc}".strip(),
                "supports": "governs",
                "source_ref": policy_id,
                "classification": "standard",
                "confidence": 0.85,
            }
        )

    if not (seen_docs or seen_policies):
        status = "evidence_gap"
    elif unresolved:
        status = "partial"
    else:
        status = "completed"
    resolved = len(evidence)
    referenced = len(seen_docs) + len(seen_policies)
    if status == "partial":
        summary = f"{resolved} of {referenced} governing source(s) retrieved; {len(unresolved)} could not be read: {', '.join(unresolved)}."
    elif evidence:
        summary = f"{len(seen_docs)} contract document(s) and {len(seen_policies)} policy(ies) govern this invoice's {len(findings)} finding(s)."
    else:
        summary = "No governing contract or policy references found for this invoice."
    payload = _evidence(canonical, evidence, summary, status)
    payload["invoice_number"] = invoice_number
    payload["findings"] = finding_view
    payload["unresolved_sources"] = unresolved
    return payload


async def _run_status_impl(activity: Any, *, case_id: str = "") -> dict[str, Any]:
    """Report Waypoint assurance run status, optionally filtered to one case."""
    if not is_waypoint_configured():
        return {"ok": False, "error": "Waypoint is not configured."}
    try:
        runs = await _WaypointClient().get_runs(case_id=case_id.strip() or None)
    except Exception as exc:  # noqa: BLE001 - fail soft back to the model
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "runs": runs}


async def _case_overview_impl(activity: Any) -> dict[str, Any]:
    """Report a high-level overview of Waypoint assurance cases."""
    if not is_waypoint_configured():
        return {"ok": False, "error": "Waypoint is not configured."}
    try:
        cases = await _WaypointClient().get_cases()
    except Exception as exc:  # noqa: BLE001 - fail soft back to the model
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "cases": cases}


# ── tool provider ─────────────────────────────────────────────────────────────


def read_tools() -> list[Tool]:
    """The single agent's read-only evidence + status tools.

    Registered even when Waypoint is unconfigured: each impl returns an explicit
    not-configured result, so the model can never imply a retrieval ran when no
    endpoint is available.
    """
    return [
        Tool(
            name="gather_evidence",
            description=(
                "Retrieve grounded contract and policy evidence for an invoice under "
                "assurance review. Resolves the invoice in the Waypoint corpus, reads "
                "its reconciliation findings, and returns the governing contract "
                "documents and policies with source references. Call this before "
                "deciding — never invent evidence; if none is found, say so."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice id or invoice number under review.",
                    },
                },
                "required": ["invoice_id"],
                "additionalProperties": False,
            },
            impl=_gather_evidence_impl,
        ),
        Tool(
            name="run_status",
            description=(
                "Report Waypoint assurance run status. Pass a case_id to filter to one "
                "case, or omit it for recent runs. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "case_id": {
                        "type": "string",
                        "description": "Optional case id to filter runs to.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_run_status_impl,
        ),
        Tool(
            name="case_overview",
            description=(
                "Report a high-level overview of Waypoint assurance cases. Read-only."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            impl=_case_overview_impl,
        ),
    ]


# ── helpers ───────────────────────────────────────────────────────────────────


def _evidence(invoice_id: str, evidence: list[dict[str, Any]], summary: str, status: str) -> dict[str, Any]:
    return {
        "agent": "waypoint-agent",
        "invoice_id": invoice_id,
        "evidence": evidence,
        "summary": summary,
        "status": status,
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
