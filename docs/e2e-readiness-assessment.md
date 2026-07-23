# End-to-end deployment readiness assessment

**Assessment date:** 2026-07-23 (01:48 PT, `2026-07-23T01:48-07:00`)
**Revised:** 2026-07-23 (01:56 PT, `2026-07-23T01:56-07:00`) after an independent
review — corrected over-claims (see [Revision notes](#revision-notes-2026-07-23)).
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
| **1. Deploy-green (structural)** | infra + app + agents + seed + acceptance all pass | **Proven on an earlier revision** in the East US 2 / North Europe split-region topology; **not** re-validated on current HEAD, and acceptance passes on `partial`/fallback (it is a runtime smoke test, not a grounding test) |
| **2. Grounded KB retrieval** | a real `knowledge_base_retrieve` call with returned clause citations, not `Fallback retrieval` | **Proven out of band** (keynote `rg-waypoint`, pre-existing co-located account); **unproven from a one-click deploy** on a fresh account; gated on **external** region health |
| **3. Calibrated confidence** | displayed decision confidence is a calibrated probability, not a raw evidence score | **Not implemented** — the recorder writes `confidence_calibrated: false` today; this is **repository work remaining (Phase 6)**, not an external blocker |

The earlier version of this document folded bars 2 and 3 together and called the
whole thing "external." That was wrong: **grounded retrieval** is externally
gated, but **calibration** is unbuilt code we own. Bar 1's "proven" is real but
belongs to an earlier revision and a weaker (structural) definition of success.

## Point 1 — Deploy-green (structural): proven on an earlier revision

An earlier revision of this branch completed a full clean deployment, a
convergence rerun, and a strict unchanged idempotency rerun, plus a later
runtime-evidence-correction deploy — all acceptance-green, with four active
hosted agents, one analyst Bot Service, a terminal correlated
orchestrator-to-recorder run, and preserved agent versions on rerun.

Two honest qualifiers keep this from being read as more than it is:

- **It was a different topology and an earlier revision.** Those green runs used
  the East US 2 (Foundry) + North Europe (app/Search) **split-region** topology
  and predate the region+capacity preflight and the cold-deploy timeout change.
  Current HEAD has **not** been re-run to green, and its preflight now selects a
  single co-located region (see Point 2), so the exact behavior that was proven is
  not the behavior the branch would exhibit today.
- **"Deploy-green" is a structural smoke test, not a grounding test.** Acceptance
  treats a `partial` terminal run as success and does **not** fail when the
  contract expert falls back instead of calling the KB
  ([KB upload does not prove KB retrieval](deployment-troubleshooting.md#kb-upload-does-not-prove-kb-retrieval)).
  So a green Bar 1 proves the infra/app/agent/seed/lifecycle plumbing works end to
  end; it does **not** prove contract-grounded retrieval or calibrated confidence.

- **Why we believe the plumbing:** see
  [Validation record](deployment-troubleshooting.md#validation-record) for the
  exact GitHub Actions run IDs and the validated environment.
- **Change delta since those runs:** the region+capacity preflight and the
  Aspire cold-deploy timeout increase. These are additive to the agent/infra/
  acceptance **contracts**, but the preflight materially changes **region
  selection**, which is exactly the Point 2 problem — so "low-risk" applies to the
  contracts, not to whether a one-click run reaches green today.

**Conclusion:** the structural pipeline is proven to reach green in a
provisioning-healthy region; that result is real but is (a) from an earlier
revision/topology and (b) a smoke-test-level definition of success.

## Point 2 — Grounded KB retrieval: proven out of band, unproven one-click

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

What is unproven is specific: **reaching that grounded single-region state from a
one-click deploy of this repository on a freshly-created Foundry account.** It is
blocked by a region catch-22 in external platform state:

- **East US 2** provisions hosted agents, but lacks Azure AI Search `basic`
  capacity, so the knowledge base runs cross-region and the contract expert
  silently falls back. Evidence:
  [Search capacity exhaustion and cross-region KB retrieval failure](deployment-troubleshooting.md#search-capacity-exhaustion-and-cross-region-kb-retrieval-failure)
  and
  [KB upload does not prove KB retrieval](deployment-troubleshooting.md#kb-upload-does-not-prove-kb-retrieval).
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

### The region-preflight catch-22 (a real gap to name)

The branch's region selector
(`tools/deploy/scripts/region_capacity_preflight.py`) chooses a region from a
**static** "supports Hosted Agents + Content Understanding GA" allow-list, then
scores it on model availability, quota, and a Search `basic` PUT/DELETE probe. It
does **not** — and today cannot — test fresh-account hosted-agent *provisioning
health*. Consequence: it will deterministically prefer **Sweden Central** (the
co-located Search winner) — the exact region where fresh-account provisioning
currently fails. **So a one-click run today would be steered into the blocked
region and fail at the agent-deploy stage.** This is not merely "unproven"; under
current conditions it is *expected to fail*.

By explicit decision we are **not** adding a hosted-agent provisioning probe to
the preflight right now. But the contradiction must be named: the preflight
optimizes for KB co-location and is silent on the one failure mode that is
actually blocking us, so its "Sweden Central selected" output should not be read
as "Sweden Central will succeed."

**Conclusion:** absent the external provisioning fault, the co-located
single-region grounded path *should* work — the capability is proven and the
region evidence is strong. But it is genuinely unproven for this branch's
one-click fresh-account flow, and today's preflight would actively route that flow
into the currently-failing region.

## Point 3 — Calibrated confidence: not yet implemented (our code)

This is the correction the previous version got wrong by bundling it into "Point
2, external." Displayed decision confidence is **not** a calibrated probability
today: the recorder writes `confidence_calibrated: false`
(`modules/agents/agents/waypoint-recorder/waypoint_write_tools.py`), and the
product deliberately labels these scores as uncalibrated rather than presenting
them as decision confidence. Turning raw evidence scores into a calibrated
probability is **Phase 6 repository work that does not exist yet** — it is not
gated on any Azure region. Any "grounded *and* calibrated demo" bar therefore
cannot be met by simply fixing provisioning; it also needs this code written.

## Residual risks

See
[Platform and environmental blockers encountered](deployment-troubleshooting.md#platform-and-environmental-blockers-encountered)
for the full catalog with class and mitigation. The load-bearing ones for E2E
readiness — note that not all are external:

- **Region must satisfy both constraints at once (external)** — Search `basic`
  capacity **and** healthy new-account hosted-agent provisioning. No single region
  has satisfied both for a **fresh, one-click** account to date (a pre-existing
  co-located account such as the keynote `rg-waypoint` already satisfies both).
- **Preflight steers into the blocked region (our code, by omission)** — the
  region selector optimizes for co-located Search and is blind to fresh-account
  provisioning health, so it selects Sweden Central, which currently fails. We are
  intentionally not adding a provisioning probe yet, so this remains a known,
  unmitigated routing gap.
- **Calibration is unbuilt (our code)** — Bar 3 above; not an external blocker.
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

## What would move each bar to "proven"

- **Bar 1 (structural), current HEAD:** re-run the clean + unchanged pipeline to
  green on this HEAD (the earlier proof was a prior revision/topology).
- **Bar 2 (grounded retrieval):** one clean **one-click** run on a
  **freshly-created** account in a co-located, provisioning-healthy region that
  reaches acceptance **and** shows a real `knowledge_base_retrieve` call with
  returned clause citations (not `Fallback retrieval`). A fail-on-fallback
  acceptance assertion (Phase 6.1) would make this self-proving instead of
  requiring manual trace inspection.
- **Bar 3 (calibration):** implement runtime confidence calibration and flip
  `confidence_calibrated` to `true` with evidence; this is repository work, not a
  deploy.

## Revision notes (2026-07-23)

This document was revised the same day it was written after an independent review
caught places where it claimed more than the evidence supported. Corrections:

- Split the single "grounded + calibrated, external" bar into **grounded
  retrieval** (externally gated) and **calibrated confidence** (unbuilt code we
  own) — the earlier "the only unproven bar is external" was wrong.
- Qualified Bar 1: the green runs were an **earlier revision** in the split-region
  topology, and acceptance is a **structural smoke test** that passes on
  `partial`/fallback — not proof of grounding.
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
