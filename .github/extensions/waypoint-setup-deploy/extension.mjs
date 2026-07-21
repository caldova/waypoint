// Extension: waypoint-setup-deploy
//
// Guided admin preflight + one-click Waypoint setup/deploy canvas.
//
// Flow: open() takes exactly four inputs (subscriptionId, tenantId, region,
// targetRepo), derives every other resource/environment name deterministically
// via tools/deploy/scripts/guided_setup_deploy.py, and offers four actions:
//   - preflight  (read-only)  -> tools/deploy/scripts/admin_preflight.py
//   - bootstrap  (MUTATING)   -> runs the existing idempotent oidc.sh
//   - deploy     (MUTATING)   -> dispatches .github/workflows/deploy.yml
//   - refresh    (read-only)  -> polls the dispatched run + recorded links
//
// Mutating actions are gated TWICE: the canvas action inputSchema requires the
// literal boolean `confirm: true` (schema-level `const`, validated by the
// runtime before the handler ever runs), and the underlying Python helper
// re-checks `confirm is True` before touching anything. Neither layer trusts
// the other. Every external command is built as an argument array and run via
// execFile/subprocess — never a shell string.
import { createServer } from "node:http";
import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";
import { ADMIN_PREFLIGHT_SCRIPT, GUIDED_SETUP_DEPLOY_SCRIPT, runPythonJson } from "./exec.mjs";
import { renderHtml } from "./renderer.mjs";
import { domainId, loadEntry, saveEntry, stateFilePath } from "./state.mjs";
import { normalizeConfig, parseRepo, requireConfirmation, ValidationError } from "./validate.mjs";

// Set once the top-level joinSession() call below resolves. Handler closures
// read this lazily (they only ever run after that await completes), which is
// how we get session.workspacePath without a circular reference at
// canvas-declaration time.
let sessionRef = null;

// instanceId -> { server, url, id } — the http.Server + resolved domainId for
// this open panel. Durable data lives in the state file keyed by `id`, never
// by instanceId (see state.mjs).
const servers = new Map();

function currentStateFile() {
    return stateFilePath(sessionRef?.workspacePath);
}

// validate.mjs is intentionally SDK-free (see its header) so its pure logic
// is unit-testable without a live extension host; translate its
// ValidationError into the real CanvasError at this process's boundary.
function asCanvasError(error) {
    if (error instanceof ValidationError) return new CanvasError(error.code, error.message);
    return error;
}

async function deriveNames(config) {
    return runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
        "derive-names",
        "--subscription-id",
        config.subscriptionId,
        "--region",
        config.region,
        "--target-repo",
        config.targetRepo,
    ]);
}

/** Resolve (and persist, if new/changed) the config + derived names for an
 * open() call. Idempotent: re-opening the same config is a no-op read. */
async function ensureConfigured(input) {
    const config = normalizeConfig(input);
    const id = domainId(config);
    const stateFile = currentStateFile();
    let entry = loadEntry(stateFile, id);
    const unchanged = entry.config && JSON.stringify(entry.config) === JSON.stringify(config) && entry.names;
    if (!unchanged) {
        const names = await deriveNames(config);
        entry = saveEntry(stateFile, id, { config, names });
    }
    return { id, entry };
}

function requireEntryId(instanceId) {
    const server = servers.get(instanceId);
    if (!server) {
        throw new CanvasError("canvas_not_open", "Open the Waypoint setup/deploy canvas first.");
    }
    return server.id;
}

function requireConfig(id) {
    const entry = loadEntry(currentStateFile(), id);
    if (!entry.config) {
        throw new CanvasError("not_configured", "Provide subscriptionId/tenantId/region/targetRepo first.");
    }
    return entry;
}

async function doPreflight(id) {
    const entry = requireConfig(id);
    const report = await runPythonJson(ADMIN_PREFLIGHT_SCRIPT, [
        "--subscription-id",
        entry.config.subscriptionId,
        "--tenant-id",
        entry.config.tenantId,
        "--repo",
        entry.config.targetRepo,
        "--region",
        entry.config.region,
        "--json",
    ]);
    return saveEntry(currentStateFile(), id, { preflight: report });
}

