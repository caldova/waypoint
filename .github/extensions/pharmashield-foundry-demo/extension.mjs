import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";
import { buildDemoPrompt, HERO_INVOICE } from "./demo-data.mjs";
import {
    DEFAULT_AGENT,
    acquireFoundryToken,
    azureIdentity,
    driveHostedAgent,
    extractHostedResult,
    getHostedAgentDetails,
    resolveFoundryProject,
    resolveProjectEndpoint,
} from "./foundry-client.mjs";
import { renderHtml } from "./renderer.mjs";

const EXTENSION_DIR = path.dirname(fileURLToPath(import.meta.url));
const servers = new Map();

function createEntry(input = {}) {
    return {
        config: {
            projectEndpoint: String(input.projectEndpoint || ""),
            projectResourceId: String(input.projectResourceId || ""),
            preferredResourceGroup: String(input.preferredResourceGroup || ""),
            agentName: String(input.agentName || DEFAULT_AGENT),
            modelName: String(input.modelName || process.env.AZURE_AI_MODEL_DEPLOYMENT_NAME || "gpt-5.5"),
        },
        state: {
            invoice: HERO_INVOICE,
            preflight: {
                status: "running",
                message: "Resolving Azure identity and Foundry project.",
                checks: [],
                project: null,
                projects: [],
                model: null,
            },
            job: { status: "idle", message: "Waiting for readiness checks." },
            result: null,
        },
        clients: new Set(),
        abortController: null,
        closed: false,
    };
}

function publicState(entry) {
    return JSON.parse(JSON.stringify(entry.state));
}

function emit(entry, type = "state") {
    const payload = `data: ${JSON.stringify({ type, at: new Date().toISOString() })}\n\n`;
    for (const response of entry.clients) {
        try {
            response.write(payload);
        } catch {
            entry.clients.delete(response);
        }
    }
}

async function runPreflight(entry) {
    if (entry.preflightPromise) return entry.preflightPromise;
    const promise = performPreflight(entry);
    entry.preflightPromise = promise;
    try {
        return await promise;
    } finally {
        if (entry.preflightPromise === promise) entry.preflightPromise = null;
    }
}

async function performPreflight(entry) {
    entry.state.preflight = {
        ...entry.state.preflight,
        status: "running",
        message: "Resolving Azure identity and Foundry project.",
        checks: [],
    };
    emit(entry);
    try {
        const identity = await azureIdentity();
        entry.state.preflight.checks.push({
            label: "Azure tenant",
            ok: true,
            detail: `${identity.user} · ${identity.subscriptionName}`,
        });
        emit(entry);

        const resolved = await resolveFoundryProject({
            explicitEndpoint: entry.config.projectEndpoint,
            explicitResourceId: entry.config.projectResourceId,
            preferredResourceGroup: entry.config.preferredResourceGroup,
        });
        entry.state.preflight.projects = resolved.projects;
        const token = await acquireFoundryToken();
        let selected = resolved.selected;
        const probeErrors = [];
        let agent = await probeAgent(entry, selected, token, probeErrors);
        const explicitlyConfigured = Boolean(
            entry.config.projectEndpoint || entry.config.projectResourceId,
        );
        if (!agent && !explicitlyConfigured) {
            for (const candidate of resolved.projects.filter(
                (project) => project.id !== selected.id && project.score > 0,
            )) {
                const project = await resolveProjectEndpoint(candidate.id);
                const candidateAgent = await probeAgent(
                    entry,
                    { ...candidate, ...project },
                    token,
                    probeErrors,
                );
                if (candidateAgent) {
                    selected = { ...candidate, ...project };
                    agent = candidateAgent;
                    break;
                }
            }
        }
        if (!agent) {
            throw new Error(
                probeErrors.at(-1) ||
                    `Hosted agent ${entry.config.agentName} was not found in the visible Waypoint/Forge projects.`,
            );
        }
        entry.state.preflight.project = selected;
        entry.state.preflight.model = agent.model || entry.config.modelName;
        entry.config.projectEndpoint = selected.endpoint;
        entry.config.projectResourceId = selected.id || entry.config.projectResourceId;
        entry.state.preflight.checks.push({
            label: "Foundry project",
            ok: true,
            detail: `${selected.displayName || selected.projectName || selected.name} · ${host(selected.endpoint)}`,
        });
        entry.state.preflight.checks.push({
            label: "Hosted agent",
            ok: true,
            detail: `${entry.config.agentName} · ${entry.state.preflight.model}`,
        });
        entry.state.preflight.checks.push({
            label: "Foundry IQ proof",
            ok: null,
            detail: "The demo is grounded only when knowledge_base_retrieve returns evidence successfully.",
        });
        entry.state.preflight.status = "ready";
        entry.state.preflight.message = "Ready for the live Foundry beat.";
        entry.state.job = { status: "idle", message: "Ready. Click once when you reach the live beat." };
    } catch (error) {
        entry.state.preflight.status = "error";
        entry.state.preflight.message = errorMessage(error);
        entry.state.preflight.checks.push({
            label: "Setup required",
            ok: false,
            detail: errorMessage(error),
        });
        entry.state.job = { status: "idle", message: errorMessage(error) };
    }
    emit(entry);
    return publicState(entry);
}

