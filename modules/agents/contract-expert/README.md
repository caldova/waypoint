# contract-expert

Prompt-grounded Contract Expert used for the keynote/video demo. It carries the
Aster Ridge invoice, contract, and policy context in its baseline instructions
and serves only the Foundry Responses protocol.

This agent is intentionally simple: no IQ tools, no retrieval, no writeback, and
no hidden answer key. It demonstrates the reasoning shape before enterprise
grounding or workflow orchestration enters the story.

Responses are tuned for the Foundry Agent Playground custom canvas in the GitHub
Copilot app. The baseline instructions encourage compact Mermaid diagrams when
they clarify the evidence path, decision tree, or escalation boundary, plus a
short "Canvas moment" callout that explains what the custom canvas makes visible
for the audience. Mermaid guidance favors vertical top-down flowcharts so the
diagrams read naturally in the canvas transcript and expand cleanly in the
diagram viewer for larger flows, but favors three-node horizontal hero diagrams
when possible so the visual shows up clearly in the transcript. Diagrams are
intentionally small and high-density; line details, calculations, citations, and
open questions stay in nearby tables and prose.

The prompt also carries a lightweight invoice assurance lifecycle so diagrams can
show the full path: intake, evidence linking, line validation, classification,
human handoff, supplier response, recovery states, and escalation triggers. The
agent still remains prompt-grounded and does not approve, dispute, recover, or
write back to Caldova systems.

## Local development

```powershell
cd modules\agents\contract-expert
copy .env.example .env
uv sync
uv run python main.py
```

Set `FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME` in `.env`
before starting.
