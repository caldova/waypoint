"""Waypoint — the single invoice-assurance hosted agent, built on castia.

One agent, three Foundry wire protocols from one handler set:

- ``responses``   — the invoice-assurance run the Waypoint app triggers (the
  critical path; the app POSTs a single agent name to ``/responses``).
- ``activity``    — Teams / AI Teammate Q&A and status.
- ``invocations`` — Foundry invoke envelopes, so the agent is callable as a tool
  and in agent-to-agent flows.

Evidence and status are read-only (see ``tools.py``). The single centralized
write tool — the only thing allowed to mutate Waypoint — lives in
``write_tools.py`` and is offered only on the assurance path. When a Foundry
toolbox is configured (``TOOLBOX_*``), ``toolbox.py`` adds a server-side,
read-only retrieval spec (e.g. the FoundryIQ knowledge base) to every surface;
with none configured it attaches nothing and the direct-REST tools stand alone.

The entrypoint is ``main:app`` so ``python -m castia deploy`` / ``eval`` /
``optimize`` resolve it with zero flags.
"""

from __future__ import annotations

from castia import Agent, Depends, Message, Model, Teams, action_chips, configured_model
from dotenv import load_dotenv

from tools import read_tools
from write_tools import write_tools
from toolbox import assurance_specs, read_specs

load_dotenv()

app = Agent(name="waypoint-agent")

# Built once for the process. Instructions resolve from .agent_configs/baseline
# (or environment defaults), so the Foundry Agent Optimizer can tune the prompt
# with no handler change.
chat_model = configured_model()

# Declare every tool provider so the optimizer can treat their descriptions as an
# optimization asset. The handlers offer explicit per-surface subsets below.
app.tools(read_tools, write_tools)

# One source of truth for the tool sets, built once (Tool objects are cheap
# dataclasses; the API clients inside them are constructed per call). The
# assurance path may write; the Teams Q&A surface stays strictly read-only.
_READ_TOOLS = read_tools()
_ASSURANCE_TOOLS = _READ_TOOLS + write_tools()

# Read-only follow-up chips for the Teams surface. imBack posts the chip text as
# the user's next message, which the same read-only handler answers — so every
# suggestion maps to a read tool and can never trigger a write. Deliberately thin:
# castia renders these as an Adaptive Card, retiring the old 21KB per-agent card DSL.
_FOLLOWUPS = ("Show recent assurance runs", "Give me a case overview")


@app.responses()
async def assurance(text: str, model: Model = Depends(chat_model)) -> str:
    """Responses — the invoice-assurance run the Waypoint app calls."""
    return await model.respond_with_tools(
        text, tools=_ASSURANCE_TOOLS, activity=None, extra_specs=await assurance_specs()
    )


@app.invocations()
async def invoked(text: str, model: Model = Depends(chat_model)) -> str:
    """Invocations — callable as a Foundry tool and in agent-to-agent flows."""
    return await model.respond_with_tools(
        text, tools=_ASSURANCE_TOOLS, activity=None, extra_specs=await assurance_specs()
    )


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message, model: Model = Depends(chat_model)) -> None:
    """Activity — Teams / AI Teammate Q&A and status (read-only).

    Renders the answer as an AI-generated reply with read-only follow-up chips.
    We post via ``msg.say`` and return ``None`` so the server does not also send
    the text (an activity handler's non-empty string return is posted verbatim).
    """
    answer = await model.respond_with_tools(
        msg.text, tools=_READ_TOOLS, activity=None, extra_specs=await read_specs()
    )
    await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])


if __name__ == "__main__":
    app.run()
