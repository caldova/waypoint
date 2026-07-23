# Deployment findings and troubleshooting

This guide records the issues found while proving the consolidated Waypoint
deployment end to end. It complements the canonical
[Azure deployment guide](deployment.md) with observed symptoms, root causes,
mitigations, and verification steps.

The final validated environment used:

| Resource plane | Region |
| --- | --- |
| Foundry account, project, models, hosted agents, ACR, storage, and monitoring | East US 2 |
| Waypoint web/API, PostgreSQL, and Azure AI Search | North Europe |

The clean deployment, convergence rerun, and strict unchanged rerun all
completed successfully. The unchanged rerun preserved all four hosted-agent
versions.

## Validation record

| Purpose | GitHub Actions run |
| --- | --- |
| Clean full deployment | `29975010853` |
| Convergence rerun after state preservation | `29976423127` |
| Strict unchanged idempotency rerun | `29977004582` |
| Runtime evidence-presentation correction | `29979862681` |

The validated environment is `waypoint-e2e-eus2`, with app resource group
`rg-waypoint-e2e-eus2` and state resource group
`rg-waypoint-e2e-eus2-state`. Failed Sweden and France validation environments
were removed after the successful run was preserved.

## Start with the failing stage

Do not wait for the entire workflow when a required job has already failed.
The root workflow intentionally blocks downstream mutation after a failed
prerequisite.

1. Identify the first failed required job, not the last skipped job.
2. Read only that job's failed log:

   ```bash
   gh run view <run-id> --repo caldova/waypoint --log-failed
   ```

3. Check the live resource state before retrying. A failed GitHub API request or
   local watcher does not mean Azure deployment failed.
4. Retry only after classifying the failure as configuration, deterministic
   code, Azure capacity, propagation, or an external service incident.
5. Require **Acceptance and evidence** to pass before calling the deployment
   healthy.

When polling GitHub Actions programmatically, retry transport failures such as
TLS handshake errors. Fail fast on a completed failed job, but do not translate
a monitoring transport error into a deployment failure.

## Findings from the validated E2E

| Symptom | Root cause | Current handling |
| --- | --- | --- |
| Content Understanding failed in France Central | The region did not support the required GA capability set | Preflight allows only the documented Hosted Agents and Content Understanding intersection |
| Azure AI Search creation failed in East US 2 | Regional Search capacity was exhausted | Search can fail over to the app region without moving Foundry or hosted-agent compute |
| Container Apps provisioning stalled or reported capacity pressure | Azure regional capacity or a poisoned partial managed environment | Deployment uses bounded attempts and narrowly scoped cleanup/retry |
| A recreated app could not pull its image | Managed-identity and `AcrPull` propagation raced the new Container Apps environment | The exact failure reconciles the sole expected identity/registry assignment and retries once |
| ACR hostname temporarily returned `no such host` | New-registry DNS propagation | The exact registry-resolution failure receives one bounded retry |
| Responses-only agents failed deployment bookkeeping | State recording incorrectly assumed every agent owned a Bot Service | Bot handling is protocol-aware; only `invoice-analyst` owns Activity protocol and a Bot |
| Agent state tags disappeared on an unchanged rerun | `az group create` on an existing resource group cleared its tags | Existing groups are reused via `az group exists`; creation is never used as reconciliation |
| Parallel agent state writes returned `RequestConflict` | Concurrent tags targeted a shared, settling Foundry account | State is stored on the dedicated state resource group with bounded conflict retries |
| Unchanged agents received new versions | Missing state tags made every agent appear changed | Per-agent source/environment hashes and live versions are preserved in state-group tags |
| Custom-environment validation failed before deployment | `postgres_server_name` was omitted | Every non-default environment must explicitly supply app RG, state RG, MSAL display name, and PostgreSQL server |
| Teardown timed out while the managed environment was deleting | Container Apps remained `ScheduledForDelete` longer than the default 300-second wait | Teardown stops safely, preserves state, and can be resumed with a longer poll window |
| Collaboration Evidence Expert appeared in the app although WorkIQ was disabled | A historical recorder payload mislabeled orchestrator checks as a WorkIQ lane | Recorder rejects noncanonical agent/plane pairs; UI excludes orchestrator and recorder control lanes |
| Every invoice displayed 85% confidence | The FoundryIQ fallback assigned `0.85` to document/policy retrieval and the UI presented that evidence score as decision confidence | Scores retain provenance internally and are displayed as **Not calibrated** unless explicitly calibrated |

## Regional placement

