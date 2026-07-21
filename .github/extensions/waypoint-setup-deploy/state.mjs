// state.mjs — durable, non-secret state for the waypoint-setup-deploy canvas.
//
// State is keyed by a DOMAIN id derived from the setup config (subscription +
// tenant + region + target repo), never by the canvas `instanceId` — the
// instanceId only names a UI panel and is not durable across reloads/restarts.
// The store itself lives under the session workspace when one is available
// (this setup attempt is scoped to "this project session"); it falls back to
// a repo-independent per-user location so the canvas still works if the SDK
// ever omits workspacePath. Nothing written here is a secret: subscription /
// tenant ids, derived resource names, run ids/urls, and check results only.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const STATE_FILE_NAME = "waypoint-setup-deploy-state.json";

function fallbackStateDir() {
    const home = process.env.COPILOT_HOME || path.join(os.homedir(), ".copilot");
    return path.join(home, "extensions", "waypoint-setup-deploy", "artifacts");
}

export function stateFilePath(workspacePath) {
    const dir = workspacePath && String(workspacePath).trim() ? workspacePath : fallbackStateDir();
    return path.join(dir, STATE_FILE_NAME);
}

export function domainId(config) {
    const parts = [config.subscriptionId, config.tenantId, config.region, config.targetRepo]
        .map((v) => String(v || "").trim().toLowerCase());
    return crypto.createHash("sha256").update(parts.join("|")).digest("hex").slice(0, 16);
}

function readAll(filePath) {
    try {
        const text = fs.readFileSync(filePath, "utf8");
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
        return {};
    }
}

function writeAll(filePath, all) {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(all, null, 2), "utf8");
}

/** Load the durable record for one domain id (or a fresh empty shape). */
export function loadEntry(filePath, id) {
    const all = readAll(filePath);
    return (
        all[id] || {
            config: null,
            names: null,
            preflight: null,
            bootstrap: null,
            deploy: null,
            links: null,
            updatedAt: null,
        }
    );
}

/** Merge `patch` into the durable record for `id` and persist it. */
export function saveEntry(filePath, id, patch) {
    const all = readAll(filePath);
    const current = all[id] || {};
    const next = { ...current, ...patch, updatedAt: new Date().toISOString() };
    all[id] = next;
    writeAll(filePath, all);
    return next;
}
