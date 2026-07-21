# Recovery and drift verification

`scripts/verify_recovery_drift.py` proves that a staged deployment can recover
from interruption and converge without duplicate resources. It consumes JSON
evidence only: the tool does not log in to Azure, call GitHub Actions, or mutate
the deployment workflow.

## Snapshot contract

Each sanitized snapshot has this shape:

```json
{
  "schema_version": 1,
  "environment": {
    "name": "waypoint-parity",
    "scope_id": "azure://resourceGroups/rg-waypoint-parity"
  },
  "stages": {
    "app": "success",
    "agents": "failed"
  },
  "inventory": {
    "role_assignments": [],
    "container_apps": [],
    "hosted_agents": [],
    "models": [],
    "fabric_items": [],
    "knowledge_bases": [],
    "seed_sets": []
  }
}
```

Every inventory item must contain an exact `id`, exact `name`, and a `state`
object containing only managed values. Observation timestamps, run IDs, and
other volatile values belong outside `state`. Persist hashes rather than
secret environment values or uploaded content.

The verifier rejects secret-shaped keys and values. Use the sanitizer before
persisting evidence:

```bash
python tools/deploy/scripts/verify_recovery_drift.py sanitize \
  --input parity-baseline.raw.json \
  --output parity-baseline.json
```

Review the sanitized file before storing or sharing it. Sanitization is a
backstop, not permission to capture credentials unnecessarily.

## Recovery proof

Capture three normalized snapshots for the same exact parity resource-group
scope: a known-good baseline, an intentionally interrupted deployment, and the
successful rerun. Then run:

```bash
python tools/deploy/scripts/verify_recovery_drift.py verify \
  --baseline parity-baseline.json \
  --interrupted parity-interrupted.json \
  --rerun parity-rerun.json \
  --scenarios parity-drift-scenarios.json \
  --output parity-recovery-report.json
```

The command exits nonzero unless:

- at least one baseline stage was incomplete in the interrupted snapshot and
  succeeded on rerun;
- the rerun inventory exactly converges on baseline managed state;
- IDs, agents, models, Container Apps, Fabric items, knowledge bases, and seed
  records are duplicate-free; and
- every declared drift scenario is reconciled.

## Controlled drift scenarios

Scenario definitions bind both the exact resource ID and exact resource name.
Names are checked as assertions only; they are never used to discover a target.
The allowed scenario types are:

| Type | Bounded managed state |
| --- | --- |
| `role_assignment_removal` | Restore the exact baseline assignment object. |
| `container_app_env_drift` | Restore one named environment-value hash on one exact app ID. |
| `hosted_agent_tag_hash_drift` | Restore the exact hosted-agent tag/hash. |
| `knowledge_base_content_hash_drift` | Restore the exact knowledge-base content hash. |
| `seed_count_drift` | Restore the exact seed-set record count. |

Preview the deterministic plan against a parity inventory snapshot:

```bash
python tools/deploy/scripts/verify_recovery_drift.py drift \
  --baseline parity-baseline.json \
  --inventory parity-drifted.json \
  --scenarios parity-drift-scenarios.json \
  --mode preview \
  --output parity-drift-plan.json
```

The preview emits a SHA-256 plan digest and an exact confirmation string.
Apply mode is deliberately a hermetic evidence backend: it writes a reconciled
copy and refuses in-place mutation. This rehearses and tests the bounded plan;
it does **not** mutate Azure.

```bash
python tools/deploy/scripts/verify_recovery_drift.py drift \
  --baseline parity-baseline.json \
  --inventory parity-drifted.json \
  --scenarios parity-drift-scenarios.json \
  --mode apply \
  --confirm "$(jq -r .required_confirmation parity-drift-plan.json)" \
  --output parity-reconciled.json
```

Apply refuses if the confirmation differs by one character, the scope changed,
a target ID or name no longer matches, the observed value changed after
planning, or an operation would escape the five allowed resource-bound
reconciliations. No operation deletes a resource.

For a live parity recovery exercise, use the existing staged deployment to
perform the real reconciliation, capture a fresh rerun snapshot, and use the
`verify` command above as the acceptance gate. Do not translate a scenario into
a loose-name Azure deletion command.
