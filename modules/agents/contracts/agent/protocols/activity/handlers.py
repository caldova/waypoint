"""Activity protocol handlers."""

from castia import Agent, Message, Teams

from agent.domain.modes import respond_with_mode
from agent.protocols.activity.cards import attachments_for_mode
from agent.protocols.activity.responding import start_activity_status
from agent.toolsets import Toolsets


def register_activity(app: Agent, toolsets: Toolsets) -> None:
    @app.activity(Teams.direct, Teams.group, Teams.channel_mention)
    async def ask(msg: Message) -> None:
        working = await start_activity_status(msg, status="Checking Contracts...")
        text = msg.text
        activity = msg.activity
        try:
            answer, mode = await respond_with_mode(text, toolsets=toolsets, activity=activity)
        except Exception:
            await working.cancel()
            raise
        await working.finish(
            answer,
            attachments=attachments_for_mode(mode, activity=activity),
        )
