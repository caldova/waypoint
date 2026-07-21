import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { domainId, loadEntry, saveEntry, stateFilePath } from "./state.mjs";

const SAMPLE_CONFIG = {
    subscriptionId: "11111111-1111-1111-1111-111111111111",
    tenantId: "22222222-2222-2222-2222-222222222222",
    region: "swedencentral",
    targetRepo: "caldova/waypoint",
};

test("stateFilePath prefers workspacePath when provided", () => {
    const p = stateFilePath("/tmp/some-workspace");
    assert.equal(p, path.join("/tmp/some-workspace", "waypoint-setup-deploy-state.json"));
});

test("stateFilePath falls back to a repo-independent per-user location when workspacePath is missing", () => {
    for (const missing of [undefined, null, "", "   "]) {
        const p = stateFilePath(missing);
        assert.ok(p.includes(path.join("extensions", "waypoint-setup-deploy", "artifacts")));
        assert.ok(!p.startsWith(process.cwd()), "must not fall back into the repo checkout");
    }
});

test("domainId is deterministic for identical config", () => {
    const a = domainId(SAMPLE_CONFIG);
    const b = domainId({ ...SAMPLE_CONFIG });
    assert.equal(a, b);
    assert.match(a, /^[0-9a-f]{16}$/);
});

test("domainId is case- and whitespace-insensitive on inputs", () => {
    const a = domainId(SAMPLE_CONFIG);
    const b = domainId({
        subscriptionId: ` ${SAMPLE_CONFIG.subscriptionId.toUpperCase()} `,
        tenantId: SAMPLE_CONFIG.tenantId.toUpperCase(),
        region: SAMPLE_CONFIG.region.toUpperCase(),
        targetRepo: SAMPLE_CONFIG.targetRepo.toUpperCase(),
    });
    assert.equal(a, b);
});

test("domainId differs when any single field differs", () => {
    const base = domainId(SAMPLE_CONFIG);
    const variants = [
        { ...SAMPLE_CONFIG, subscriptionId: "99999999-9999-9999-9999-999999999999" },
        { ...SAMPLE_CONFIG, tenantId: "99999999-9999-9999-9999-999999999999" },
        { ...SAMPLE_CONFIG, region: "eastus" },
        { ...SAMPLE_CONFIG, targetRepo: "caldova/other" },
    ];
    for (const variant of variants) {
        assert.notEqual(domainId(variant), base);
    }
});

test("loadEntry returns a fresh empty shape for an unknown id, never throws", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wsd-state-"));
    const file = path.join(dir, "state.json");
    try {
        const entry = loadEntry(file, "does-not-exist");
        assert.deepEqual(entry, {
            config: null,
            names: null,
            preflight: null,
            bootstrap: null,
            deploy: null,
            links: null,
            updatedAt: null,
        });
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});

test("loadEntry tolerates a missing or corrupt state file", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wsd-state-"));
    const file = path.join(dir, "missing.json");
    try {
        assert.doesNotThrow(() => loadEntry(file, "abc"));

        fs.writeFileSync(file, "{ not json", "utf8");
        assert.doesNotThrow(() => loadEntry(file, "abc"));
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});

test("saveEntry persists and round-trips through loadEntry, keyed by domain id", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wsd-state-"));
    const file = path.join(dir, "state.json");
    try {
        const id = domainId(SAMPLE_CONFIG);
        const saved = saveEntry(file, id, { config: SAMPLE_CONFIG });
        assert.equal(saved.config.targetRepo, "caldova/waypoint");
        assert.ok(saved.updatedAt);

        const reloaded = loadEntry(file, id);
        assert.deepEqual(reloaded.config, SAMPLE_CONFIG);
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});

test("saveEntry merges patches instead of clobbering unrelated fields", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wsd-state-"));
    const file = path.join(dir, "state.json");
    try {
        const id = domainId(SAMPLE_CONFIG);
        saveEntry(file, id, { config: SAMPLE_CONFIG });
        saveEntry(file, id, { preflight: { overall: "pass" } });
        const entry = loadEntry(file, id);
        assert.deepEqual(entry.config, SAMPLE_CONFIG);
        assert.deepEqual(entry.preflight, { overall: "pass" });
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});

test("saveEntry keeps separate domain ids fully isolated", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wsd-state-"));
    const file = path.join(dir, "state.json");
    try {
        const idA = domainId(SAMPLE_CONFIG);
        const idB = domainId({ ...SAMPLE_CONFIG, targetRepo: "caldova/other" });
        saveEntry(file, idA, { config: SAMPLE_CONFIG });
        saveEntry(file, idB, { config: { ...SAMPLE_CONFIG, targetRepo: "caldova/other" } });

        assert.equal(loadEntry(file, idA).config.targetRepo, "caldova/waypoint");
        assert.equal(loadEntry(file, idB).config.targetRepo, "caldova/other");
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});