async function probeAgent(entry, project, token, errors) {
    try {
        return await getHostedAgentDetails({
            projectEndpoint: project.endpoint,
            agentName: entry.config.agentName,
            token,
        });
    } catch (error) {
        errors.push(
            `${project.displayName || project.projectName || project.name}: ${errorMessage(error)}`,
        );
        return null;
    }
}

async function selectProject(entry, resourceId) {
    if (!resourceId) throw new CanvasError("invalid_input", "resourceId is required");
    if (["starting", "running"].includes(entry.state.job.status)) {
        throw new CanvasError(
            "run_in_progress",
            "Wait for the current hosted audit to finish before changing projects.",
        );
    }
    const project = await resolveProjectEndpoint(resourceId);
    const agent = await getHostedAgentDetails({
        projectEndpoint: project.endpoint,
        agentName: entry.config.agentName,
    });
    if (!agent) {
        throw new CanvasError(
            "agent_not_deployed",
            `Hosted agent ${entry.config.agentName} is not deployed in ${project.displayName || project.name}.`,
        );
    }
    const listed = entry.state.preflight.projects.find(
        (candidate) => candidate.id.toLowerCase() === resourceId.toLowerCase(),
    );
    entry.config.projectResourceId = resourceId;
    entry.config.projectEndpoint = project.endpoint;
    entry.state.preflight.project = { ...listed, ...project };
    entry.state.preflight.model = agent.model || entry.config.modelName;
    entry.state.preflight.status = "ready";
    entry.state.preflight.message = "Ready for the live Foundry beat.";
    entry.state.preflight.checks = entry.state.preflight.checks.map((check) =>
        check.label === "Foundry project"
            ? {
                  ...check,
                  ok: true,
                  detail: `${project.displayName || project.name} · ${host(project.endpoint)}`,
              }
            : check.label === "Hosted agent"
              ? {
                    ...check,
                    ok: true,
                    detail: `${entry.config.agentName} · ${entry.state.preflight.model}`,
                }
              : check,
    );
    entry.state.result = null;
    entry.state.job = { status: "idle", message: "Ready. Click once when you reach the live beat." };
    resetGroundingProof(entry, "Run the audit to verify Foundry IQ retrieval in this project.");
    emit(entry);
    return publicState(entry);
}

