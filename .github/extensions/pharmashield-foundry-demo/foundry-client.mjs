import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const ARM_PROJECT_API_VERSION = "2025-06-01";
export const RESPONSES_API_VERSION = "2025-11-15-preview";
export const FOUNDRY_FEATURES = "HostedAgents=V1Preview,AgentEndpoints=V1Preview";
export const AI_RESOURCE = "https://ai.azure.com";
export const DEFAULT_AGENT = "contract-policy-expert";

const TERMINAL_STATUSES = new Set([
    "completed",
    "failed",
    "cancelled",
    "canceled",
    "incomplete",
    "expired",
]);

function commandPath() {
    return [
        process.env.PATH || "",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
    ].join(":");
}

export async function runAz(args, options = {}) {
    const { stdout } = await execFileAsync("az", args, {
        timeout: options.timeout || 30000,
        maxBuffer: 4 << 20,
        env: { ...process.env, PATH: commandPath() },
    });
    return String(stdout).trim();
}

export async function azureIdentity(az = runAz) {
    const raw = await az([
        "account",
        "show",
        "--query",
        "{tenantId:tenantId,subscriptionId:id,subscriptionName:name,user:user.name}",
        "-o",
        "json",
    ]);
    return JSON.parse(raw);
}

export async function acquireFoundryToken(az = runAz) {
    const token = await az([
        "account",
        "get-access-token",
        "--resource",
        AI_RESOURCE,
        "--query",
        "accessToken",
        "-o",
        "tsv",
    ]);
    if (!token) {
        throw new Error("Azure returned an empty Foundry access token.");
    }
    return token;
}

export async function listHostedAgents({
    projectEndpoint,
    token,
    fetchImpl = fetch,
    az = runAz,
}) {
    if (!projectEndpoint) throw new Error("Foundry project endpoint is required.");
    const bearer = token || (await acquireFoundryToken(az));
    const response = await fetchImpl(
        `${projectEndpoint.replace(/\/+$/, "")}/agents?api-version=${RESPONSES_API_VERSION}`,
        {
            method: "GET",
            headers: {
                Authorization: `Bearer ${bearer}`,
                "Foundry-Features": FOUNDRY_FEATURES,
                Accept: "application/json",
            },
        },
    );
    const text = await response.text();
    if (!response.ok) {
        throw new Error(`Foundry agent inventory failed (HTTP ${response.status}): ${text.slice(0, 500)}`);
    }
    const body = JSON.parse(text);
    const agents = body.data || body.value || body.agents || [];
    return agents
        .map((agent) => String(agent.name || agent.id || ""))
        .filter(Boolean);
}

export async function hasHostedAgent(options) {
    const agents = await listHostedAgents(options);
    return agents.includes(options.agentName || DEFAULT_AGENT);
}

export function rankProject(project, preferredResourceGroup = "") {
    const name = `${project.name || ""} ${project.resourceGroup || ""}`.toLowerCase();
    let score = 0;
    if (preferredResourceGroup && project.resourceGroup === preferredResourceGroup) score += 1000;
    if (name.includes("waypoint")) score += 200;
    if (name.includes("forge")) score += 100;
    if (name.includes("parity")) score += 20;
    return score;
}

export async function listFoundryProjects({
    az = runAz,
    preferredResourceGroup = process.env.AZURE_RESOURCE_GROUP || "",
} = {}) {
    const raw = await az([
        "resource",
        "list",
        "--resource-type",
        "Microsoft.CognitiveServices/accounts/projects",
        "--query",
        "[].{id:id,name:name,resourceGroup:resourceGroup,location:location}",
        "-o",
        "json",
    ]);
    const projects = JSON.parse(raw);
    return projects
        .map((project) => ({
            ...project,
            projectName: String(project.name || "").split("/").at(-1),
            score: rankProject(project, preferredResourceGroup),
        }))
        .sort(
            (left, right) =>
                right.score - left.score ||
                String(left.resourceGroup).localeCompare(String(right.resourceGroup)) ||
                String(left.name).localeCompare(String(right.name)),
        );
}

