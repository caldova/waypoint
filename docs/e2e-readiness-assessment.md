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
| **2. Grounded-demo E2E** — deploy-green **and** real contract-grounded KB retrieval with calibrated confidence | **Likely, but unproven via one-click** | Out of band, yes — the keynote `rg-waypoint` environment; not yet from a one-click deploy of this branch |

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

## Point 2 — Grounded-demo E2E: proven out of band, unproven via one-click

**The grounded, calibrated, single-region outcome is not hypothetical — it is
already demonstrated.** The keynote `rg-waypoint` environment runs the full
platform co-located in a single region (Sweden Central) with **more** agents and
**more** complexity than this launch package — all IQ planes (FoundryIQ, WorkIQ,
WebIQ, FabricIQ), not just the FoundryIQ launch set — and produces real
contract-grounded retrieval. So the capability, the corpus, the agent pipeline,
and the single-region topology are proven to work.

What is unproven is narrower and specific: **reaching that same grounded
single-region state from a one-click deploy of this consolidated repository on a
freshly-created Foundry account.** That gap is a region catch-22 caused by
external platform state, not a code defect:

- **East US 2** provisions hosted agents, but lacks Azure AI Search `basic`
  capacity, so the knowledge base runs cross-region and the contract expert
  silently falls back to uncalibrated confidence. Root cause and evidence:
  [Search capacity exhaustion and cross-region KB retrieval failure](deployment-troubleshooting.md#search-capacity-exhaustion-and-cross-region-kb-retrieval-failure)
  and
  [KB upload does not prove KB retrieval](deployment-troubleshooting.md#kb-upload-does-not-prove-kb-retrieval).
- **Sweden Central** co-locates Search + Foundry + model, which grounds correctly
  (the keynote environment proves it) — but currently cannot provision hosted
  agents on **newly-created** Foundry accounts. The keynote `rg-waypoint` account
  is pre-existing and therefore grandfathered onto a healthy backend; a one-click
  run creates a new account, which hits the current fault. Root cause and the
  differential proof:
  [Region/stamp-scoped hosted-agent provisioning failure](deployment-troubleshooting.md#regionstamp-scoped-hosted-agent-provisioning-failure-new-accounts).

The branch's own region-preflight gate correctly **selects Sweden Central** (it
rejects East US 2 for Search capacity). So today the branch would deploy into the
one region where new-account provisioning is currently blocked. If provisioning
were healthy in a co-located region, this deploy would be the **first one-click
run** to prove grounding + calibration on a fresh account — but that specific run
remains unexercised.

**Conclusion:** absent blockers outside our control, this should work in a single
region — the keynote `rg-waypoint` deployment is existence proof at greater agent
count and complexity. The only thing genuinely unproven is the **one-click,
fresh-account** path reaching that state, and it is blocked by external
new-account provisioning health in the co-located region, not by anything in this
repository.

## Residual risks (all external, tracked in the blockers catalog)

See
[Platform and environmental blockers encountered](deployment-troubleshooting.md#platform-and-environmental-blockers-encountered)
for the full catalog with class and mitigation. The load-bearing ones for E2E
readiness:

- **Region must satisfy both constraints at once** — Search `basic` capacity
  **and** healthy new-account hosted-agent provisioning. No single region has
  satisfied both for a **fresh, one-click** account to date (a pre-existing
  co-located account such as the keynote `rg-waypoint` already satisfies both).
- **First-model service gate** — a brand-new subscription can hit an Azure
  fraud/abuse review on its first model deployment (relevant to the per-seller
  subscription model).
- **GitHub Actions runner availability** — the one-click depends on it.

## What would move Point 2 to "proven"

The single-region grounded outcome is already proven out of band (the keynote
`rg-waypoint` environment). To close the remaining gap, one clean **one-click**
run on a **freshly-created** account in a co-located, provisioning-healthy region
must reach acceptance **and** show a `knowledge_base_retrieve` call with returned
clause citations (not `Fallback retrieval`) plus calibrated confidence. Until that
specific run exists, Point 2 stays "proven out of band, unproven via one-click."
