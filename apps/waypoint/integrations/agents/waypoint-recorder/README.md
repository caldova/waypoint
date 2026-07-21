# Waypoint Recorder integration

`waypoint-recorder` is the sole hosted agent authorized to write governed
invoice-assurance results to Waypoint.

This directory retains app-side integration assets. The canonical hosted source
is
[`modules/agents/agents/waypoint-recorder`](../../../../../modules/agents/agents/waypoint-recorder/README.md).

The recorder receives the orchestrator's final write plan, validates the
payload, creates or updates the governed result, preserves correlation IDs, and
finalizes the run. Evidence experts, `invoice-analyst`, and
`assurance-orchestrator` do not bypass this boundary.

Writer credentials are supplied by deployment and must never be committed.
