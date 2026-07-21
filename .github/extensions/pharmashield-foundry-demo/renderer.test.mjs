import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { renderHtml } from "./renderer.mjs";

test("renders the Foundry contract expert structure", () => {
    const html = renderHtml();

    for (const label of [
        "Anatomy of an agent",
        "Model",
        "Instructions",
        "Context",
        "Memory",
        "Tools",
        "Chat",
        "Trace",
        "Connection",
    ]) {
        assert.match(html, new RegExp(`>${label}<|${label}`));
    }
});

test("names the model and excludes the retired two-part narrative", () => {
    const html = renderHtml();

    assert.match(html, /gpt-5\.5/);
    assert.match(html, /id="anatomy-model"/);
    assert.match(html, /model = "<span id="code-model">gpt-5\.5<\/span>"/);
    assert.match(html, /FoundryChatClient/);
    assert.match(html, /Keeping model choice explicit|model choice is explicit/i);
    for (const phrase of [
        /Part 1/i,
        /Part 2/i,
        /local proof/i,
        /same invoice/i,
        /carried forward/i,
        /proof of concept/i,
        /laptop runtime/i,
    ]) {
        assert.doesNotMatch(html, phrase);
    }
});

test("follows the host app theme with complete explicit palettes", () => {
    const html = renderHtml();

    assert.match(html, /data-visual-mode/);
    assert.match(html, /data-color-mode/);
    assert.match(html, /data-theme/);
    assert.match(html, /new MutationObserver\(resolveTheme\)/);
    assert.match(html, /observer\.observe\(document\.body, options\)/);
    assert.match(html, /matchMedia\('\(prefers-color-scheme: light\)'\)/);
    assert.match(html, /:root\[data-theme="light"\]/);
    assert.match(html, /--bg: #0d1117/);
    assert.match(html, /--bg: #f6f8fa/);
    assert.match(html, /--surface: #161b22/);
    assert.match(html, /--surface: #ffffff/);
    assert.match(html, /--text: #e6edf3/);
    assert.match(html, /--text: #1f2328/);
    assert.match(html, /--faint: #656d76/);
    assert.doesNotMatch(
        html,
        /var\(--(?:background-color|overlay-background|border-color|text-color|true-color|color-focus|font-sans|font-mono)/,
    );
    assert.match(html, /@media \(prefers-reduced-motion: reduce\)/);
});

test("renders the canonical chronological Trace sequence from live result fields", () => {
    const html = renderHtml();
    const labels = [
        "Calling Foundry IQ",
        "Query sent to the knowledge base",
        "knowledge_base_retrieve returned",
        "Grounded findings · ",
        "Citations · ",
    ];
    let previous = -1;
    for (const label of labels) {
        const position = html.indexOf(label);
        assert.ok(position > previous, `${label} should follow the previous Trace event`);
        previous = position;
    }

    assert.match(html, /highlightTraceText\(output\)/);
    assert.match(html, /class="trace-highlight"/);
    assert.match(html, /output\.matchAll/);
    assert.match(html, /groundedIds\.add/);
    assert.match(html, /evidenceSourceLabels/);
    assert.match(html, /if \(result\.grounded\)/);
    assert.match(html, /if \(traceOutputFailed\(call\.output, call\.error\)\) continue/);
    assert.match(html, /No source references were returned/);
    assert.doesNotMatch(html, /class="trace-item"/);
});

test("keeps the full governed platform handoff visible", () => {
    const html = renderHtml();

    for (const stage of ["Build", "Deliver", "Evaluate", "Optimize", "Govern"]) {
        assert.match(html, new RegExp(`>${stage}<`));
    }
    assert.match(html, /Waypoint handoff/);
    assert.match(html, /optional Teams reach/);
});

test("does not embed a scripted grounded result", () => {
    const html = renderHtml();

    assert.doesNotMatch(html, /deterministicFoundryAudit/);
    assert.match(html, /Grounding not proven/);
    assert.match(html, /knowledge_base_retrieve required/);
});

test("presents the live result as a seller-readable audit", () => {
    const html = renderHtml();

    assert.match(html, /Foundry audit at a glance/);
    assert.match(html, /What matters/);
    assert.match(html, /Foundry found .* priority findings/);
    assert.match(html, /Questions the evidence could not resolve/);
    assert.match(html, /View all retrieved evidence/);
    assert.match(html, /Confidence /);
    assert.match(html, /source_ref/);
    assert.match(html, /Potential recovery/);
    assert.match(html, /supportRank/);
    assert.match(html, /collectTraceSources\(result, retrievalCalls\(result\), evidence\)\.length/);
    assert.match(html, /sellerClaim/);
    assert.match(html, /potential .* recovery/);
    assert.match(html, /Intl\.NumberFormat/);
    assert.match(html, /Grounded findings · /);
    assert.match(html, /primaryFindings/);
    assert.match(html, /grounded findings/);
});

test("reconciles the listed, effective, and contract rates in the seller claim", () => {
    const { sellerClaim } = canvasLogic();
    const claim = sellerClaim(
        {
            category: { id: "rate" },
            claim: "ALLER-20 uses a USD 0.42 per released tablet contract rate.",
            related: [{ claim: "ALLER-20 uses a USD 0.42 per released tablet contract rate." }],
        },
        [],
    );

    assert.match(claim, /lists \$0\.47 per tablet/);
    assert.match(claim, /\$664,720\.00 line amount implies an effective \$0\.4748 per tablet/);
    assert.match(claim, /contract rate is \$0\.42/);
    assert.match(claim, /prices the line at \$588,000\.00/);
    assert.match(claim, /potential \$76,720\.00 recovery/);
});

test("uses only successful retrieval references in seller and Trace source counts", () => {
    const { collectTraceSources, retrievalCalls } = canvasLogic();
    const result = {
        grounded: true,
        citations: [],
        toolCalls: [
            {
                callId: "successful",
                name: "knowledge_base___knowledge_base_retrieve",
                arguments: '{"query":"pricing"}',
            },
            { callId: "successful", output: "Pricing [ref_id:0] and policy [ref_id:3]" },
            {
                callId: "failed",
                name: "knowledge_base___knowledge_base_retrieve",
                arguments: '{"query":"packaging"}',
            },
            { callId: "failed", output: "Error: Function failed. [ref_id:2]" },
        ],
    };
    const evidence = [
        {
            source_ref:
                "INV-ARB-001-2026-10 L003; Aster Ridge Biomanufacturing Statement of Work, Unit Production Price clause; KB ref_id:0; Invoice Reconciliation Policy, Minimum Evidence for Approval clause; KB ref_id:3",
        },
        { source_ref: "Unretrieved policy, Must not appear; KB ref_id:9" },
    ];

    const sources = collectTraceSources(result, retrievalCalls(result), evidence);
    assert.equal(sources.map((source) => source.id).join(","), "0,3");
    assert.equal(sources[0].title, "Aster Ridge Biomanufacturing Statement of Work");
    assert.equal(sources[0].detail, "Unit Production Price clause");
    assert.equal(sources[1].title, "Invoice Reconciliation Policy");
    assert.equal(sources[1].detail, "Minimum Evidence for Approval clause");
});

test("keeps seller cards to two priority findings while audit metrics can use all findings", () => {
    const { keyFindings, primaryFindings } = canvasLogic();
    const evidence = [
        { claim: "ALLER-20 unit rate", supports: "recover", confidence: 0.98 },
        { claim: "Blister packaging charge", supports: "review", confidence: 0.91 },
        { claim: "Batch release fee", supports: "review", confidence: 0.88 },
    ];

    assert.equal(keyFindings(evidence).length, 3);
    assert.equal(
        primaryFindings(evidence)
            .map((item) => item.category.id)
            .join(","),
        "rate,packaging",
    );
});

function canvasLogic() {
    const html = renderHtml();
    const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
        .map((match) => match[1])
        .find((value) => value.includes("function sellerClaim"));
    assert.ok(script, "canvas script should be present");
    const initialization =
        "document.querySelectorAll('[role=\"tab\"]').forEach((tab) => {\n      tab.addEventListener";
    const prefix = script.slice(0, script.indexOf(initialization));
    const context = {};
    vm.runInNewContext(
        `${prefix}
        globalThis.__canvasLogic = {
            collectTraceSources,
            keyFindings,
            primaryFindings,
            retrievalCalls,
            sellerClaim,
        };`,
        context,
    );
    return context.__canvasLogic;
}
