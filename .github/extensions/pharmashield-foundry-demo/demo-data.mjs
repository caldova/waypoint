export const HERO_INVOICE = {
    id: "INV-ARB-001-2026-10",
    supplier: "Aster Ridge Biomanufacturing",
    purchaseOrder: "PO-ARB-001-2026-10",
    total: 1530200,
    currency: "USD",
    source: "assets/invoice-asterridge.txt",
    lines: [
        {
            id: "L001",
            description: "ALLER-10 released tablet production",
            quantity: 1800000,
            unitPrice: 0.42,
            amount: 756000,
        },
        {
            id: "L002",
            description: "ALLER-20 released tablet production",
            quantity: 1400000,
            unitPrice: 0.47,
            amount: 664720,
        },
        {
            id: "L003",
            description: "Batch release administration",
            quantity: 2,
            unitPrice: 4800,
            amount: 9600,
        },
        {
            id: "L004",
            description: "Blister packaging surcharge",
            quantity: 1,
            unitPrice: 99880,
            amount: 99880,
        },
    ],
};

export const CANONICAL_AUDIT_PROMPT =
    "Audit this invoice against our contracts. Flag every discrepancy with the source.";

export const AGENT_ANATOMY = [
    {
        id: "model",
        label: "Model",
        value: "gpt-5.5 · Microsoft Foundry",
        detail: "The selected model is explicit because different agent jobs can use different models.",
    },
    {
        id: "instructions",
        label: "Instructions",
        value: "Contract Policy Expert",
        detail: "The read-only evidence contract keeps the expert focused on grounded contract facts.",
    },
    {
        id: "context",
        label: "Context",
        value: HERO_INVOICE.id,
        detail: "The Aster Ridge invoice supplies the business artifact the expert must audit.",
    },
    {
        id: "memory",
        label: "Memory",
        value: "Conversation thread",
        detail: "Lights when the live audit starts and preserves the hosted response context.",
    },
    {
        id: "tools",
        label: "Tools",
        value: "Foundry IQ · contracts-kb",
        detail: "Foundry IQ provides live knowledge_base_retrieve access to approved contract knowledge.",
    },
];

export const DEMO_BEATS = [
    {
        id: "start",
        label: "Start in GitHub Copilot",
        talkTrack:
            "From GitHub Copilot, we open a live contract-policy expert hosted in Microsoft Foundry.",
    },
    {
        id: "anatomy",
        label: "Name every component",
        talkTrack:
            "This expert uses gpt-5.5. Model choice is explicit so every agent job can use the right model, alongside its instructions, context, memory, and tools.",
    },
    {
        id: "connect",
        label: "Open Connection",
        talkTrack:
            "There are three moves: choose the model, connect approved contract knowledge, and assemble the read-only Contract Policy Expert.",
    },
    {
        id: "audit",
        label: "Run the grounded audit",
        talkTrack:
            "Run the live audit. The invoice supplies the transaction; Foundry IQ retrieves the contract terms needed to evaluate it.",
    },
    {
        id: "trace",
        label: "Prove it in Trace",
        talkTrack:
            "Show the actual knowledge_base_retrieve query, returned clause text, and source references. This is grounding, not model memory.",
    },
    {
        id: "handoff",
        label: "Hand off the chapter",
        talkTrack:
            "The expert returns evidence, not a payment decision. Waypoint governs the workflow; delivery, evaluation, optimization, and fleet governance come next.",
    },
];

export const JOURNEY_STAGES = [
    {
        id: "build",
        label: "Build",
        title: "Ground the expert",
        detail: "Foundry hosted agent + Foundry IQ",
        state: "active",
    },
    {
        id: "deliver",
        label: "Deliver",
        title: "Put evidence into workflow",
        detail: "Waypoint record + optional Teams reach",
        state: "next",
    },
    {
        id: "evaluate",
        label: "Evaluate",
        title: "Measure behavior",
        detail: "Golden cases, graders, and calibration",
        state: "next",
    },
    {
        id: "optimize",
        label: "Optimize",
        title: "Improve cost and quality",
        detail: "Telemetry, prompt tuning, and RFT",
        state: "next",
    },
    {
        id: "govern",
        label: "Govern",
        title: "Operate the workforce",
        detail: "Identity, lifecycle, security, and oversight",
        state: "next",
    },
];

export function buildDemoPrompt(invoiceText) {
    return [
        CANONICAL_AUDIT_PROMPT,
        "Retrieve grounded contract and policy evidence for the supplier invoice below.",
        "You must use the knowledge_base_retrieve MCP tool before answering.",
        "Focus on the contracted ALLER-20 unit-production rate, any volume discount,",
        "the batch-release fee, and whether the blister-packaging surcharge is authorized.",
        "Return the contract-policy-expert JSON evidence contract with stable source_ref citations.",
        "Do not make a final payment decision and do not write to Waypoint.",
        "",
        `Invoice reference: ${HERO_INVOICE.id}`,
        `Supplier: ${HERO_INVOICE.supplier}`,
        "",
        "--- INVOICE ---",
        invoiceText.trim(),
        "--- END INVOICE ---",
    ].join("\n");
}
