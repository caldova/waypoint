import assert from "node:assert/strict";
import test from "node:test";
import { normalizeConfig, parseRepo, requireConfirmation, ValidationError } from "./validate.mjs";

// ---- parseRepo --------------------------------------------------------------

test("parseRepo splits a valid owner/name repo", () => {
    assert.deepEqual(parseRepo("caldova/waypoint"), { owner: "caldova", repo: "waypoint" });
});

test("parseRepo rejects missing, empty, and malformed repo strings", () => {
    for (const bad of [undefined, null, "", "no-slash", "owner/", "/repo", "a/b/c", "  "]) {
        assert.throws(() => parseRepo(bad), ValidationError);
    }
});

// ---- normalizeConfig ---------------------------------------------------------

const VALID_INPUT = {
    subscriptionId: "  11111111-1111-1111-1111-111111111111  ",
    tenantId: "22222222-2222-2222-2222-222222222222",
    region: " swedencentral ",
    targetRepo: "caldova/waypoint",
};

test("normalizeConfig trims whitespace on every field", () => {
    const config = normalizeConfig(VALID_INPUT);
    assert.deepEqual(config, {
        subscriptionId: "11111111-1111-1111-1111-111111111111",
        tenantId: "22222222-2222-2222-2222-222222222222",
        region: "swedencentral",
        targetRepo: "caldova/waypoint",
    });
});

test("normalizeConfig fails closed when any required field is missing", () => {
    for (const key of ["subscriptionId", "tenantId", "region", "targetRepo"]) {
        const input = { ...VALID_INPUT, [key]: "" };
        assert.throws(() => normalizeConfig(input), ValidationError);
    }
});

test("normalizeConfig fails closed on a completely empty or undefined input", () => {
    assert.throws(() => normalizeConfig({}), ValidationError);
    assert.throws(() => normalizeConfig(undefined), ValidationError);
});

test("normalizeConfig rejects a malformed targetRepo even when the other three fields are valid", () => {
    assert.throws(() => normalizeConfig({ ...VALID_INPUT, targetRepo: "not-a-repo" }), ValidationError);
});

test("normalizeConfig never mutates the input object", () => {
    const input = { ...VALID_INPUT };
    const frozen = Object.freeze({ ...input });
    assert.doesNotThrow(() => normalizeConfig(frozen));
});

// ---- requireConfirmation (no mutation without confirmation) -----------------

test("requireConfirmation accepts only the strict boolean true", () => {
    assert.doesNotThrow(() => requireConfirmation(true, "deploy"));
});

test("requireConfirmation fails closed for every non-true value, including truthy look-alikes", () => {
    for (const value of [false, undefined, null, "true", "yes", 1, {}, [], "TRUE", 0]) {
        assert.throws(() => requireConfirmation(value, "deploy"), ValidationError);
    }
});

test("requireConfirmation error message names the action so failures are traceable", () => {
    assert.throws(() => requireConfirmation(false, "bootstrap"), /bootstrap/);
    assert.throws(() => requireConfirmation(false, "deploy"), /deploy/);
});
