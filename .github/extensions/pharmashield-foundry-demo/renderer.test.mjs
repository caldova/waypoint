import assert from "node:assert/strict";
import test from "node:test";
import { renderHtml } from "./renderer.mjs";

test("renders the canonical Foundry Part 2 structure", () => {
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

test("follows system light and dark appearances", () => {
    const html = renderHtml();

    assert.match(html, /color-scheme: light dark/);
    assert.match(html, /@media \(prefers-color-scheme: dark\)/);
    assert.match(html, /@media \(prefers-reduced-motion: reduce\)/);
});

test("keeps the full Chapter 2 handoff visible", () => {
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
