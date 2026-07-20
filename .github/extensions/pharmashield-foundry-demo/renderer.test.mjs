import assert from "node:assert/strict";
import test from "node:test";
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
    assert.match(html, /values\.push\('ref_id:'/);
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