export async function resolveProjectEndpoint(resourceId, az = runAz) {
    if (!resourceId) throw new Error("A Foundry project resource ID is required.");
    const separator = resourceId.includes("?") ? "&" : "?";
    const raw = await az([
        "rest",
        "--method",
        "get",
        "--url",
        `${resourceId}${separator}api-version=${ARM_PROJECT_API_VERSION}`,
        "--query",
        "{id:id,name:name,displayName:properties.displayName,endpoint:properties.endpoints.\"AI Foundry API\",location:location}",
        "-o",
        "json",
    ]);
    const project = JSON.parse(raw);
    if (!project.endpoint) {
        throw new Error(`Foundry project ${project.displayName || project.name} has no AI Foundry API endpoint.`);
    }
    return project;
}

export async function resolveFoundryProject({
    explicitEndpoint = process.env.FOUNDRY_PROJECT_ENDPOINT || process.env.AZURE_AI_PROJECT_ENDPOINT || "",
    explicitResourceId = process.env.FOUNDRY_PROJECT_RESOURCE_ID || "",
    preferredResourceGroup = process.env.AZURE_RESOURCE_GROUP || "",
    az = runAz,
} = {}) {
    if (explicitEndpoint) {
        return {
            selected: {
                id: explicitResourceId || null,
                name: "Configured project",
                displayName: "Configured project",
                endpoint: explicitEndpoint.replace(/\/+$/, ""),
                resourceGroup: preferredResourceGroup || null,
            },
            projects: [],
        };
    }
    const projects = await listFoundryProjects({ az, preferredResourceGroup });
    const selectedResource = explicitResourceId
        ? projects.find((project) => project.id.toLowerCase() === explicitResourceId.toLowerCase())
        : projects[0];
    if (!selectedResource) {
        throw new Error(
            "No Azure AI Foundry projects are visible. Deploy the FoundryIQ lane or set FOUNDRY_PROJECT_ENDPOINT.",
        );
    }
    const selected = await resolveProjectEndpoint(selectedResource.id, az);
    return {
        selected: {
            ...selectedResource,
            ...selected,
            endpoint: selected.endpoint.replace(/\/+$/, ""),
        },
        projects,
    };
}

function responsesBase(projectEndpoint, agentName) {
    return `${projectEndpoint.replace(/\/+$/, "")}/agents/${encodeURIComponent(agentName)}/endpoint/protocols/openai/responses`;
}

export async function driveHostedAgent({
    projectEndpoint,
    agentName = DEFAULT_AGENT,
    prompt,
    pollIntervalMs = 5000,
    pollTimeoutMs = 10 * 60 * 1000,
    token,
    fetchImpl = fetch,
    az = runAz,
    signal,
    onProgress = () => {},
}) {
    if (!projectEndpoint) throw new Error("Foundry project endpoint is required.");
    if (!prompt) throw new Error("A demo prompt is required.");
    const bearer = token || (await acquireFoundryToken(az));
    const headers = {
        Authorization: `Bearer ${bearer}`,
        "Foundry-Features": FOUNDRY_FEATURES,
        "Content-Type": "application/json",
        Accept: "application/json",
    };
    const base = responsesBase(projectEndpoint, agentName);
    const startUrl = `${base}?api-version=${RESPONSES_API_VERSION}`;
    onProgress({ phase: "starting", message: `Starting ${agentName} in background mode.` });
    const startResponse = await fetchImpl(startUrl, {
        method: "POST",
        headers,
        body: JSON.stringify({ input: prompt, store: true, background: true }),
        signal,
    });
    const startedText = await startResponse.text();
    if (!startResponse.ok) {
        throw new Error(`Foundry start failed (HTTP ${startResponse.status}): ${startedText.slice(0, 500)}`);
    }
    const started = JSON.parse(startedText);
    const responseId = started.id || started.response_id;
    if (!responseId) throw new Error("Foundry returned no response ID.");
    onProgress({
        phase: "running",
        message: `Hosted response ${responseId} is ${started.status || "in progress"}.`,
        responseId,
    });

    const deadline = Date.now() + pollTimeoutMs;
    let last = started;
    while (Date.now() < deadline) {
        if (signal?.aborted) throw new Error("The canvas closed while the hosted response was running.");
        await sleep(pollIntervalMs, signal);
        const pollUrl = `${base}/${encodeURIComponent(responseId)}?api-version=${RESPONSES_API_VERSION}`;
        const pollResponse = await fetchImpl(pollUrl, { method: "GET", headers, signal });
        const pollText = await pollResponse.text();
        if (!pollResponse.ok) {
            throw new Error(`Foundry poll failed (HTTP ${pollResponse.status}): ${pollText.slice(0, 500)}`);
        }
        last = JSON.parse(pollText);
        const status = String(last.status || "in_progress").toLowerCase();
        onProgress({
            phase: TERMINAL_STATUSES.has(status) ? status : "running",
            message: `Hosted response ${responseId}: ${status}.`,
            responseId,
        });
        if (TERMINAL_STATUSES.has(status)) return last;
    }
    throw new Error(`Hosted response ${responseId} did not finish within ${pollTimeoutMs / 1000} seconds.`);
}

