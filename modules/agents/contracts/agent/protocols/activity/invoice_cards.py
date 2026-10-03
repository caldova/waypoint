"""Adaptive Cards for live invoice results (list + per-invoice disposition)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from castia import adaptive_card

DISPOSITION_PROMPT = "Tell me about invoice {invoice_id}"
REVIEW_DOCUMENT_PROMPT = "Create a review document for invoice {invoice_id}"
FULL_WIDTH = {"width": "Full"}
MAX_LIST_ROWS = 10
MAX_FINDINGS = 5

_SEVERITY_STYLE = {"critical": "attention", "high": "attention", "medium": "warning"}
_SEVERITY_COLOR = {
    "critical": "Attention",
    "high": "Attention",
    "medium": "Warning",
    "low": "Good",
}
_STATUS_COLOR = {
    "approved": "Good",
    "closed": "Good",
    "paid": "Good",
    "recover": "Attention",
    "escalate": "Attention",
    "blocked": "Attention",
    "review": "Warning",
    "open": "Warning",
}


def invoice_attachments(results: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Card for this turn's invoice results, or ``None`` if there are none.

    A published review document wins; otherwise the last query_invoices result.
    """
    if not results:
        return None
    reviews = [item for item in results if item.get("kind") == "review_document"]
    if reviews:
        return [review_document_card(reviews[-1])]
    results = [item for item in results if item.get("kind") != "review_document"]
    if not results:
        return None
    result = results[-1]
    invoices = [item for item in result.get("invoices") or [] if isinstance(item, dict)]
    if not invoices:
        return None
    if len(invoices) == 1:
        context = (
            result.get("context") if isinstance(result.get("context"), dict) else None
        )
        return [invoice_disposition_card(invoices[0], context=context)]
    return [
        invoice_list_card(invoices, match_count=int(result.get("match_count") or 0))
    ]


def invoice_list_card(
    invoices: list[dict[str, Any]], *, match_count: int = 0
) -> dict[str, Any]:
    shown = invoices[:MAX_LIST_ROWS]
    total_at_risk = sum((_at_risk(item) for item in shown), Decimal(0))
    currency = _currency(shown[0])
    subtitle = f"{len(shown)} of {match_count or len(shown)} from Waypoint"
    if total_at_risk:
        subtitle += f" · {_money(total_at_risk, currency)} at risk"
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Latest invoices",
            "weight": "Bolder",
            "size": "Medium",
        },
        {
            "type": "TextBlock",
            "text": subtitle,
            "isSubtle": True,
            "spacing": "None",
            "wrap": True,
        },
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                _header_column("Invoice", "stretch"),
                _header_column("Amount", "auto", align="Right"),
                _header_column("Status", "90px", align="Right"),
            ],
        },
    ]
    for invoice in shown:
        body.append(_invoice_row(invoice))
    body.append(
        {
            "type": "TextBlock",
            "text": "Select an invoice to see its disposition.",
            "isSubtle": True,
            "size": "Small",
            "spacing": "Medium",
            "wrap": True,
        }
    )
    return adaptive_card(body, msteams=FULL_WIDTH)


def invoice_disposition_card(
    invoice: dict[str, Any], *, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    invoice_id = str(invoice.get("id") or "")
    number = str(invoice.get("invoice_number") or invoice_id)
    currency = _currency(invoice)
    status = str(invoice.get("status") or "unknown")
    at_risk = _at_risk(invoice)
    findings = _findings_with_basis(invoice, context)

    body: list[dict[str, Any]] = [
        {
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": number,
                                    "weight": "Bolder",
                                    "size": "Large",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": invoice.get("supplier_name")
                                    or invoice.get("supplier_id")
                                    or "Unknown supplier",
                                    "isSubtle": True,
                                    "spacing": "None",
                                    "wrap": True,
                                },
                            ],
                        },
                        {
                            "type": "Column",
                            "width": "auto",
                            "verticalContentAlignment": "Center",
                            "items": [_status_badge(status)],
                        },
                    ],
                }
            ],
        },
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                _stat("Invoice total", _money(invoice.get("total_amount"), currency)),
                _stat(
                    "Money at risk",
                    _money(at_risk, currency),
                    color="Attention" if at_risk else "Good",
                ),
                _stat("Findings", str(len(findings))),
            ],
        },
        {
            "type": "FactSet",
            "spacing": "Medium",
            "facts": [
                fact
                for fact in (
                    _fact("Invoice date", invoice.get("invoice_date")),
                    _fact("Due date", invoice.get("due_date")),
                    _fact("Scenario", invoice.get("scenario_name")),
                    _fact("Line items", invoice.get("line_count")),
                    _fact("Evidence", invoice.get("evidence_count")),
                )
                if fact
            ],
        },
    ]

    body.append(_section_title("Findings"))
    if findings:
        body.extend(_finding_block(item, currency) for item in findings[:MAX_FINDINGS])
        if len(findings) > MAX_FINDINGS:
            body.append(_subtle(f"+ {len(findings) - MAX_FINDINGS} more findings"))
    else:
        body.append(
            {
                "type": "Container",
                "style": "good",
                "items": [
                    _text("No open findings; nothing blocks payment.", wrap=True)
                ],
            }
        )

    grounding = _grounding_facts(context)
    if grounding:
        body.append(_section_title("Grounded in"))
        body.append({"type": "FactSet", "facts": grounding})

    actions = [
        _imback(
            "Create review document",
            REVIEW_DOCUMENT_PROMPT.format(invoice_id=invoice_id),
        ),
        _imback(
            "Draft a variance note", f"Draft a variance note for invoice {invoice_id}"
        ),
        _imback("Show evidence", f"Show the evidence for invoice {invoice_id}"),
        _imback("Back to latest invoices", "Show latest invoices"),
    ]
    if not findings:
        actions = [actions[0], *actions[2:]]
    return adaptive_card(body, actions=actions, msteams=FULL_WIDTH)