### Unsupported Foundry capability combinations

A region that supports Azure AI services generally may still lack one of the
specific capabilities Waypoint requires. France Central failed at Content
Understanding even though other Foundry resources were available.

Use a region accepted by workflow preflight. Do not bypass the allowlist to get
past validation; it exists to prevent a later partial deployment.

### Search capacity exhaustion

East US 2 had the required Foundry capabilities but could not allocate Azure AI
Search capacity. Search was placed in North Europe while Foundry, models, ACR,
storage, monitoring, and hosted-agent compute remained together in East US 2.

This split did not cause hosted-agent activation failures. Search is consumed
through the knowledge-base connection at runtime and is not involved in pulling
or activating hosted-agent images.

If Search falls back:

- keep Foundry and hosted-agent compute in the selected Foundry region;
- verify the existing Search resource location before a rerun;
- pass the discovered location back into Bicep; and
- run KB upload and acceptance again.

### Hosted-agent activation

Earlier Sweden Central attempts failed during hosted-agent platform/account
activation before any ACR image pull. That evidence did not implicate
cross-region Search or the app region.

Classify activation failures by checking whether the platform reached image
pull:

- failure before image pull: investigate Foundry account/platform activation;
- image pull authorization failure: inspect the managed identity and `AcrPull`;
- image resolution failure: inspect ACR DNS and image existence; or
- container startup failure: inspect the hosted-agent revision logs and
  application entrypoint.

## Agent topology and protocol checks

The launch fleet is exactly:

- `invoice-analyst`;
- `assurance-orchestrator`;
- `contract-policy-expert`; and
- `waypoint-recorder`.

Only `invoice-analyst` exposes Activity protocol and owns a Bot Service. The
other three agents are Responses-only. A healthy launch environment therefore
has four active hosted agents and exactly one Bot Service.

Responses-only state recording must also remove stale Bots left by older
deployments. Do not restore the earlier assumption that each agent requires a
Bot.

## State and idempotency

Per-agent deployment state is stored as tags on the dedicated state resource
group. Each agent records its desired-state hash and active version.

The critical Azure CLI behavior is:

> Running `az group create` against an existing resource group can clear its
> tags even when no tags are supplied.

Clearing those tags destroys the comparison baseline and causes unnecessary new
agent versions. Any script that needs the state group must:

1. call `az group exists`;
2. create the group only when absent; and
3. update individual tags without replacing unrelated state.

An unchanged rerun should log that each agent already matches desired state and
skip `azd deploy`. Verify that active versions are identical before and after
the rerun.

## Container Apps recovery

The app deployment is bounded. It retries only recognized transient failures:

- `ManagedEnvironmentCapacityHeavyUsageError`;
- `AKSCapacityHeavyUsage`;
- the expected managed-identity image-pull propagation failure; and
- a new-ACR `no such host` resolution failure.

Unknown failures remain fail-fast. Cleanup of a partial managed environment is
allowed only when it contains no Container Apps. An environment with apps fails
closed for operator review.

Do not repeatedly dispatch the workflow while an earlier managed environment is
still being deleted. Check:

```bash
az containerapp env show \
  --resource-group <app-rg> \
  --name <managed-environment> \
  --query properties.provisioningState \
  -o tsv
```

## Safe teardown and resume

The guarded teardown order is:

1. Container Apps and .NET components;
2. Container Apps managed environment;
3. app resource group;
4. owned soft-deleted app resources;
5. owned app registration;
6. state resource group;
7. owned soft-deleted state resources; and
8. local azd state.

If app-group deletion exceeds the default poll window, the script intentionally
preserves the state group, app registration, and local azd environment. Resume
the same teardown after Azure finishes the asynchronous deletion:

```bash
WAYPOINT_TEARDOWN_POLL_ATTEMPTS=120 \
python tools/deploy/scripts/seller_teardown.py \
  --subscription-id "<subscription-id>" \
  --app-resource-group "<app-rg>" \
  --state-resource-group "<state-rg>" \
  --azd-env "<azd-env>" \
  --deployment-client-id "<deployment-client-id>" \
  --repository caldova/waypoint \
  --delete-app-registrations \
  --apply \
  --confirm-environment "<azd-env>"
```

Never delete the state group first to work around a slow app-group deletion.
The state group is the ownership and recovery boundary.

After teardown, verify:

```bash
az group exists --name "<app-rg>"
az group exists --name "<state-rg>"
az ad app list --filter "displayName eq '<environment-name>'" \
  --query "[].appId" -o tsv
(cd modules/agents && azd env list)
```