async function startDemo(entry) {
    if (entry.state.preflight.status !== "ready") {
        throw new CanvasError("preflight_required", "Complete Foundry readiness checks before starting.");
    }
    if (["starting", "running"].includes(entry.state.job.status)) {
        return publicState(entry);
    }
    entry.abortController = new AbortController();
    entry.state.result = null;
    resetGroundingProof(entry, "Waiting for the live hosted response.");
    entry.state.job = {
        status: "starting",
        message: `Loading ${HERO_INVOICE.source} and starting ${entry.config.agentName}.`,
        startedAt: new Date().toISOString(),
    };
    emit(entry);
    void executeDemo(entry);
    return publicState(entry);
}

async function executeDemo(entry) {
    try {
        const invoicePath = path.join(EXTENSION_DIR, HERO_INVOICE.source);
        const invoiceText = await readFile(invoicePath, "utf8");
        const response = await driveHostedAgent({
            projectEndpoint: entry.config.projectEndpoint,
            agentName: entry.config.agentName,
            prompt: buildDemoPrompt(invoiceText),
            signal: entry.abortController.signal,
            onProgress: (progress) => {
                entry.state.job = {
                    ...entry.state.job,
                    status: progress.phase === "starting" ? "starting" : "running",
                    message: progress.message,
                    responseId: progress.responseId || entry.state.job.responseId || null,
                };
                emit(entry, "progress");
            },
        });
        const result = extractHostedResult(response);
        if (result.status !== "completed") {
            throw new Error(`Hosted response ended with status ${result.status}.`);
        }
        entry.state.result = result;
        entry.state.job = {
            ...entry.state.job,
            status: result.grounded ? "completed" : "error",
            message: result.grounded
                ? "Live audit completed with a verified knowledge_base_retrieve result."
                : result.retrievalAttempted
                  ? "The knowledge-base retrieval failed or returned no evidence. Do not present this run as grounded."
                  : "The hosted response completed without knowledge_base_retrieve. Do not present this run as grounded.",
            completedAt: new Date().toISOString(),
        };
        entry.state.preflight.checks = entry.state.preflight.checks.map((check) =>
            check.label === "Foundry IQ proof"
                ? {
                      ...check,
                      ok: result.grounded,
                      detail: result.grounded
                          ? "Verified in the live hosted response."
                          : result.retrievalAttempted
                            ? "Retrieval was attempted but did not return usable evidence."
                            : "No knowledge_base_retrieve tool call was returned.",
                  }
                : check,
        );
    } catch (error) {
        resetGroundingProof(entry, "The hosted audit failed before grounding could be verified.", false);
        entry.state.job = {
            ...entry.state.job,
            status: "error",
            message: errorMessage(error),
            completedAt: new Date().toISOString(),
        };
    }
    emit(entry, "complete");
}

function resetGroundingProof(entry, detail, ok = null) {
    entry.state.preflight.checks = entry.state.preflight.checks.map((check) =>
        check.label === "Foundry IQ proof" ? { ...check, ok, detail } : check,
    );
}

