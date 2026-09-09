"""Waypoint — the single invoice-assurance hosted agent, built on castia.

One agent, three Foundry wire protocols from one handler set:

- ``responses``   — the invoice-assurance run the Waypoint app triggers (the
  critical path; the app POSTs a single agent name to ``/responses``).
- ``activity``    — Teams / AI Teammate Q&A and status.
- ``invocations`` — Foundry invoke envelopes, so the agent is callable as a tool
  and in agent-to-agent flows.

Evidence and status are read-only (see ``tools.py``). The single centralized
write tool — the only thing allowed to mutate Waypoint — lives in
``write_tools.py`` and is offered only on the assurance path.

The entrypoint is ``main:app`` so ``python -m castia deploy`` / ``eval`` /
``optimize`` resolve it with zero flags.
"""

from __future__ import annotations

from castia import Agent, Depends, Model, Teams, configured_model
from dotenv import load_dotenv

from tools import read_tools
from write_tools import write_tools

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


@app.responses()
async def assurance(text: str, model: Model = Depends(chat_model)) -> str:
    """Responses — the invoice-assurance run the Waypoint app calls."""
    return await model.respond_with_tools(text, tools=_ASSURANCE_TOOLS, activity=None)


@app.invocations()
async def invoked(text: str, model: Model = Depends(chat_model)) -> str:
    """Invocations — callable as a Foundry tool and in agent-to-agent flows."""
    return await model.respond_with_tools(text, tools=_ASSURANCE_TOOLS, activity=None)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(text: str, model: Model = Depends(chat_model)) -> str:
    """Activity — Teams / AI Teammate Q&A and status (read-only)."""
    return await model.respond_with_tools(text, tools=_READ_TOOLS, activity=None)


if __name__ == "__main__":
    app.run()