def review_document_card(result: dict[str, Any]) -> dict[str, Any]:
    invoice_id = str(result.get("invoice_id") or "")
    number = str(result.get("invoice_number") or invoice_id)
    link = str(result.get("teams_link_url") or result.get("web_url") or "")
    shared = bool(link) and result.get("storage") != "local"
    body: list[dict[str, Any]] = [
        {
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": "Review document ready"
                    if shared
                    else "Review document created",
                    "weight": "Bolder",
                    "size": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": str(result.get("title") or f"Invoice review: {number}"),
                    "isSubtle": True,
                    "spacing": "None",
                    "wrap": True,
                },
            ],
        },
        {
            "type": "FactSet",
            "spacing": "Medium",
            "facts": [
                fact
                for fact in (
                    _fact("Invoice", number),
                    _fact("Supplier", result.get("supplier_name")),
                    _fact("Findings", str(result.get("finding_count") or 0)),
                    _fact(
                        "Money at risk",
                        _money(
                            result.get("money_at_risk"),
                            str(result.get("currency") or "USD"),
                        ),
                    ),
                    _fact(
                        "Shared",
                        "With you, view access"
                        if shared
                        else "Not shared (saved locally)",
                    ),
                )
                if fact
            ],
        },
    ]
    actions: list[dict[str, Any]] = []
    if shared:
        actions.append(
            {"type": "Action.OpenUrl", "title": "Open document", "url": link}
        )
    actions.append(
        _imback("Back to invoice", DISPOSITION_PROMPT.format(invoice_id=invoice_id))
    )
    return adaptive_card(body, actions=actions, msteams=FULL_WIDTH)


def _invoice_row(invoice: dict[str, Any]) -> dict[str, Any]:
    invoice_id = str(invoice.get("id") or "")
    number = str(invoice.get("invoice_number") or invoice_id)
    currency = _currency(invoice)
    at_risk = _at_risk(invoice)
    finding_count = int(invoice.get("finding_count") or 0)
    detail = invoice.get("supplier_name") or invoice.get("supplier_id") or ""
    if finding_count:
        detail += f" · {finding_count} finding{'s' if finding_count != 1 else ''}"
        if at_risk:
            detail += f" · {_money(at_risk, currency)} at risk"
    status = str(invoice.get("status") or "unknown")
    return {
        "type": "ColumnSet",
        "spacing": "Small",
        "separator": True,
        "selectAction": _imback(
            number, DISPOSITION_PROMPT.format(invoice_id=invoice_id)
        ),
        "columns": [
            {
                "type": "Column",
                "width": "stretch",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": number,
                        "weight": "Bolder",
                        "color": "Accent",
                    },
                    {
                        "type": "TextBlock",
                        "text": detail,
                        "isSubtle": True,
                        "size": "Small",
                        "spacing": "None",
                        "wrap": True,
                    },
                ],
            },
            {
                "type": "Column",
                "width": "auto",
                "verticalContentAlignment": "Center",
                "items": [
                    _text(_money(invoice.get("total_amount"), currency), align="Right"),
                ],
            },
            {
                "type": "Column",
                "width": "90px",
                "verticalContentAlignment": "Center",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": status.title(),
                        "color": _STATUS_COLOR.get(status.lower(), "Default"),
                        "weight": "Bolder",
                        "horizontalAlignment": "Right",
                    }
                ],
            },
        ],
    }