async function doBootstrap(id, confirm) {
    requireConfirmation(confirm, "bootstrap");
    const entry = requireConfig(id);
    const { owner, repo } = parseRepo(entry.config.targetRepo);
    const result = await runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
        "bootstrap",
        "--owner",
        owner,
        "--repo",
        repo,
        "--subscription-id",
        entry.config.subscriptionId,
        "--region",
        entry.config.region,
        "--confirm",
    ]);
    return saveEntry(currentStateFile(), id, { bootstrap: result });
}

async function doDeploy(id, confirm) {
    requireConfirmation(confirm, "deploy");
    const entry = requireConfig(id);
    if (!entry.names) throw new CanvasError("not_configured", "Names have not been derived yet.");
    const { owner, repo } = parseRepo(entry.config.targetRepo);
    const result = await runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
        "deploy",
        "--owner",
        owner,
        "--repo",
        repo,
        "--names-json",
        JSON.stringify(entry.names),
        "--confirm",
    ]);
    return saveEntry(currentStateFile(), id, { deploy: result });
}

async function doRefresh(id) {
    const entry = requireConfig(id);
    const { owner, repo } = parseRepo(entry.config.targetRepo);
    const patch = {};

    if (entry.deploy?.run_found && entry.deploy?.run_id) {
        const status = await runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
            "status",
            "--owner",
            owner,
            "--repo",
            repo,
            "--run-id",
            String(entry.deploy.run_id),
        ]);
        patch.deploy = { ...entry.deploy, ...status };
    }

    if (entry.names?.state_resource_group) {
        patch.links = await runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
            "links",
            "--resource-group",
            entry.names.state_resource_group,
        ]);
    }

    if (Object.keys(patch).length === 0) return entry;
    return saveEntry(currentStateFile(), id, patch);
}

function publicState(id) {
    return loadEntry(currentStateFile(), id);
}

// ---- loopback HTTP server (drives the iframe UI) --------------------------

