# Azure deployment

Waypoint deploys in two independent parts: the **application** (web, API,
PostgreSQL) and the hosted **contract agents** in the caldova Foundry project.

## The agents

`contract-expert`, `contract-policy-expert`, and `contract-agent` are deployed
with `azd` + [castia](https://github.com/sethjuarez/castia) to the caldova
Foundry project (**West US**), either locally or through the
[Deploy contract agents workflow](../.github/workflows/deploy.yml).

Locally, from the repository root:

```bash
azd provision            # shared Foundry resources + agent/KB model deployments
castia deploy            # reconcile azure.yaml protocols from the agent decorators
azd deploy contract-expert
azd deploy contract-policy-expert
azd deploy contract-agent
```

`azd provision` is only needed on the first run or after infrastructure changes.
`gpt-6-astra` is pinned for hosted agents in `infra/main.parameters.json`;
`contracts-kb` answer synthesis currently stays on co-located `gpt-5.5` because
Azure AI Search rejected `gpt-6-astra` as an unsupported knowledge-base model.
The knowledge base also needs Azure AI Search, Foundry, and the embedding/model
deployments in the **same** region so `knowledge_base_retrieve` does not run
cross-region and fall back.

### CI deployment

The workflow uses GitHub OIDC and stores no Azure client secret. Wire these
repository variables once (see `tools/deploy/scripts/oidc.sh` for the idempotent
bootstrap):

| Variable | Purpose |
| --- | --- |
| `AZURE_CLIENT_ID` | Client ID of the GitHub OIDC deployment identity. |
| `AZURE_TENANT_ID` | Target Entra tenant ID. |
| `AZURE_SUBSCRIPTION_ID` | Target Azure subscription ID. |
| `AZD_ENV_NAME` | azd environment name; defaults to `caldova`. |
| `AZURE_LOCATION` | Azure region; defaults to `westus`. |

Run **Actions → Deploy contract agents**, enabling **provision** on the first run.

For the clean three-agent environment, use the
[`caldova-agents` buildout ledger](caldova-agents-buildout.md). It maps the
manual setup to the existing Bicep modules and tracks the remaining automation
gaps for FoundryIQ, toolbox publishing, RBAC, and acceptance.

## The application

The Waypoint app (Aspire AppHost, FastAPI API, React web, PostgreSQL, auth, and
telemetry) is deployed separately from `apps/waypoint`. See
[apps/waypoint/README.md](../apps/waypoint/README.md) for the current
`aspire`/`azd` app deployment path. Reusable OIDC, Key Vault, MSAL, and
acceptance-probe helpers live under [tools/deploy](../tools/deploy/README.md).

> The previous one-click workflow that provisioned the app and a seven-agent
> fleet together has been retired. Its orchestration remains available in git
> history if a stage needs to be re-derived for the app deployment.

## Quality and optimization

Agent quality and optimization run through `castia eval` and `castia optimize`.
Use `contract-policy-expert` for FoundryIQ-only answer quality and
`contract-agent` for workflow/writeback correctness, backed by the datasets and graders in
[modules/evals](../modules/evals/README.md) and the Agent Optimizer / RFT assets
in [modules/optimization](../modules/optimization/README.md).
