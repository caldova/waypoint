# Agent quality operations

Waypoint separates live invoice assurance from agent quality and optimization
controls:

- **Invoices** starts one or many invoice-scoped assurance runs through the
  deployed `waypoint-agent`.
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
| Concurrency | At most four new runs start at once |
| Deduplication | Duplicate request IDs are removed; active invoice runs are reused |
| Ordering | Results follow first-seen input order |
| Isolation | A missing or failed invoice does not roll back accepted invoices |
| Outcomes | `accepted`, `reused`, `not_found`, or `start_failed` |
| Writer | the agent's single governed writer is the sole write path |

The header checkbox selects **visible** invoices. Filters therefore provide a
safe way to run a smaller cohort.

## Follow the controlled quality loop

Open the authenticated **Quality** page at `/quality`. Its numbered flow aligns
with the castia quality loop against `waypoint-agent`:

| Step | Purpose | Tooling |
| --- | --- | --- |
| 1. Run assurance | Generate live governed evidence from an invoice. | Waypoint app |
| 2. Inspect the run | Review the correlated trace and evidence. | Waypoint app / Foundry traces |
| 3. Measure quality | Score responses against datasets and graders. | `castia eval` (`modules/evals`) |
| 4. Improve the agent | Search prompt/config candidates and prepare RFT. | `castia optimize` (`modules/optimization`) |
| 5. Release with approval | Keep spend-incurring training behind reviewed, fail-closed gates. | Reviewed promotion |

No step auto-applies an optimizer candidate, promotes a model, or deploys the
agent. Spend-incurring RFT submission stays behind an explicit, reviewed
decision. Cloud credentials and evidence artifacts stay outside the browser.

