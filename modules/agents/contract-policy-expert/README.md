# contract-policy-expert

Prompty-backed contract and policy expert for Teams-facing Q&A and optimization.
It answers from the `contracts-kb` evidence plane through
`knowledge_base_retrieve`, remains strictly read-only, and uses Castia's
optional Prompty runtime harness for each turn.

This agent is intentionally separate from the full `contract-agent`: its eval and
fine-tuning target is grounded answer quality, not workflow orchestration or
writeback behavior.

`eval.yaml` points at the shared `modules/evals/datasets/contract-policy-expert`
splits so `castia eval` / `castia optimize` can treat this as the clean
FoundryIQ quality lane.

## Local development

```powershell
cd modules\agents\contract-policy-expert
copy .env.example .env
uv sync
uv run python main.py
```

Set the Foundry project/model values and a FoundryIQ toolbox endpoint before
testing live retrieval. The Prompty harness is provided by the
`castia[optimize,prompty]` dependency and emits Prompty tracing through the
active Castia/OpenTelemetry provider.
