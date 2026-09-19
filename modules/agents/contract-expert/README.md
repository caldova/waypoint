# contract-expert

Prompt-grounded Contract Expert used for the keynote/video demo. It carries the
Aster Ridge invoice, contract, and policy context in its baseline instructions
and serves only the Foundry Responses protocol.

This agent is intentionally simple: no IQ tools, no retrieval, no writeback, and
no hidden answer key. It demonstrates the reasoning shape before enterprise
grounding or workflow orchestration enters the story.

## Local development

```powershell
cd modules\agents\contract-expert
copy .env.example .env
uv sync
uv run python main.py
```

Set `FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME` in `.env`
before starting.
