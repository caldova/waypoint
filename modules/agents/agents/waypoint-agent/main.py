"""Waypoint — the single invoice-assurance hosted agent, built on castia.

One agent, three Foundry wire protocols from one handler set:

- ``responses``   — the invoice-assurance run the Waypoint app triggers (the
  critical path; the app POSTs a single agent name to ``/responses``).
- ``activity``    — Teams / AI Teammate Q&A and status (Adaptive Cards land in a
  later step).
- ``invocations`` — Foundry invoke envelopes, so the agent is callable as a tool
  and in agent-to-agent flows.

Evidence and status are read-only. A single centralized write tool — the only
thing allowed to mutate Waypoint — is added in a later step.

The entrypoint is ``main:app`` so ``python -m castia deploy`` / ``eval`` /
``optimize`` resolve it with zero flags.
"""

from __future__ import annotations

from castia import Agent, Depends, Model, Teams, configured_model
from dotenv import load_dotenv

load_dotenv()

app = Agent(name="waypoint-agent")

# Built once for the process. Instructions resolve from .agent_configs/baseline
# (or environment defaults), so the Foundry Agent Optimizer can tune the prompt
# with no handler change.
chat_model = configured_model()


@app.responses()
async def assurance(text: str, model: Model = Depends(chat_model)) -> str:
    """Responses — the invoice-assurance run the Waypoint app calls."""
    return await model.respond(text)


@app.invocations()
async def invoked(text: str, model: Model = Depends(chat_model)) -> str:
    """Invocations — callable as a Foundry tool and in agent-to-agent flows."""
    return await model.respond(text)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(text: str, model: Model = Depends(chat_model)) -> str:
    """Activity — Teams / AI Teammate Q&A and status."""
    return await model.respond(text)


if __name__ == "__main__":
    app.run()
