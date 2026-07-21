# Invoice Analyst integration

`invoice-analyst` is the default hosted, read-only human-facing agent. It can
answer invoice-assurance and status questions with Waypoint reads and grounded
contract/policy context.

This directory retains app-side integration assets. The canonical hosted source
is
[`modules/agents/agents/invoice-analyst`](../../../../../modules/agents/agents/invoice-analyst/README.md).

The agent serves Foundry Responses and the Microsoft 365 activity protocol. Its
activity surface can render an Adaptive Card, but Microsoft 365 publication and
tenant approval remain separate from the default Azure deployment.

`invoice-analyst` never writes Waypoint records.