Both resource-group checks should return `false`, the owned app registration
query should be empty, and the local environment should no longer be listed.

## App evidence presentation

### False WorkIQ participation

One historical run contained this inconsistent shape:

```json
{
  "agent": "assurance-orchestrator",
  "plane": "workiq",
  "source_ref": "deterministic_checks:<invoice-id>:line_math"
}
```

The Collaboration Evidence Expert was neither deployed nor consulted. The UI
mapped the bad `plane` value to WorkIQ and displayed a false participant.

The recorder now accepts only canonical expert/plane pairs, does not synthesize
optional experts from generic invoice context, and excludes pipeline control
agents from `experts_consulted`. The UI independently excludes orchestrator and
recorder lanes from expert usage. Historical malformed records remain stored for
auditability but are not presented as expert participation.

### Uniform 85% confidence

The observed app assurance runs used the contract expert's local fallback. That
fallback assigned `0.85` to each located contract or policy reference. Because
FoundryIQ was the only enabled evidence lane, averaging those evidence scores
also produced `0.85` for every run.

That number is not calibrated decision accuracy. New recorder metadata marks
its basis as `expert_evidence_mean` and `confidence_calibrated: false`. The API
does not expose an uncalibrated numeric score as decision confidence, and the UI
shows **Not calibrated**.

Do not generate artificial variation by decision, severity, or citation count.
A numeric decision confidence should be displayed only after a reviewed
calibration process sets `confidence_calibrated: true`.

Running assurance again does not calibrate confidence. Assurance is an
inference operation; calibration is a separate quality operation that compares
scores with reviewed outcomes over a representative dataset and versions the
resulting calibration artifact. A rerun using the same fallback evidence path
will correctly remain **Not calibrated**.

The post-fix 18-invoice batch confirmed this contract:

- all 18 runs recorded `confidence_basis: expert_evidence_mean`;
- all 18 recorded `confidence_calibrated: false`;
- all 18 retained the raw `0.85` evidence score for audit; and
- 16 run summaries explicitly identified fallback retrieval.

Before displaying a numeric value again, the platform needs a reviewed
calibration process that:

1. defines what the score predicts;
2. evaluates it against human-reviewed outcomes;
3. measures calibration error by decision and evidence shape;
4. versions the dataset, grader, and calibration mapping; and
5. sets `confidence_calibrated: true` only for runs using that approved mapping.

## Remaining known limitations

### KB upload does not prove KB retrieval

The deployment successfully created and populated `contracts-kb`, but observed
app assurance summaries said `Fallback retrieval`. This means the hosted
contract expert used `gather_contract_policy_evidence` rather than proving a
clause-level `knowledge_base_retrieve` MCP call for those runs.

The current acceptance test proves:

- application health;
- expected hosted-agent inventory;
- terminal orchestrator-to-recorder lifecycle;
- governed evidence persistence; and
- operation correlation.

It does **not** yet fail when the contract expert falls back instead of using
the KB MCP connection. Treat this as a fidelity gap, not a deployment outage.
Before claiming clause-level FoundryIQ grounding in the app path, inspect the
trace for `knowledge_base_retrieve` and returned clause citations.

### Teardown can outlive the default timeout

Container Apps managed-environment deletion can take substantially longer than
five minutes. Teardown is resumable and safe, but the default wait remains
shorter than the longest observed deletion. Use the poll override above until
the default is increased or made an explicit CLI option.

### Historical audit records are immutable

Previously stored malformed fanout lanes and raw `0.85` values remain in run
metadata. Product projections now interpret them safely. Do not mutate governed
history solely to make the current UI cleaner.

## Final verification checklist

A deployment is complete only when all of the following are true:

- **Acceptance and evidence** succeeded.
- Web returns HTTP 200 and the API health probe passes.
- The expected corpus is present.
- Exactly four launch agents are active.
- Exactly one Bot Service exists and belongs to `invoice-analyst`.
- A governed assurance run reaches a terminal state through
  `waypoint-recorder`.
- The run has an App Insights operation ID.
- Optional WorkIQ, WebIQ, and FabricIQ experts are absent from launch
  participation.
- Uncalibrated evidence scores are not displayed as decision confidence.
- An unchanged rerun skips all unchanged agents and preserves their versions.
- Failed test environments are fully removed without deleting the validated
  environment.

Never include API keys, PostgreSQL passwords, access tokens, or unredacted
deployment evidence in troubleshooting output.