def _finding_block(finding: dict[str, Any], currency: str) -> dict[str, Any]:
    severity = str(finding.get("severity") or "medium").lower()
    headline = " · ".join(
        part
        for part in (
            severity.upper(),
            str(finding.get("category") or "").replace("_", " "),
            str(finding.get("status") or ""),
        )
        if part
    )
    items: list[dict[str, Any]] = [
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": headline,
                            "weight": "Bolder",
                            "size": "Small",
                            "color": _SEVERITY_COLOR.get(severity, "Default"),
                            "wrap": True,
                        }
                    ],
                },
                {
                    "type": "Column",
                    "width": "auto",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": _money(finding.get("overpayment_amount"), currency),
                            "weight": "Bolder",
                            "horizontalAlignment": "Right",
                        }
                    ],
                },
            ],
        },
        _text(str(finding.get("summary") or ""), wrap=True, spacing="Small"),
    ]
    basis = finding.get("basis_summary")
    if basis:
        items.append(_subtle(f"Basis: {basis}"))
    return {
        "type": "Container",
        "style": _SEVERITY_STYLE.get(severity, "default"),
        "spacing": "Small",
        "items": items,
    }


def _findings_with_basis(
    invoice: dict[str, Any], context: dict[str, Any] | None
) -> list[dict[str, Any]]:
    findings = [
        dict(item) for item in invoice.get("findings") or [] if isinstance(item, dict)
    ]
    detail = (context or {}).get("invoice")
    raw = detail.get("findings") if isinstance(detail, dict) else None
    basis = {
        item.get("id"): item.get("basis_summary")
        for item in raw or []
        if isinstance(item, dict) and item.get("basis_summary")
    }
    for finding in findings:
        if not finding.get("basis_summary") and finding.get("id") in basis:
            finding["basis_summary"] = basis[finding["id"]]
    return findings


def _grounding_facts(context: dict[str, Any] | None) -> list[dict[str, str]]:
    if not context:
        return []
    facts: list[dict[str, str]] = []
    contracts = [
        str(doc.get("title"))
        for doc in context.get("contract_documents") or []
        if isinstance(doc, dict) and doc.get("title")
    ]
    if contracts:
        facts.append({"title": "Contracts", "value": "; ".join(contracts[:3])})
    policies = [
        str(policy.get("title") or policy.get("name"))
        for policy in context.get("policies") or []
        if isinstance(policy, dict) and (policy.get("title") or policy.get("name"))
    ]
    if policies:
        facts.append({"title": "Policies", "value": "; ".join(policies[:3])})
    cases = [
        f"{case.get('title')} ({case.get('status')})"
        for case in context.get("cases") or []
        if isinstance(case, dict) and case.get("title")
    ]
    if cases:
        facts.append({"title": "Cases", "value": "; ".join(cases[:3])})
    return facts


def _at_risk(invoice: dict[str, Any]) -> Decimal:
    return sum(
        (
            _decimal(item.get("overpayment_amount"))
            for item in invoice.get("findings") or []
            if isinstance(item, dict)
        ),
        Decimal(0),
    )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value not in (None, "") else Decimal(0)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _currency(invoice: dict[str, Any]) -> str:
    return str(invoice.get("currency") or "USD")


def _money(value: Any, currency: str) -> str:
    amount = _decimal(value)
    if currency.upper() == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency.upper()}"


def _imback(title: str, value: str) -> dict[str, Any]:
    # Same imBack shape Castia's action_chips uses: one visible user message per tap.
    return {
        "type": "Action.Submit",
        "title": title,
        "data": {"msteams": {"type": "imBack", "value": value}, "choice": value},
    }


def _status_badge(status: str) -> dict[str, Any]:
    return {
        "type": "TextBlock",
        "text": status.upper(),
        "weight": "Bolder",
        "color": _STATUS_COLOR.get(status.lower(), "Default"),
        "horizontalAlignment": "Right",
    }


def _stat(label: str, value: str, *, color: str = "Default") -> dict[str, Any]:
    return {
        "type": "Column",
        "width": "stretch",
        "items": [
            {"type": "TextBlock", "text": label, "isSubtle": True, "size": "Small"},
            {
                "type": "TextBlock",
                "text": value,
                "weight": "Bolder",
                "size": "Medium",
                "color": color,
                "spacing": "None",
            },
        ],
    }


def _header_column(text: str, width: Any, *, align: str = "Left") -> dict[str, Any]:
    return {
        "type": "Column",
        "width": width,
        "items": [
            {
                "type": "TextBlock",
                "text": text,
                "isSubtle": True,
                "size": "Small",
                "weight": "Bolder",
                "horizontalAlignment": align,
            }
        ],
    }


def _section_title(text: str) -> dict[str, Any]:
    return {
        "type": "TextBlock",
        "text": text,
        "weight": "Bolder",
        "spacing": "Large",
        "separator": True,
    }


def _fact(title: str, value: Any) -> dict[str, str] | None:
    if value in (None, "", 0):
        return None
    return {"title": title, "value": str(value)}


def _text(
    text: str, *, wrap: bool = False, align: str = "Left", spacing: str = "Default"
) -> dict[str, Any]:
    return {
        "type": "TextBlock",
        "text": text,
        "wrap": wrap,
        "horizontalAlignment": align,
        "spacing": spacing,
    }


def _subtle(text: str) -> dict[str, Any]:
    return {
        "type": "TextBlock",
        "text": text,
        "isSubtle": True,
        "size": "Small",
        "wrap": True,
    }
