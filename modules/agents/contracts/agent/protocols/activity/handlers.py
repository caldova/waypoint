"""Activity protocol handlers."""

import asyncio

from castia import Agent, Message, Teams
from contract_sources import activity_attachments, is_pdf_activity_attachment

from agent.domain.invoice_capture import capture_invoice_results
from agent.domain.modes import respond_with_mode
from agent.protocols.activity.cards import attachments_for_mode
from agent.protocols.activity.invoice_cards import invoice_attachments
from agent.protocols.activity.responding import start_activity_status
from agent.toolsets import Toolsets

INVOICE_CARD_NOTE = (
    "[If you call query_invoices, Teams renders its results as an interactive card with "
    "the invoice amounts, statuses, findings, and grounding. Then reply with a short "
    "narrative: what is going on and the recommended next step. Do not repeat tables or "
    "field-by-field lists. If you call draft_invoice_review, Teams renders a card with "
    "the document link; do not paste the link.]"
)


def _with_attachment_note(text: str, activity: object) -> str:
    """Tell the model about PDFs attached to this Teams message; it cannot see files."""
    names = [
        str(item.get("name") or "attachment.pdf")
        for item in activity_attachments(activity)
        if is_pdf_activity_attachment(item)
    ]
    if not names:
        return text
    note = f"[The user attached {len(names)} PDF file(s) to this message: {', '.join(names)}]"
    return f"{text}\n\n{note}" if text and text.strip() else note


def register_activity(app: Agent, toolsets: Toolsets) -> None:
    @app.activity(Teams.direct, Teams.group, Teams.channel_mention)
    async def ask(msg: Message) -> None:
        working = await start_activity_status(msg, status="Checking Contracts...")
        activity = msg.activity
        text = _with_invoice_card_note(_with_attachment_note(msg.text or "", activity))
        try:
            with capture_invoice_results() as invoice_results:
                answer, mode = await respond_with_mode(
                    text, toolsets=toolsets, activity=activity
                )
        except BaseException:
            await asyncio.shield(working.cancel())
            raise
        attachments = invoice_attachments(invoice_results) or attachments_for_mode(
            mode, activity=activity
        )
        await working.finish(answer, attachments=attachments)


def _with_invoice_card_note(text: str) -> str:
    if "invoice" not in text.lower():
        return text
    return f"{text}\n\n{INVOICE_CARD_NOTE}"
