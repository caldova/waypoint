"""contract-evidence-analyst: one supplier invoice line + supplied sources -> evidence-only JSON review.

Independent of contract-policy-expert. Optimizer-ready: the model and instructions come from the resolved
optimization config (``agent_config.load``), and every hosted version declares the model it runs. The
request text carries the full task contract and sources, so every arm (baseline, optimized, MAI-2, tuned
MAI-2) sees identical user input; only the instructions/model differ.
"""

from __future__ import annotations

import os
from pathlib import Path

from castia import Agent, Depends, Model, trace_attribute
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

import agent_config  # noqa: E402
from model_route import routed_model  # noqa: E402

app = Agent(name="contract-evidence-analyst")

_config = agent_config.load()
_MODEL = Depends(routed_model(_config))


@app.responses()
async def reply(text: str, model: Model = _MODEL) -> str:
    trace_attribute("contract_evidence.config_source", _config.source)
    trace_attribute("contract_evidence.model", _config.model)
    return await model.respond(text)


if __name__ == "__main__":
    import background_shim

    background_shim.install()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
