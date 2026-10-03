"""Activity protocol handlers."""

from castia import Agent, Message, Teams
from contract_sources import activity_attachments, is_pdf_activity_attachment

from agent.domain.modes import respond_with_mode
from agent.protocols.activity.cards import attachments_for_mode
from agent.protocols.activity.responding import start_activity_status
from agent.toolsets import Toolsets


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
        text = _with_attachment_note(msg.text or "", activity)
        try:
            answer, mode = await respond_with_mode(text, toolsets=toolsets, activity=activity)
        except Exception:
            await working.cancel()
            raise
        await working.finish(
            answer,
            attachments=attachments_for_mode(mode, activity=activity),
        )
