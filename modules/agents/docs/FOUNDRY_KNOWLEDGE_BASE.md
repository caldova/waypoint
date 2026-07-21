# Foundry contracts knowledge base

`contracts-kb` is the default deployment's grounded contract and policy evidence
source for `contract-policy-expert`.

## Ownership

| Monorepo area | Responsibility |
| --- | --- |
| `modules/corpus` | Canonical synthetic contract and policy documents plus upload CLI. |
| `modules/agents` | Foundry project, Search, storage, knowledge-base resources, MCP connection, and hosted expert. |
| Root deployment | Ordered provisioning, corpus upload, reindex, expert wiring, and acceptance. |

No external checkout is required.

## Resources

| Resource | Purpose |
| --- | --- |
| `contracts-kb` | Azure AI Search knowledge base. |
| `contracts-ks` | Blob-backed knowledge source. |
| `contracts-ks-indexer` | Search ingestion and refresh. |
| `kb-mcp-connection` | Foundry RemoteTool connection used by `contract-policy-expert`. |
| `text-embedding-3-large` | Embedding deployment for ingestion. |
| `gpt-5.5` | Default completion deployment for hosted agents and KB synthesis. |

The provisioning path creates or reconciles Search, storage, roles, the
knowledge source, the knowledge base, and the MCP connection. The upload path
syncs the corpus module's current documents and triggers reindexing.

## Root deployment sequence

1. Provision Foundry, Search, storage, and model resources.
2. Initialize `contracts-ks`, `contracts-kb`, and `kb-mcp-connection`.
3. Upload contract and policy content from `modules/corpus`.
4. Remove stale blobs through the corpus sync policy.
5. Trigger the indexer.
6. Deploy and wire `contract-policy-expert`.
7. Run acceptance with FoundryIQ enabled.

FoundryIQ is the only evidence lane enabled by default. A missing knowledge-base
connection fails deployment instead of silently deploying an ungrounded default
expert.

## Standalone maintenance

From `modules/agents`, after selecting the target azd environment:

```bash
az login
azd env select waypoint-agents
make contracts-kb-seed
make contracts-kb-reindex
```

The corpus upload can also be run from the monorepo's corpus module. Resolve
resource coordinates from deployment outputs; do not hardcode account names,
endpoints, or IDs.

## Deletion handling

Blob soft delete and the native blob deletion-detection policy allow a normal
sync and indexer run to remove documents whose source files were renamed or
deleted. The initializer reapplies the policy after knowledge-source updates so
it survives resource reconciliation.

## Validation

A trustworthy FoundryIQ response must include:

- a successful `knowledge_base_retrieve` call
- non-empty retrieved content
- stable source references
- claims supported by those sources
- explicit unresolved questions when the sources are insufficient

The Pharmashield Foundry demo uses the same rule and never substitutes canned
contract evidence.

See the canonical [Azure deployment guide](../../../docs/deployment.md) and
[Foundry demo guide](../../../docs/foundry-demo.md).
