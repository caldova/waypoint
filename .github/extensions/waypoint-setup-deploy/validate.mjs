// validate.mjs — pure, dependency-free validation helpers shared by
// extension.mjs. Deliberately does NOT import @github/copilot-sdk: that
// package is only resolvable inside a running extension host process, so
// keeping this module SDK-free lets its pure logic be unit tested directly
// with `node --test`, unlike extension.mjs itself (which calls joinSession()
// at module load time and requires a live RPC connection). extension.mjs
// converts ValidationError -> the real CanvasError at its action/HTTP
// boundaries (see asCanvasError there).
export class ValidationError extends Error {
    constructor(code, message) {
        super(message);
        this.name = "ValidationError";
        this.code = code;
    }
}

/** Split "owner/name" into its parts; throws ValidationError on anything else
 * (missing slash, empty owner/name, extra segments). */
export function parseRepo(targetRepo) {
    const parts = String(targetRepo || "").split("/");
    const [owner, repo] = parts;
    if (parts.length !== 2 || !owner || !repo) {
        throw new ValidationError("invalid_input", "targetRepo must be in 'owner/name' form.");
    }
    return { owner, repo };
}

/** Trim + require all four setup fields; validates targetRepo shape early so
 * a malformed repo string fails at open() time rather than deep in a later
 * mutating call. */
export function normalizeConfig(input) {
    const config = {
        subscriptionId: String(input?.subscriptionId || "").trim(),
        tenantId: String(input?.tenantId || "").trim(),
        region: String(input?.region || "").trim(),
        targetRepo: String(input?.targetRepo || "").trim(),
    };
    for (const [key, value] of Object.entries(config)) {
        if (!value) throw new ValidationError("invalid_input", `${key} is required.`);
    }
    parseRepo(config.targetRepo);
    return config;
}

/** Fail-closed confirmation gate for mutating actions (bootstrap/deploy).
 * Accepts ONLY the strict boolean `true` — not "true", 1, "yes", etc. This is
 * defense in depth alongside the canvas action's own `{ const: true }`
 * inputSchema and guided_setup_deploy.py's require_confirmation(); no single
 * layer is trusted alone. */
export function requireConfirmation(confirm, action) {
    if (confirm !== true) {
        throw new ValidationError(
            "confirmation_required",
            `${action} is a mutating action and requires confirm=true.`,
        );
    }
}
