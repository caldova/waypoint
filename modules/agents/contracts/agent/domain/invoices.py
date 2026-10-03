"""Invoice-mode responses shared across protocols."""

from __future__ import annotations

from agent.domain.fixtures import latest_invoice_fixtures


def is_latest_invoices_prompt(text: str) -> bool:
    normalized = text.strip().lower()
    return "invoice" in normalized and any(
        word in normalized for word in ("latest", "recent", "last", "show", "find")
    )


def latest_invoices_response() -> str:
    lines = [
        "I found **3 fixture invoices** to show the next interaction shape. "
        "These are demo records, not live Caldova data yet.",
        "",
        "| Invoice | Supplier | Amount | Status | Why it matters |",
        "|---|---:|---:|---|---|",
    ]
    for invoice in latest_invoice_fixtures():
        lines.append(
            "| {invoice_id} | {supplier} | {amount} | {status} | {summary} |".format(
                **invoice
            )
        )
    lines.extend(
        [
            "",
            "**Next useful turn:** ask me to draft a variance note or show the evidence "
            "I would need before approving payment.",
        ]
    )
    return "\n".join(lines)
