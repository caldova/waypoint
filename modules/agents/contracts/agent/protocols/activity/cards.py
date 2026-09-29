"""Teams card and suggestion rendering for Activity responses."""

from __future__ import annotations

from typing import Any

from castia import action_chips, adaptive_card

from agent.domain.fixtures import latest_invoice_fixtures
from agent.integrations.activity_identity import has_agentic_user_identity

FOLLOWUPS = (
    "What can Contracts do right now?",
    "Show latest invoices",
    "/health",
)

CAPABILITY_CHIPS = (
    "Show latest invoices",
    "Check the Contracts inbox",
    "/tools",
)

INVOICE_CHIPS = (
    "Draft a variance note",
    "Show invoice evidence",
    "/trace",
)


def attachments_for_mode(mode: str, *, activity: Any = None) -> list[dict[str, Any]]:
    if mode == "capabilities":
        return [capabilities_card(activity=activity), action_chips(*CAPABILITY_CHIPS)]
    if mode == "invoices":
        return [invoice_summary_card(), action_chips(*INVOICE_CHIPS)]
    return [action_chips(*FOLLOWUPS)]


def capabilities_card(*, activity: Any = None) -> dict[str, Any]:
    identity_ready = has_agentic_user_identity(activity)
    return adaptive_card(
        [
            {
                "type": "TextBlock",
                "text": "Contracts is hired and listening",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Chat", "value": "Capabilities and guided next steps"},
                    {"title": "Invoices", "value": "Fixture summaries for now"},
                    {
                        "title": "Agentic identity",
                        "value": "Present" if identity_ready else "Not present on this surface",
                    },
                    {"title": "Debug", "value": "/health /state /whoami /tools /trace"},
                ],
            },
        ]
    )


def invoice_summary_card() -> dict[str, Any]:
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Latest invoices - fixture preview",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        }
    ]
    for invoice in latest_invoice_fixtures():
        body.extend(
            [
                {
                    "type": "TextBlock",
                    "text": f"{invoice['invoice_id']} - {invoice['status']}",
                    "weight": "Bolder",
                    "spacing": "Medium",
                    "wrap": True,
                },
                {
                    "type": "TextBlock",
                    "text": f"{invoice['supplier']} - {invoice['amount']} - {invoice['summary']}",
                    "isSubtle": True,
                    "wrap": True,
                    "spacing": "None",
                },
            ]
        )
    return adaptive_card(body)
