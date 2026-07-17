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

export const DEMO_BEATS = [
    {
        id: "frame",
        label: "Frame the story",
        talkTrack:
            "We are starting where the local prototype was trying to get: a governed agent in Microsoft Foundry, grounded on approved contract knowledge.",
    },
    {
        id: "inspect",
        label: "Inspect the agent",
        talkTrack:
            "The job is unchanged: check a supplier invoice. The production model and instructions are hosted, and Foundry IQ adds the missing contract context.",
    },
    {
        id: "run",
        label: "Run it live",
        talkTrack:
            "One click sends the Aster Ridge invoice facts to the hosted Contract Policy Expert. The canvas never substitutes a canned answer.",
    },
    {
        id: "prove",
        label: "Prove grounding",
        talkTrack:
            "The trace is the proof: the real knowledge_base_retrieve call, its query, returned contract evidence, and source references.",
    },
    {
        id: "land",
        label: "Land the value",
        talkTrack:
            "The invoice-only math can identify its own inconsistency. Foundry resolves what requires the contract: the rate terms and packaging authorization.",
    },
];

export function buildDemoPrompt(invoiceText) {
    return [
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