async function startServer(entry) {
    const server = createServer(async (request, response) => {
        const url = new URL(request.url || "/", "http://127.0.0.1");
        try {
            if (request.method === "GET" && url.pathname === "/") {
                response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
                response.end(renderHtml());
                return;
            }
            if (request.method === "GET" && url.pathname === "/api/state") {
                sendJson(response, 200, publicState(entry));
                return;
            }
            if (request.method === "GET" && url.pathname === "/events") {
                response.writeHead(200, {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    Connection: "keep-alive",
                });
                response.write("retry: 2000\n\n");
                entry.clients.add(response);
                request.on("close", () => entry.clients.delete(response));
                return;
            }
            if (request.method === "POST" && url.pathname === "/api/preflight") {
                sendJson(response, 202, { accepted: true });
                void runPreflight(entry);
                return;
            }
            if (request.method === "POST" && url.pathname === "/api/project") {
                const body = await readJson(request);
                const state = await selectProject(entry, String(body.resourceId || ""));
                sendJson(response, 200, state);
                return;
            }
            if (request.method === "POST" && url.pathname === "/api/run") {
                const state = await startDemo(entry);
                sendJson(response, 202, state);
                return;
            }
            sendJson(response, 404, { error: "Not found" });
        } catch (error) {
            const status = error instanceof CanvasError ? 400 : 500;
            sendJson(response, status, { error: errorMessage(error) });
        }
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    return {
        server,
        url: `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}/`,
    };
}

function requireEntry(instanceId) {
    const entry = servers.get(instanceId);
    if (!entry) throw new CanvasError("canvas_not_open", "Open the Pharmashield Foundry canvas first.");
    return entry;
}

function sendJson(response, status, value) {
    const body = JSON.stringify(value);
    response.writeHead(status, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": Buffer.byteLength(body),
    });
    response.end(body);
}

async function readJson(request) {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString("utf8");
    return text ? JSON.parse(text) : {};
}

function host(endpoint) {
    try {
        return new URL(endpoint).host;
    } catch {
        return endpoint;
    }
}

function errorMessage(error) {
    if (error instanceof Error && error.message) return error.message;
    return String(error || "Unknown error");
}

await joinSession({
    canvases: [
        createCanvas({
            id: "pharmashield-foundry-demo",
            displayName: "Pharmashield · Foundry live demo",
            description:
                "Open the one-click Pharmashield presenter runbook and run the Aster Ridge contract audit live against a hosted FoundryIQ agent.",
            inputSchema: {
                type: "object",
                properties: {
                    projectEndpoint: { type: "string", description: "Optional explicit AI Foundry project endpoint." },
                    projectResourceId: { type: "string", description: "Optional Azure resource ID for the Foundry project." },
                    preferredResourceGroup: { type: "string", description: "Optional resource group preferred during discovery." },
                    agentName: { type: "string", description: "Hosted agent name; defaults to contract-policy-expert." },
                    modelName: { type: "string", description: "Fallback model deployment name when the hosted inventory does not report one." },
                },
                additionalProperties: false,
            },
            actions: [
                {
                    name: "preflight",
                    description: "Re-run Azure identity and Foundry project readiness checks.",
                    handler: async (context) => runPreflight(requireEntry(context.instanceId)),
                },
                {
                    name: "select_project",
                    description: "Select one of the Azure AI Foundry projects discovered by preflight.",
                    inputSchema: {
                        type: "object",
                        properties: { resourceId: { type: "string" } },
                        required: ["resourceId"],
                        additionalProperties: false,
                    },
                    handler: async (context) =>
                        selectProject(requireEntry(context.instanceId), String(context.input.resourceId || "")),
                },
                {
                    name: "run_demo",
                    description:
                        "Start the live Aster Ridge contract-evidence run against contract-policy-expert. The canvas updates while the hosted response runs.",
                    handler: async (context) => startDemo(requireEntry(context.instanceId)),
                },
                {
                    name: "status",
                    description: "Return current readiness, hosted run, grounding, and trace status.",
                    handler: async (context) => publicState(requireEntry(context.instanceId)),
                },
            ],
            open: async (context) => {
                let entry = servers.get(context.instanceId);
                if (!entry) {
                    entry = createEntry(context.input || {});
                    const listener = await startServer(entry);
                    Object.assign(entry, listener);
                    servers.set(context.instanceId, entry);
                    void runPreflight(entry);
                }
                return {
                    title: "Pharmashield · Foundry live demo",
                    status: entry.state.preflight.status,
                    url: entry.url,
                };
            },
            onClose: async (context) => {
                const entry = servers.get(context.instanceId);
                if (!entry) return;
                entry.closed = true;
                entry.abortController?.abort();
                for (const client of entry.clients) client.end();
                servers.delete(context.instanceId);
                await new Promise((resolve) => {
                    entry.server.close(resolve);
                    entry.server.closeAllConnections?.();
                });
            },
        }),
    ],
});
