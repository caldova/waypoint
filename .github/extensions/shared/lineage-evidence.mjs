// Shared quality-evidence lineage loader for the optimizer/RFT canvases.
//
// This module never fetches, applies, or promotes anything. It only reads
// the committed reference-lineage evidence produced by
// `caliber lineage snapshot` / `caliber lineage report`
// (see modules/evals/src/caliber/lineage.py) so canvases can badge their
// metrics as `current`, `stale`, `reference_only`, or `unverifiable` instead
// of presenting unqualified embedded numbers.
//
// Kept identical in two places in this repo (both must be edited together):
//   - modules/optimization/extensions/shared/lineage-evidence.mjs (source)
//   - .github/extensions/shared/lineage-evidence.mjs (loaded at runtime)

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

/** Lineage statuses a canvas may report. Mirrors caliber.lineage.VERIFY_STATUSES. */
export const LINEAGE_STATUSES = Object.freeze(["current", "stale", "reference_only", "unverifiable"]);

/**
 * Walk up from `startDir` looking for the monorepo root, identified by
 * having both `modules/evals` and `modules/optimization` as children. Both
 * duplicate extension trees (`.github/extensions/*` and
 * `modules/optimization/extensions/*`) sit at different depths, so this
 * cannot assume a fixed number of `..` segments.
 */
export function findRepoRoot(startDir, maxDepth = 12) {
    let dir = startDir;
    for (let i = 0; i < maxDepth; i += 1) {
        if (existsSync(join(dir, "modules", "evals")) && existsSync(join(dir, "modules", "optimization"))) {
            return dir;
        }
        const parent = dirname(dir);
        if (parent === dir) {
            return null;
        }
        dir = parent;
    }
    return null;
}

/** Path to the committed reference-lineage evidence file for an agent. */
export function referenceLineagePath(repoRoot, agent) {
    return join(repoRoot, "modules", "optimization", "evidence", agent, "reference-lineage.json");
}

/**
 * Load the committed reference-lineage evidence for an agent. Returns
 * `null` if the repo root can't be found or the file doesn't exist/parse,
 * so canvases can fall back to an `unverifiable` badge rather than throwing.
 */
export function loadReferenceLineage(repoRoot, agent) {
    if (!repoRoot) {
        return null;
    }
    const path = referenceLineagePath(repoRoot, agent);
    if (!existsSync(path)) {
        return null;
    }
    try {
        const data = JSON.parse(readFileSync(path, "utf8"));
        const snapshots = Array.isArray(data?.snapshots) ? data.snapshots : Array.isArray(data) ? data : [];
        return { path, snapshots };
    } catch {
        return null;
    }
}

/** Find a snapshot in loaded reference-lineage evidence by operation id. */
export function findSnapshotByOperationId(reference, operationId) {
    if (!reference || !Array.isArray(reference.snapshots)) {
        return null;
    }
    return reference.snapshots.find((snapshot) => snapshot.operation_id === operationId) ?? null;
}

/** sha256 hex digest of a file's bytes, or null if it doesn't exist. */
export function sha256File(path) {
    if (!path || !existsSync(path)) {
        return null;
    }
    return createHash("sha256").update(readFileSync(path)).digest("hex");
}

/**
 * Compare a snapshot's stored hash for one component against a freshly
 * computed hash. Returns `null` (unverifiable) when either side is missing,
 * otherwise a boolean match result.
 */
export function verifyHashComponent(snapshot, componentKey, currentSha256) {
    const stored = snapshot?.hashes?.[componentKey]?.sha256 ?? null;
    if (!stored || !currentSha256) {
        return null;
    }
    return stored === currentSha256;
}

/**
 * Classify overall lineage status from a snapshot and a list of per-component
 * match results (booleans, or null for unverifiable components). Mirrors the
 * semantics of `caliber.lineage.verify_snapshot`:
 *   - `reference_only` always wins: a reference snapshot's raw sources are
 *     gone, so it can never be reported as fresh, only historically anchored.
 *   - `unverifiable` when nothing could be compared.
 *   - `current` when every compared component matched.
 *   - `stale` when at least one compared component did not match.
 */
export function classifyLineageStatus(snapshot, matches) {
    if (!snapshot) {
        return "unverifiable";
    }
    if (snapshot.reference_only) {
        return "reference_only";
    }
    const supplied = matches.filter((match) => match !== null && match !== undefined);
    if (supplied.length === 0) {
        return "unverifiable";
    }
    return supplied.every(Boolean) ? "current" : "stale";
}

const BADGE_STYLE = Object.freeze({
    current: { label: "Lineage: current", color: "#1a7f37" },
    reference_only: { label: "Lineage: reference-only", color: "#0969da" },
    stale: { label: "Lineage: stale", color: "#cf222e" },
    unverifiable: { label: "Lineage: unverifiable", color: "#9a6700" },
});

/** Human label + accent color for a lineage status. */
export function lineageBadge(status) {
    return BADGE_STYLE[status] ?? BADGE_STYLE.unverifiable;
}

/** Small inline-styled HTML pill for a lineage status, safe to embed directly. */
export function lineageBadgeHtml(status, extraLabel) {
    const badge = lineageBadge(status);
    const label = extraLabel ? `${badge.label} \u2014 ${extraLabel}` : badge.label;
    return (
        `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 9px;` +
        `border-radius:999px;border:1px solid ${badge.color};color:${badge.color};` +
        `font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;">` +
        `${label}</span>`
    );
}

/**
 * Convenience: given an extension directory (`import.meta.url` derived) and
 * an agent + operation id, load evidence, find the matching snapshot, and
 * verify one hash component against a current file. Returns a structured
 * result a canvas can badge and surface directly. Never throws; missing
 * evidence degrades to `unverifiable`.
 */
export function resolveLineageStatus({ extensionDir, agent, operationId, componentKey, currentFilePath }) {
    const repoRoot = findRepoRoot(extensionDir);
    const reference = loadReferenceLineage(repoRoot, agent);
    const snapshot = findSnapshotByOperationId(reference, operationId);
    const currentSha256 = componentKey && currentFilePath ? sha256File(currentFilePath) : null;
    const matches = componentKey && snapshot ? [verifyHashComponent(snapshot, componentKey, currentSha256)] : [];
    const status = classifyLineageStatus(snapshot, matches);
    return {
        status,
        repoRoot,
        referencePath: reference?.path ?? null,
        snapshotId: snapshot?.snapshot_id ?? null,
        reviewStatus: snapshot?.review_status ?? null,
        hashIntegrity: matches.length > 0 ? matches[0] : null,
        badge: lineageBadge(status),
    };
}