async function startServer(instanceId, id) {
    const server = createServer(async (req, res) => {
        const url = new URL(req.url || "/", "http://127.0.0.1");
        try {
            if (req.method === "GET" && url.pathname === "/") {
                res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
                res.end(renderHtml());
                return;
            }
            if (req.method === "GET" && url.pathname === "/api/state") {
                sendJson(res, 200, publicState(id));
                return;
            }
            if (req.method === "POST" && url.pathname === "/api/preflight") {
                sendJson(res, 200, await doPreflight(id));
                return;
            }
            if (req.method === "POST" && url.pathname === "/api/bootstrap") {
                const body = await readJson(req);
                sendJson(res, 200, await doBootstrap(id, body.confirm === true));
                return;
            }
            if (req.method === "POST" && url.pathname === "/api/deploy") {
                const body = await readJson(req);
                sendJson(res, 200, await doDeploy(id, body.confirm === true));
                return;
            }
            if (req.method === "POST" && url.pathname === "/api/refresh") {
                sendJson(res, 200, await doRefresh(id));
                return;
            }
            sendJson(res, 404, { error: "Not found" });
        } catch (rawError) {
            const error = asCanvasError(rawError);
            const status = error instanceof CanvasError ? 400 : 500;
            sendJson(res, status, { error: errorMessage(error) });
        }
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    return { server, url: `http://127.0.0.1:${port}/` };
}

function sendJson(res, status, value) {
    const body = JSON.stringify(value);
    res.writeHead(status, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
    });
    res.end(body);
}

async function readJson(req) {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString("utf8");
    return text ? JSON.parse(text) : {};
}

function errorMessage(error) {
    if (error instanceof Error && error.message) return error.message;
    return String(error || "Unknown error");
}

// ---- canvas wiring ----------------------------------------------------------

sessionRef = await joinSession({
    canvases: [
        createCanvas({
            id: "waypoint-setup-deploy",
            displayName: "Waypoint guided setup + deploy",
            description:
                "Preflight Azure/GitHub admin readiness, then guide a one-click Waypoint bootstrap + deploy. " +
                "Asks only for subscription, tenant, region, and target repo; every other name is derived. " +
                "Bootstrap and deploy always require explicit user confirmation.",
            inputSchema: {
                type: "object",
                properties: {
                    subscriptionId: { type: "string", description: "Target Azure subscription ID (GUID)." },
                    tenantId: { type: "string", description: "Target Entra tenant ID (GUID)." },
                    region: { type: "string", description: "Azure region, e.g. swedencentral." },
                    targetRepo: { type: "string", description: "GitHub repository to deploy, as 'owner/name'." },
                },
                required: ["subscriptionId", "tenantId", "region", "targetRepo"],
                additionalProperties: false,
            },
            actions: [
                {
                    name: "preflight",
                    description:
                        "Run read-only admin readiness checks: Azure/gh auth, tenant/subscription match, repo " +
                        "admin/OIDC access, required resource providers, RBAC role-assignment ability, Microsoft " +
                        "Graph admin-consent boundary, Foundry model quota, and Fabric capacity/permissions.",
                    handler: async (ctx) => {
                        try {
                            return await doPreflight(requireEntryId(ctx.instanceId));
                        } catch (error) {
                            throw asCanvasError(error);
                        }
                    },
                },
                {
                    name: "bootstrap",
                    description:
                        "MUTATING: runs the existing idempotent oidc.sh to bootstrap Azure OIDC trust and set " +
                        "repo variables/secrets. Requires confirm=true.",
                    inputSchema: {
                        type: "object",
                        properties: { confirm: { type: "boolean", const: true } },
                        required: ["confirm"],
                        additionalProperties: false,
                    },
                    handler: async (ctx) => {
                        try {
                            return await doBootstrap(requireEntryId(ctx.instanceId), ctx.input?.confirm);
                        } catch (error) {
                            throw asCanvasError(error);
                        }
                    },
                },
                {
                    name: "deploy",
                    description:
                        "MUTATING: dispatches .github/workflows/deploy.yml with the derived deterministic names " +
                        "and locates the new run. Requires confirm=true.",
                    inputSchema: {
                        type: "object",
                        properties: { confirm: { type: "boolean", const: true } },
                        required: ["confirm"],
                        additionalProperties: false,
                    },
                    handler: async (ctx) => {
                        try {
                            return await doDeploy(requireEntryId(ctx.instanceId), ctx.input?.confirm);
                        } catch (error) {
                            throw asCanvasError(error);
                        }
                    },
                },
                {
                    name: "refresh",
                    description:
                        "Read-only: polls the dispatched deploy run's status and re-reads recorded app/API links.",
                    handler: async (ctx) => {
                        try {
                            return await doRefresh(requireEntryId(ctx.instanceId));
                        } catch (error) {
                            throw asCanvasError(error);
                        }
                    },
                },
            ],
            open: async (ctx) => {
                let id;
                let entry;
                try {
                    ({ id, entry } = await ensureConfigured(ctx.input || {}));
                } catch (error) {
                    throw asCanvasError(error);
                }
                let server = servers.get(ctx.instanceId);
                if (!server) {
                    server = await startServer(ctx.instanceId, id);
                    servers.set(ctx.instanceId, server);
                }
                server.id = id;
                return {
                    title: "Waypoint guided setup + deploy",
                    status: entry.preflight?.overall || "unconfigured",
                    url: server.url,
                };
            },
            onClose: async (ctx) => {
                const server = servers.get(ctx.instanceId);
                if (!server) return;
                servers.delete(ctx.instanceId);
                await new Promise((resolve) => server.server.close(() => resolve()));
            },
        }),
    ],
});
