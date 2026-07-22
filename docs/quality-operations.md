# Agent quality operations

Waypoint separates live invoice assurance from agent quality and optimization
controls:

- **Invoices** starts one or many invoice-scoped assurance runs through the
  deployed orchestrator.
- **Quality** explains the controlled improvement loop and links to the reviewed
  GitHub Actions operation that owns cloud credentials, evidence, and approvals.

The browser never stores GitHub or Foundry credentials and never executes a
cloud operation directly.

## Run the full invoice batch

The canonical seed contains 18 invoices, so the complete work queue fits within
the 25-invoice batch limit. The register shows every imported invoice, including
invoices that have not run assurance yet; unreviewed rows do not contribute to
decision, severity, evidence, or recovery metrics.

1. Open **Invoices**.
2. Clear filters if the batch should include every invoice in the register.
3. Select the checkbox in the table header. It selects every visible row.
4. Select **Review batch**.
5. Verify the invoice list and select **Start batch assurance**.
6. Open **Activity** to monitor accepted or reused runs.

Batch assurance uses `POST /api/invoices/assurance-runs/batch` and preserves the
single-invoice lifecycle:

| Contract | Behavior |
| --- | --- |
| Maximum | 25 unique invoice IDs per request |
| Concurrency | At most four new orchestrations start at once |
| Deduplication | Duplicate request IDs are removed; active invoice runs are reused |
| Ordering | Results follow first-seen input order |
| Isolation | A missing or failed invoice does not roll back accepted invoices |
| Outcomes | `accepted`, `reused`, `not_found`, or `start_failed` |
| Writer | `waypoint-recorder` remains the sole governed writer |

The header checkbox selects **visible** invoices. Filters therefore provide a
safe way to run a smaller cohort.

## Follow the controlled quality loop

Open the authenticated **Quality** page at `/quality`. Its numbered flow aligns
the available operations with the end-to-end story:

| Step | Purpose | Workflow options |
| --- | --- | --- |
| 1. Run assurance | Generate live governed evidence from an invoice. | `invoice-run` |
| 2. Inspect the run | Export sanitized metadata for a correlated trace. | `trace-export` |
| 3. Measure quality | Validate quality assets and start a reviewed evaluation. | `quality-status`, `eval-run` |
| 4. Improve the agent | Search candidates and validate an RFT package without applying either. | `optimizer-start`, `rft-prepare` |
| 5. Release with approval | Keep spend-incurring training behind protected, fail-closed gates. | `rft-submit` |

Select **Open agent quality workflow** or an operation's
**Open in GitHub Actions** link. Both open
`.github/workflows/agent-quality-operations.yml`.

## Guardrail meanings

- **Completes in Actions** means the bounded command finishes within the
  workflow job.
- **Starts an asynchronous job** means Actions records the Foundry job identity
  and exits without waiting for the remote job to finish.
- **Requires protected approval** means the operation must pass the
  `quality-rft-submit` environment, spend acknowledgement, current lineage, and
  all other fail-closed gates.
- No operation auto-applies an optimizer candidate, promotes a model, or deploys
  an agent.
- Reference-only lineage is suitable for comparison and display, but it can
  never authorize a governed mutation.

## Workflow availability

GitHub only permits manual dispatch of a new workflow after the workflow file
exists on the repository's default branch. Before that point, the quality page
can explain the operations and link to their source, but live dispatch remains
merge-gated.
