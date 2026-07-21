import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
    classifyLineageStatus,
    findRepoRoot,
    findSnapshotByOperationId,
    lineageBadge,
    lineageBadgeHtml,
    loadReferenceLineage,
    referenceLineagePath,
    resolveLineageStatus,
    sha256File,
    verifyHashComponent,
} from "./lineage-evidence.mjs";

function makeFakeRepo() {
    const root = mkdtempSync(join(tmpdir(), "lineage-evidence-test-"));
    mkdirSync(join(root, "modules", "evals"), { recursive: true });
    mkdirSync(join(root, "modules", "optimization", "evidence", "some-agent"), { recursive: true });
    return root;
}

test("findRepoRoot walks up until it finds modules/evals + modules/optimization", () => {
    const root = makeFakeRepo();
    try {
        const nested = join(root, "modules", "optimization", "extensions", "some-canvas");
        mkdirSync(nested, { recursive: true });
        assert.equal(findRepoRoot(nested), root);
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("findRepoRoot returns null when no marker directories exist", () => {
    const isolated = mkdtempSync(join(tmpdir(), "lineage-evidence-nomatch-"));
    try {
        assert.equal(findRepoRoot(isolated), null);
    } finally {
        rmSync(isolated, { recursive: true, force: true });
    }
});

test("loadReferenceLineage returns null when the evidence file is missing", () => {
    const root = makeFakeRepo();
    try {
        assert.equal(loadReferenceLineage(root, "some-agent"), null);
        assert.equal(loadReferenceLineage(null, "some-agent"), null);
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("loadReferenceLineage parses a committed reference-lineage.json and finds snapshots by operation id", () => {
    const root = makeFakeRepo();
    try {
        const path = referenceLineagePath(root, "some-agent");
        const payload = {
            agent: "some-agent",
            snapshots: [
                { operation_id: "op-a", reference_only: true, snapshot_id: "abc" },
                { operation_id: "op-b", reference_only: true, snapshot_id: "def" },
            ],
        };
        writeFileSync(path, JSON.stringify(payload));

        const reference = loadReferenceLineage(root, "some-agent");
        assert.equal(reference.snapshots.length, 2);

        const found = findSnapshotByOperationId(reference, "op-b");
        assert.equal(found.snapshot_id, "def");
        assert.equal(findSnapshotByOperationId(reference, "missing"), null);
        assert.equal(findSnapshotByOperationId(null, "op-b"), null);
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("loadReferenceLineage tolerates invalid JSON by returning null", () => {
    const root = makeFakeRepo();
    try {
        writeFileSync(referenceLineagePath(root, "some-agent"), "{not valid json");
        assert.equal(loadReferenceLineage(root, "some-agent"), null);
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("sha256File hashes real bytes and returns null for missing files", () => {
    const root = makeFakeRepo();
    try {
        const filePath = join(root, "sample.txt");
        writeFileSync(filePath, "hello lineage");
        const digest = sha256File(filePath);
        assert.equal(digest.length, 64);
        assert.equal(sha256File(join(root, "does-not-exist.txt")), null);
        assert.equal(sha256File(null), null);
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("verifyHashComponent compares stored vs current hash, unverifiable when either side is missing", () => {
    const snapshot = { hashes: { prompt_config: { sha256: "abc123" } } };
    assert.equal(verifyHashComponent(snapshot, "prompt_config", "abc123"), true);
    assert.equal(verifyHashComponent(snapshot, "prompt_config", "different"), false);
    assert.equal(verifyHashComponent(snapshot, "prompt_config", null), null);
    assert.equal(verifyHashComponent(snapshot, "dataset", "abc123"), null);
    assert.equal(verifyHashComponent(null, "prompt_config", "abc123"), null);
});

test("classifyLineageStatus always reports reference_only for reference snapshots, regardless of hash matches", () => {
    const referenceSnapshot = { reference_only: true };
    assert.equal(classifyLineageStatus(referenceSnapshot, [true, true]), "reference_only");
    assert.equal(classifyLineageStatus(referenceSnapshot, [false]), "reference_only");
    assert.equal(classifyLineageStatus(referenceSnapshot, []), "reference_only");
});

test("classifyLineageStatus reports unverifiable, current, and stale for live snapshots", () => {
    const liveSnapshot = { reference_only: false };
    assert.equal(classifyLineageStatus(liveSnapshot, []), "unverifiable");
    assert.equal(classifyLineageStatus(liveSnapshot, [null, null]), "unverifiable");
    assert.equal(classifyLineageStatus(liveSnapshot, [true, true]), "current");
    assert.equal(classifyLineageStatus(liveSnapshot, [true, false]), "stale");
    assert.equal(classifyLineageStatus(null, [true]), "unverifiable");
});

test("lineageBadge and lineageBadgeHtml cover every known status and fall back safely", () => {
    for (const status of ["current", "stale", "reference_only", "unverifiable", "not-a-real-status"]) {
        const badge = lineageBadge(status);
        assert.ok(badge.label);
        assert.ok(badge.color);
        const html = lineageBadgeHtml(status);
        assert.match(html, /<span/);
        assert.match(html, new RegExp(badge.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    }
});

test("lineageBadgeHtml appends an extra label when provided", () => {
    const html = lineageBadgeHtml("current", "hash verified");
    assert.match(html, /hash verified/);
});

test("resolveLineageStatus end-to-end: reference snapshot resolves and hash integrity is reported", () => {
    const root = makeFakeRepo();
    try {
        const extDir = join(root, "modules", "optimization", "extensions", "some-canvas");
        mkdirSync(extDir, { recursive: true });
        const fixturePath = join(extDir, "config.json");
        writeFileSync(fixturePath, JSON.stringify({ hello: "world" }));
        const digest = sha256File(fixturePath);

        writeFileSync(
            referenceLineagePath(root, "some-agent"),
            JSON.stringify({
                snapshots: [
                    {
                        operation_id: "op-a",
                        reference_only: true,
                        snapshot_id: "abc",
                        review_status: "accepted",
                        hashes: { prompt_config: { sha256: digest } },
                    },
                ],
            }),
        );

        const result = resolveLineageStatus({
            extensionDir: extDir,
            agent: "some-agent",
            operationId: "op-a",
            componentKey: "prompt_config",
            currentFilePath: fixturePath,
        });

        assert.equal(result.status, "reference_only");
        assert.equal(result.snapshotId, "abc");
        assert.equal(result.reviewStatus, "accepted");
        assert.equal(result.hashIntegrity, true);
        assert.equal(result.badge.label, "Lineage: reference-only");
    } finally {
        rmSync(root, { recursive: true, force: true });
    }
});

test("resolveLineageStatus degrades to unverifiable when no repo root or evidence is found", () => {
    const isolated = mkdtempSync(join(tmpdir(), "lineage-evidence-isolated-"));
    try {
        const result = resolveLineageStatus({
            extensionDir: isolated,
            agent: "some-agent",
            operationId: "op-a",
        });
        assert.equal(result.status, "unverifiable");
        assert.equal(result.snapshotId, null);
        assert.equal(result.hashIntegrity, null);
    } finally {
        rmSync(isolated, { recursive: true, force: true });
    }
});
