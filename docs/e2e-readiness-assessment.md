# End-to-end deployment readiness assessment

**Assessment date:** 2026-07-23 (01:48 PT, `2026-07-23T01:48-07:00`)
**Branch:** `jldeen-plan-waypoint-simplification`
**Question answered:** *If hosted-agent provisioning were working, would this
branch deploy end to end?*

This is a point-in-time readiness judgment. The supporting symptoms, root causes,
and evidence for every claim below live in
[Deployment findings and troubleshooting](deployment-troubleshooting.md); this
document only interprets them into a go/no-go readiness view.

## Bottom line

"End to end" has two different bars, and the branch sits differently on each:

| Bar | Confidence | Proven? |
| --- | --- | --- |
| **1. Deploy-green E2E** — infra + app + agents + seed + acceptance all pass | **High** | Yes, on this branch |
| **2. Grounded-demo E2E** — deploy-green **and** real contract-grounded KB retrieval with calibrated confidence | **Likely, but unproven** | No — never green in a single region |

Nothing outstanding points to a **repository** defect that blocks E2E. The one
unproven bar is gated on **external Azure/Foundry regional platform health**, not
on code in this repo.

## Point 1 — Deploy-green E2E: high confidence

The same pipeline on this branch has already completed a full clean deployment,
a convergence rerun, and a strict unchanged idempotency rerun, plus a later
runtime-evidence-correction deploy — all acceptance-green, with four active
hosted agents, one analyst Bot Service, a terminal correlated
orchestrator-to-recorder run, and preserved agent versions on rerun.

- **Why we believe it:** see
  [Validation record](deployment-troubleshooting.md#validation-record) for the
  exact GitHub Actions run IDs and the validated environment.
- **Change delta since that last green deploy:** only two commits touch the
  deploy path — the region+capacity preflight and an Aspire cold-deploy timeout
  increase. Both are additive and low-risk; neither changes the agent, infra, or
  acceptance contracts that were proven green.

**Conclusion:** if hosted-agent provisioning succeeds in the target region, the
infra → app → agents → seed → acceptance path very likely goes green again.

## Point 2 — Grounded-demo E2E: likely but unproven

Real FoundryIQ grounding (a clause-level `knowledge_base_retrieve` call with
citations) and calibrated decision confidence have **never** been green in a
single region. This is a region catch-22, not a code defect:

- **East US 2** provisions hosted agents, but lacks Azure AI Search `basic`
  capacity, so the knowledge base runs cross-region and the contract expert
  silently falls back to uncalibrated confidence. Root cause and evidence:
  [Search capacity exhaustion and cross-region KB retrieval failure](deployment-troubleshooting.md#search-capacity-exhaustion-and-cross-region-kb-retrieval-failure)
  and
  [KB upload does not prove KB retrieval](deployment-troubleshooting.md#kb-upload-does-not-prove-kb-retrieval).
- **Sweden Central** co-locates Search + Foundry + model, which would fix
  grounding — but currently cannot provision hosted agents on newly-created
  Foundry accounts. Root cause and the differential proof:
  [Region/stamp-scoped hosted-agent provisioning failure](deployment-troubleshooting.md#regionstamp-scoped-hosted-agent-provisioning-failure-new-accounts).

The branch's own region-preflight gate correctly **selects Sweden Central** (it
rejects East US 2 for Search capacity). So today the branch would deploy into the
one region where provisioning is currently blocked. If provisioning were healthy
in a co-located region, this deploy would be the **first real opportunity** to
prove grounding + calibration E2E — but that outcome remains unexercised.

**Conclusion:** high likelihood once a co-located region provisions agents, but
this bar is genuinely unproven and depends on external platform state we cannot
currently exercise.

## Residual risks (all external, tracked in the blockers catalog)

See
[Platform and environmental blockers encountered](deployment-troubleshooting.md#platform-and-environmental-blockers-encountered)
for the full catalog with class and mitigation. The load-bearing ones for E2E
readiness:

- **Region must satisfy both constraints at once** — Search `basic` capacity
  **and** healthy new-account hosted-agent provisioning. No single region has
  been green for both to date.
- **First-model service gate** — a brand-new subscription can hit an Azure
  fraud/abuse review on its first model deployment (relevant to the per-seller
  subscription model).
- **GitHub Actions runner availability** — the one-click depends on it.

## What would move Point 2 to "proven"

A single clean run in one co-located, provisioning-healthy region that reaches
acceptance **and** shows a `knowledge_base_retrieve` call with returned clause
citations (not `Fallback retrieval`) plus calibrated confidence. Until that run
exists, Point 2 stays "likely, unproven."
