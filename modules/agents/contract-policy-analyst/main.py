"""Independent Contract Policy Analyst with the expert's real FoundryIQ lane."""

import os
from pathlib import Path

from castia import (
    Agent,
    Depends,
    Model,
)
from castia.observe.tool_capture import annotate_tool_capture
from configuration import config_evidence, load_release
from dotenv import load_dotenv
from model_route import routed_model
from observability import configure_project_export

from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

app = Agent(name="contract-policy-analyst")

_config = load_release()
chat_model = routed_model(_config)
_CHAT_MODEL_DEPENDENCY = Depends(chat_model)

app.tools(foundryiq_toolbox_tools)


@app.responses()
async def reply(text: str, model: Model = _CHAT_MODEL_DEPENDENCY) -> str:
    annotate_tool_capture(application="contract-policy-analyst", **config_evidence(_config))
    tools = foundryiq_runtime_tools(_config.tool_definitions)
    if not tools:
        raise RuntimeError("FoundryIQ toolbox endpoint is not configured.")
    return await model.respond_with_tools(text, tools=tools, activity=None)


if __name__ == "__main__":
    configure_project_export()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
