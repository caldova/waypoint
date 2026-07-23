# End-to-end deployment readiness assessment

**Assessment date:** 2026-07-23 (01:48 PT, `2026-07-23T01:48-07:00`)
**Revised:** 2026-07-23 (01:56 PT, `2026-07-23T01:56-07:00`) after an independent
review — corrected over-claims (see [Revision notes](#revision-notes-2026-07-23)).
**Revised:** 2026-07-23 (10:02 PT, `2026-07-23T10:02-07:00`) after UK South
one-click/idempotency proof and live KB trace comparison with the prior Forge
deployment.
**Revised:** 2026-07-23 (11:55 PT, `2026-07-23T11:55-07:00`) after current-head
UK South one-click run `30034540034` passed with grounded KB runtime evidence.
**Branch:** `jldeen-plan-waypoint-simplification`
**Question answered:** *If hosted-agent provisioning were working, would this
branch deploy end to end?*

This is a point-in-time readiness judgment. The supporting symptoms, root causes,
and evidence for every claim below live in
[Deployment findings and troubleshooting](deployment-troubleshooting.md); this
document only interprets them into a go/no-go readiness view.

## Bottom line

"End to end" is really three bars, not two, and the branch sits differently on
each. Separating them is the whole point — collapsing them hides where the real
gaps are:

| Bar | What it means | Status |
| --- | --- | --- |
| **1. Deploy-green (structural)** | infra + app + agents + seed + acceptance all pass | **Proven at current head in UK South** on `30034540034`; earlier unchanged idempotency rerun `30000311095` preserved stable resources and agent versions |
| **2. Grounded KB retrieval** | a real KB retrieval path with returned clause citations, not `Fallback retrieval` | **Proven at current head in UK South** on `30034540034` by recorder-preserved retrieval `ref_id` citations and no fallback markers after matching the prior Forge model split (`gpt-5.5` hosted agents, `gpt-5-mini` KB answer synthesis) |
| **3. Calibrated confidence** | displayed decision confidence is a calibrated probability, not a raw evidence score | **Not implemented** — numeric raw scores are visible again as uncalibrated **evidence scores**; calibrated confidence still requires a reviewed calibration artifact |

The earlier version of this document folded bars 2 and 3 together and called the
whole thing "external." That was wrong: **grounded retrieval** needed both
platform health and a repo-side KB model split; **calibration** remains unbuilt
code we own.

## Point 1 — Deploy-green (structural): proven in UK South

Run `29998293196` completed a clean single-region UK South deployment from this
branch with the app, PostgreSQL, seed data, Search, Foundry infrastructure,
contracts KB upload, four active hosted agents, and a terminal correlated
orchestrator-to-recorder run. Run `30000311095` repeated the same environment
unchanged and passed idempotency, preserving stable resources and agent versions.
Current-head run `30034540034` then passed all jobs after the KB model split and
acceptance-gate hardening:

- app, seed import, Foundry infrastructure, KB upload, all four hosted agents,
  app/agent wiring, acceptance, and baseline recording passed;
- terminal run `run-14af8323ab954397a14f8da4e20bf189` completed through
  `waypoint-recorder`; and
- acceptance passed the KB retrieval evidence gate.

- **Why we believe the plumbing:** see
  [Validation record](deployment-troubleshooting.md#validation-record) for the
  exact GitHub Actions run IDs and the validated environment.

**Conclusion:** if the selected region can provision hosted agents and required
resources, this branch's structural one-click path is proven to deploy E2E in a
single region.

## Point 2 — Grounded KB retrieval: proven in UK South

**The grounded single-region *capability* is real, not hypothetical.** The
keynote `rg-waypoint` environment runs the platform co-located in one region
(Sweden Central), across more IQ planes than this launch package, and produces
real contract-grounded retrieval. That is a **topology and feature existence
proof**: it proves the corpus, the KB wiring, and a co-located Search→Foundry→
model design can ground.

It is **not** proof of this branch's one-click path, and it should not be leaned
on as if it were. `rg-waypoint` is a **pre-existing, hand-matured** account: it
does not exercise this repository's fresh-account creation flow, current images,
simplified fleet, acceptance assertions, idempotency, or calibration. Treat it as
"the destination exists," not "this branch arrives there automatically."

What was unproven was specific: **reaching that grounded single-region state from
a one-click deploy of this repository on a freshly-created Foundry account.** UK
South removed that doubt for a single region. The first green run exposed a
repo-side KB configuration mismatch; current-head run `30034540034` proves the
fix:

- **East US 2** provisions hosted agents, but lacks Azure AI Search `basic`
  capacity, so the knowledge base runs cross-region and the contract expert
  silently falls back. Evidence:
  [Search capacity exhaustion and cross-region KB retrieval failure](deployment-troubleshooting.md#search-capacity-exhaustion-and-cross-region-kb-retrieval-failure)
  and
  [KB upload does not prove KB retrieval](deployment-troubleshooting.md#kb-upload-does-not-prove-kb-retrieval).
- **UK South** co-locates Search + Foundry + hosted agents. It first deployed
  structurally, but the consolidated KB was bound to the hosted-agent
  `gpt-5.5` deployment. Live traces proved `knowledge_base_retrieve` was invoked
  and then failed because Search's KB backend used chat completions with
  `reasoning_effort` against `gpt-5.5`.
- **Prior Forge / `rg-waypoint`** uses `gpt-5-mini` for `contracts-kb` answer
  synthesis while keeping hosted agents on `gpt-5.5`. The consolidated branch now
  mirrors that simpler shape.
- **Current-head UK South proof** (`30034540034`) passed acceptance with terminal
  run `run-14af8323ab954397a14f8da4e20bf189`, operation
  `93a129706c5e366a82105d6dc3d33436`, retrieved `ref_id` citations in recorded
  runtime evidence, and no fallback or KB error markers.
- **Sweden Central** co-locates Search + Foundry + model and grounds correctly
  (the keynote proves the capability) — but currently cannot provision hosted
  agents on **newly-created** Foundry accounts. Differential:
  [Region/stamp-scoped hosted-agent provisioning failure](deployment-troubleshooting.md#regionstamp-scoped-hosted-agent-provisioning-failure-new-accounts).

### How strong is the "region, not our code" conclusion?

Strong on discrimination, honest about mechanism. The differential is a clean
2×2: **both** account-creation flows fail in Sweden Central and **both** succeed
in East US 2 —

| Creation flow | Sweden Central | East US 2 |
| --- | --- | --- |
| Our `azd`/Bicep deploy | E2E account failed | historical full deploy → 4 active agents |
| Manual `az`-CLI clean-room (identical steps both regions) | failed (our image **and** the `forge` image) | active in ~40s (our exact image) |

Because the manual clean-room used identical creation steps in both regions and
only the region differed, **creation flow is controlled and region is the
discriminator**. That rules out an image, architecture, or repository-config
defect as the cause.

What it does **not** do is confirm the *mechanism*. "Pre-existing accounts are
grandfathered onto a healthy stamp" is an **inferred** explanation that fits the
evidence, not an observed fact — we cannot see Foundry's control-plane
provisioning logs. The only way to confirm the mechanism (and whether it is
region-wide vs. subscription-scoped, which matters for the per-seller model) is a
Microsoft support case with the failing `request-id`s. Until then, state it as a
**strongly localized, well-evidenced hypothesis**, not a settled root cause.

### The region-preflight catch-22 (still real)

The branch's region selector
(`tools/deploy/scripts/region_capacity_preflight.py`) chooses a region from a
**static** "supports Hosted Agents + Content Understanding GA" allow-list, then
scores it on model availability for `gpt-5.5`, `gpt-5-mini`, and embeddings, quota, and a
Search `basic` PUT/DELETE probe. It does **not** — and today cannot — test
fresh-account hosted-agent *provisioning health*. Consequence: it may prefer a
region with perfect Search/model capacity but broken fresh-agent provisioning.

By explicit decision we are **not** adding a hosted-agent provisioning probe to
the preflight right now. But the contradiction must be named: the preflight
optimizes for KB co-location and is silent on the one failure mode that is
actually blocking us, so its "Sweden Central selected" output should not be read
as "Sweden Central will succeed."

**Conclusion:** absent external provisioning faults, the co-located grounded path
works in a single region. The branch now has the right KB model split and a gate
that fails closed if it falls back. The remaining risk is regional availability,
not grounded-retrieval wiring.

## Point 3 — Calibrated confidence: not yet implemented (our code)

This is the correction the previous version got wrong by bundling it into "Point
2, external." Displayed decision confidence is **not** a calibrated probability today. The
recorder no longer hardcodes calibration status: it preserves
`confidence_basis`, `confidence_calibrated`, and calibration artifact/version
provenance from the code-owned orchestration or quality layer, and it refuses to
mark confidence calibrated when a payload merely claims `confidence_calibrated:
true` without that provenance. The current orchestrator's score is explicitly
labeled `expert_evidence_mean` and uncalibrated. The product now shows the
numeric value again to match the earlier Forge/Waypoint experience, but labels it
as an **evidence score** unless `confidence_calibrated: true` carries approved
artifact/version provenance. Turning raw evidence scores into a calibrated
probability is repository work that does not exist yet.

## Residual risks

See
[Platform and environmental blockers encountered](deployment-troubleshooting.md#platform-and-environmental-blockers-encountered)
for the full catalog with class and mitigation. The load-bearing ones for E2E
readiness — note that not all are external:

- **Region must satisfy all constraints at once (external)** — Search `basic`
  capacity, `gpt-5.5`, `gpt-5-mini`, embeddings, Postgres, and healthy
  new-account hosted-agent provisioning. UK South satisfied those constraints
  for the current proof; Sweden Central currently fails fresh hosted-agent
  provisioning.
- **Preflight steers into the blocked region (our code, by omission)** — the
  region selector optimizes for co-located Search and is blind to fresh-account
  provisioning health, so it selects Sweden Central, which currently fails. We are
  intentionally not adding a provisioning probe yet, so this remains a known,
  unmitigated routing gap.
- **Calibration is unbuilt (our code)** — Bar 3 above; numeric evidence scores
  are visible but not calibrated decision probabilities.
- **First-model service gate (external)** — a brand-new subscription can hit an
  Azure fraud/abuse review on its first model deployment (see fleet-scale below).
- **GitHub Actions runner availability (external)** — the one-click depends on it.

## Fleet-scale viability (the 20,000-seller goal)

The end goal is one-click deployment across tens of thousands of sellers, **each
in its own Azure subscription**. That reframes two "external, transient" blockers
as potentially **structural**, because every new seller repeats exactly the
cold-account operations that are failing today:

- **First-model fraud/abuse gate** fires on a *new account's first model deploy*.
  A per-account manual review is fundamentally incompatible with unattended
  one-click onboarding at fleet scale.
- **Fresh-account hosted-agent provisioning** is exactly the fresh-account
  operation that fails in Sweden Central right now, and the preflight's regional
  preference creates a **correlated failure domain** (many sellers steered to the
  same region fail together).

Even a low per-account failure rate is operationally heavy at this volume (1% of
20,000 is ~200 sellers needing hands-on repair). Treat the current state as
**pilot-scale**, not 20k-ready. Moving to fleet-ready requires things that do not
exist yet and are mostly outside this repository: programmatic/pre-cleared model
enablement (no per-account fraud gate), capacity/provisioning commitments in **at
least two** co-located regions, a fresh-account provisioning SLO, staged rollout
with canaries, automatic resume, and a support-escalation path. None of this
blocks a *single pilot* deploy; all of it blocks *20k unattended* deploys.

## What remains to prove

- **Idempotency at the exact final head:** the branch already has a UK South
  unchanged idempotency proof (`30000311095`) and current-head green one-click
  proof (`30034540034`). A strict unchanged rerun at `f9fc7bb` would make the
  final-head idempotency evidence symmetrical.
- **Bar 3 (calibration):** implement runtime confidence calibration and flip
  `confidence_calibrated` to `true` with evidence; this is repository work, not a
  deploy.

## Revision notes (2026-07-23)

This document was revised the same day it was written after an independent review
caught places where it claimed more than the evidence supported. Corrections:

- Split the single "grounded + calibrated, external" bar into **grounded
  retrieval** (externally gated) and **calibrated confidence** (unbuilt code we
  own) — the earlier "the only unproven bar is external" was wrong.
- Qualified Bar 1 before the final rerun: the earlier green runs were an earlier
  revision and acceptance was initially only a structural smoke test. Current-head
  run `30034540034` supersedes that caveat by proving the KB retrieval evidence
  gate as well.
- Reframed the Sweden root cause as a **strongly localized, well-evidenced
  hypothesis** (with the 2×2 that controls for creation flow) rather than a
  confirmed Microsoft-side defect; a support case is still needed to confirm the
  mechanism.
- Named the **region-preflight catch-22**: the selector routes one-click deploys
  into the currently-failing region, so today a fresh-account one-click is
  *expected to fail*, not merely unproven.
- Narrowed the `rg-waypoint` claim to a **topology/feature existence proof**, not
  proof of this branch's fresh-account one-click path.
- Added the **fleet-scale viability** section for the 20k-seller goal.
- (Separately) fixed a stale deploy-timeout unit test that the timeout change had
  left red.
- Added the UK South structural/idempotency proof, identified the KB-specific
  `gpt-5.5` answer-synthesis mismatch, and documented the fix to use
  Forge-compatible `gpt-5-mini` for `contracts-kb`.
- Added the current-head UK South green proof (`30034540034`) and clarified that
  customer-visible trace rows can be absent even when recorder-preserved runtime
  evidence carries retrieved `ref_id` citations.