export function extractHostedResult(body) {
    const textChunks = [];
    const toolCalls = [];
    const citations = [];
    walk(body, (value) => {
        if (!value || typeof value !== "object" || Array.isArray(value)) return;
        const type = String(value.type || "");
        if (
            (type === "output_text" || type === "text") &&
            typeof value.text === "string" &&
            value.text.trim()
        ) {
            textChunks.push(value.text);
        }
        if (
            type.includes("mcp") ||
            type.includes("tool") ||
            type === "function_call" ||
            type === "function_call_output"
        ) {
            const name = String(value.name || value.tool_name || value.server_label || "");
            if (name || value.arguments || value.output || value.call_id) {
                toolCalls.push({
                    type,
                    name,
                    callId: String(value.call_id || ""),
                    arguments: compact(value.arguments),
                    output: compact(value.output),
                    error: compact(value.error),
                });
            }
        }
        for (const annotation of value.annotations || []) {
            if (!annotation || typeof annotation !== "object") continue;
            citations.push({
                title: String(annotation.title || annotation.text || "Foundry citation"),
                url: String(annotation.url || annotation.uri || ""),
            });
        }
    });
    if (typeof body?.output_text === "string" && body.output_text.trim()) {
        textChunks.unshift(body.output_text);
    }
    const outputText = [...new Set(textChunks.map((text) => text.trim()).filter(Boolean))].join("\n");
    const grounded = toolCalls.some((call) =>
        call.name.toLowerCase().includes("knowledge_base_retrieve"),
    );
    return {
        status: String(body?.status || "unknown"),
        responseId: body?.id || body?.response_id || null,
        outputText,
        parsedEvidence: parseEvidence(outputText),
        toolCalls,
        citations,
        grounded,
    };
}

function parseEvidence(text) {
    const candidate = String(text || "")
        .replace(/^```(?:json)?\s*/i, "")
        .replace(/\s*```$/i, "")
        .trim();
    if (!candidate) return null;
    try {
        const parsed = JSON.parse(candidate);
        return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
        const start = candidate.indexOf("{");
        const end = candidate.lastIndexOf("}");
        if (start < 0 || end <= start) return null;
        try {
            return JSON.parse(candidate.slice(start, end + 1));
        } catch {
            return null;
        }
    }
}

function compact(value) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > 4000 ? `${text.slice(0, 4000)}…` : text;
}

function walk(value, visit, seen = new Set()) {
    if (!value || typeof value !== "object" || seen.has(value)) return;
    seen.add(value);
    visit(value);
    if (Array.isArray(value)) {
        for (const item of value) walk(item, visit, seen);
        return;
    }
    for (const item of Object.values(value)) walk(item, visit, seen);
}

function sleep(ms, signal) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, ms);
        signal?.addEventListener(
            "abort",
            () => {
                clearTimeout(timer);
                reject(new Error("The hosted response poll was cancelled."));
            },
            { once: true },
        );
    });
}
