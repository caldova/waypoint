"""Markdown for an invoice review document, built from Waypoint invoice records.

Facts (amounts, findings, grounding) come straight from the API; only the summary
and recommendation are model-authored.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def invoice_findings(
    detail: dict[str, Any], context: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Invoice findings, preferring the context bundle copy (it carries ``basis_summary``)."""
    source = (context or {}).get("invoice")
    if isinstance(source, dict) and isinstance(source.get("findings"), list):
        return [item for item in source["findings"] if isinstance(item, dict)]
    return [item for item in detail.get("findings") or [] if isinstance(item, dict)]


def money_at_risk(findings: list[dict[str, Any]]) -> Decimal:
    return sum(
        (_decimal(item.get("overpayment_amount")) for item in findings), Decimal(0)
    )


def build_invoice_review_markdown(
    detail: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    summary: str,
    recommendation: str,
    prepared_on: str,
) -> str:
    currency = str(detail.get("currency") or "USD")
    supplier = (
        detail.get("supplier") if isinstance(detail.get("supplier"), dict) else {}
    )
    scenario = (
        detail.get("scenario") if isinstance(detail.get("scenario"), dict) else {}
    )
    number = str(detail.get("invoice_number") or detail.get("id") or "")
    findings = invoice_findings(detail, context)
    at_risk = money_at_risk(findings)

    lines = [
        f"# Invoice review: {number}",
        "",
        f"*Prepared {prepared_on} from Waypoint invoice records.*",
        "",
        "## Summary",
        "",
        summary.strip() or "_No summary provided._",
        "",
        "## Invoice",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for label, value in (
        ("Invoice", number),
        ("Supplier", supplier.get("name") or detail.get("supplier_id")),
        ("Status", str(detail.get("status") or "").title()),
        ("Invoice date", detail.get("invoice_date")),
        ("Due date", detail.get("due_date")),
        ("Scenario", scenario.get("name")),
        ("Total", _money(detail.get("total_amount"), currency)),
        ("Money at risk", _money(at_risk, currency)),
    ):
        if value not in (None, ""):
            lines.append(f"| {label} | {_cell(value)} |")

    lines += ["", "## Findings", ""]
    if findings:
        lines += [
            "| Severity | Category | Finding | Overpayment | Basis |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for item in findings:
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        str(item.get("severity") or "").title(),
                        str(item.get("category") or "").replace("_", " "),
                        item.get("summary"),
                        _money(item.get("overpayment_amount"), currency),
                        item.get("basis_summary"),
                    )
                )
                + " |"
            )
    else:
        lines.append("No open findings; nothing blocks payment.")

    grounding = _grounding(context)
    if grounding:
        lines += ["", "## Grounded in", ""]
        lines += grounding

    lines += [
        "",
        "## Recommendation",
        "",
        recommendation.strip() or "_No recommendation provided._",
        "",
        "## Reviewer sign-off",
        "",
        "| Reviewer | Decision | Date |",
        "| --- | --- | --- |",
        "|  |  |  |",
        "",
    ]
    return "\n".join(lines)


def _grounding(context: dict[str, Any] | None) -> list[str]:
    if not context:
        return []
    lines: list[str] = []
    for label, key in (("Contract", "contract_documents"), ("Policy", "policies")):
        for item in context.get(key) or []:
            if isinstance(item, dict) and item.get("title"):
                lines.append(f"- **{label}:** {item['title']}")
    for case in context.get("cases") or []:
        if isinstance(case, dict) and case.get("title"):
            status = f" ({case['status']})" if case.get("status") else ""
            lines.append(f"- **Case:** {case['title']}{status}")
    return lines


def _cell(value: Any) -> str:
    return " ".join(str(value or "").replace("|", "\\|").split())


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _money(value: Any, currency: str) -> str:
    amount = _decimal(value)
    if currency.upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency.upper()}"
