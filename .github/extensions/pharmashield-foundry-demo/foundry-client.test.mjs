import assert from "node:assert/strict";
import test from "node:test";
import {
    extractHostedResult,
    listHostedAgents,
    rankProject,
    resolveFoundryProject,
} from "./foundry-client.mjs";

test("project ranking prefers Waypoint and the explicit resource group", () => {
    assert.ok(
        rankProject({ name: "account/ai-project-waypoint", resourceGroup: "rg-waypoint" }, "rg-waypoint") >
            rankProject({ name: "account/ai-project-forge", resourceGroup: "rg-forge" }, "rg-waypoint"),
    );
});

test("explicit endpoint avoids an ARM project lookup", async () => {
    const calls = [];
    const az = async (args) => {
        calls.push(args);
        return JSON.stringify([
            {
                id: "/subscriptions/test/resourceGroups/rg-waypoint/providers/Microsoft.CognitiveServices/accounts/a/projects/p",
                name: "a/p",
                resourceGroup: "rg-waypoint",
                location: "swedencentral",
            },
        ]);
    };
    const result = await resolveFoundryProject({
        explicitEndpoint: "https://example.services.ai.azure.com/api/projects/demo/",
        az,
    });

    assert.equal(result.selected.endpoint, "https://example.services.ai.azure.com/api/projects/demo");
    assert.equal(calls.length, 0);
    assert.deepEqual(result.projects, []);
});

test("hosted result is grounded only by a real knowledge base tool call", () => {
    const result = extractHostedResult({
        id: "resp-1",
        status: "completed",
        output: [
            {
                type: "function_call",
                name: "knowledge_base___knowledge_base_retrieve",
                call_id: "call-1",
                arguments: '{"query":"Aster Ridge packaging authorization"}',
            },
            {
                type: "function_call_output",
                call_id: "call-1",
                output: "Section 3.2 requires written authorization.",
            },
            {
                type: "message",
                content: [
                    {
                        type: "output_text",
                        text: JSON.stringify({
                            agent: "contract-policy-expert",
                            plane: "foundryiq",
                            evidence: [
                                {
                                    claim: "Blister packaging requires written authorization.",
                                    source_ref: "Aster Ridge SOW §3.2",
                                },
                            ],
                        }),
                    },
                ],
            },
        ],
    });

    assert.equal(result.grounded, true);
    assert.equal(result.parsedEvidence.evidence[0].source_ref, "Aster Ridge SOW §3.2");
    assert.equal(result.toolCalls.length, 2);
    assert.equal(result.toolCalls[0].callId, "call-1");
});

test("hosted agent inventory supports the Foundry data response shape", async () => {
    const agents = await listHostedAgents({
        projectEndpoint: "https://example.services.ai.azure.com/api/projects/demo",
        token: "test-token",
        fetchImpl: async () =>
            new Response(
                JSON.stringify({
                    data: [
                        { name: "invoice-analyst" },
                        { name: "contract-policy-expert" },
                    ],
                }),
                { status: 200 },
            ),
    });

    assert.deepEqual(agents, ["invoice-analyst", "contract-policy-expert"]);
});

test("citations without a retrieval call do not pass the grounding gate", () => {
    const result = extractHostedResult({
        status: "completed",
        output_text: '{"evidence":[]}',
    });

    assert.equal(result.grounded, false);
});

test("an unrelated hosted function call does not pass the grounding gate", () => {
    const result = extractHostedResult({
        status: "completed",
        output: [
            {
                type: "function_call",
                name: "lookup_invoice",
                call_id: "call-2",
                arguments: '{"invoice_id":"INV-1"}',
            },
        ],
    });

    assert.equal(result.grounded, false);
    assert.equal(result.toolCalls.length, 1);
});

test("tool output text cannot satisfy the grounding gate", () => {
    const result = extractHostedResult({
        status: "completed",
        output: [
            {
                type: "function_call_output",
                call_id: "call-3",
                output: '{"debug":"knowledge_base_retrieve"}',
            },
        ],
    });

    assert.equal(result.grounded, false);
});
