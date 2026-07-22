# Optimization

This module contains the improvement and promotion assets for measured Waypoint
agents.

The supported quality path is:

1. **Run** governed invoice assurance.
2. **Inspect** correlated, sanitized trace evidence.
3. **Measure** with Foundry-native evaluation plus Caliber datasets, graders,
   and calibration.
4. **Improve** with Foundry Agent Optimizer and reviewed RFT/RLE preparation.
5. **Release with approval** only after current lineage and every protected gate
   passes.

The operator surface for this loop is documented in
[`../../docs/quality-operations.md`](../../docs/quality-operations.md) and
implemented by `.github/workflows/agent-quality-operations.yml`.

The current target is `contract-policy-expert`. Historical
`assurance-analyst` artifacts remain only as calibration provenance.

| Path | Purpose |
| --- | --- |
| `docs/TUNE.md` | Operator tuning guidance. |
| `docs/CONTRACT_POLICY_EXPERT_RFT_ARTIFACTS.md` | Contract expert RFT inputs and outputs. |
| `docs/FOUNDRY_TRACES_AND_FINE_TUNING.md` | Trace-to-evaluation-to-optimization flywheel. |
| `extensions/optimizer-diff-canvas` | Baseline and candidate comparison. |
| `extensions/rft-cost-quality-canvas` | Cost-quality exploration. |
| `extensions/caldova-rft-process` | Business-facing RFT process walkthrough. |

## Quality-evidence lineage

- `evidence/contract-policy-expert/reference-lineage.json` contains committed,
  schema-conformant, `reference_only` lineage snapshots for the historical Agent
  Optimizer and RFT runs described in
  `docs/CONTRACT_POLICY_EXPERT_RFT_ARTIFACTS.md`. See
  `../evals/docs/QUALITY_LINEAGE.md` for the lineage and gate contract.
- `extensions/shared/lineage-evidence.mjs` provides the shared lineage loader,
  classifier, and badge renderer used by both optimization canvases. Surfaced
  metrics carry an explicit `current`, `stale`, or `reference-only` status.

Plans, generated datasets, optimizer candidates, and RFT packages are not proof
of a deployed promotion. Keep generated run output and deployment-specific IDs
out of git.

P2M is retired.
