// exec.mjs — sandboxed command execution for the waypoint-setup-deploy canvas.
//
// SECURITY CONTRACT: every function here takes a *pre-built argument array*.
// Nothing in this file (or its callers) ever concatenates user input into a
// shell string. All child processes are spawned with `execFile`, which never
// invokes a shell, so there is no injection surface even if a caller passed a
// hostile value inside one array element.
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const EXTENSION_DIR = path.dirname(fileURLToPath(import.meta.url));
// .github/extensions/waypoint-setup-deploy -> repo root is three levels up.
export const REPO_ROOT = path.resolve(EXTENSION_DIR, "..", "..", "..");
export const SCRIPTS_DIR = path.join(REPO_ROOT, "tools", "deploy", "scripts");
export const ADMIN_PREFLIGHT_SCRIPT = path.join(SCRIPTS_DIR, "admin_preflight.py");
export const GUIDED_SETUP_DEPLOY_SCRIPT = path.join(SCRIPTS_DIR, "guided_setup_deploy.py");

const LOCAL_BIN_DIRS =
    process.platform === "win32"
        ? [
              process.env.LOCALAPPDATA ? `${process.env.LOCALAPPDATA}\\Programs\\Python` : "",
              process.env.ProgramFiles ? `${process.env.ProgramFiles}\\Python3` : "",
              process.env.SystemRoot ? `${process.env.SystemRoot}\\System32` : "",
          ].filter(Boolean)
        : ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"];

function augmentedEnv() {
    const dirs = [...LOCAL_BIN_DIRS, ...(process.env.PATH || "").split(path.delimiter)];
    const seen = new Set();
    const pathValue = dirs.filter((d) => d && !seen.has(d) && seen.add(d)).join(path.delimiter);
    return { ...process.env, PATH: pathValue };
}

export function resolveBin(name, alts = []) {
    const names = process.platform === "win32" ? [name, `${name}.exe`, ...alts] : [name, ...alts];
    for (const dir of LOCAL_BIN_DIRS) {
        for (const candidate of names) {
            const candidatePath = path.join(dir, candidate);
            try {
                if (fs.existsSync(candidatePath)) return candidatePath;
            } catch {
                /* ignore and keep looking */
            }
        }
    }
    return name;
}

/**
 * Execute `bin` with `args` (an argument ARRAY, never a joined string) and
 * resolve with { code, stdout, stderr }. Never rejects on a non-zero exit —
 * callers decide how to interpret failure so preflight/status probes can
 * degrade gracefully instead of throwing.
 */
export function execArgs(bin, args, opts = {}) {
    if (!Array.isArray(args)) {
        throw new TypeError("execArgs requires an argument array, never a command string");
    }
    return new Promise((resolve) => {
        execFile(
            bin,
            args,
            {
                cwd: opts.cwd || REPO_ROOT,
                env: augmentedEnv(),
                timeout: opts.timeoutMs || 120_000,
                maxBuffer: 10 * 1024 * 1024,
                windowsHide: true,
            },
            (err, stdout, stderr) => {
                resolve({
                    code: err && typeof err.code === "number" ? err.code : err ? 1 : 0,
                    stdout: String(stdout || ""),
                    stderr: String(stderr || err?.message || ""),
                });
            },
        );
    });
}

function pythonBin() {
    return resolveBin("python3", ["python"]);
}

/** Run one of our tools/deploy/scripts/*.py helpers with an argument array and
 * parse its stdout as JSON. Throws only when the script cannot even be
 * invoked or the output truly is not JSON — callers still see partial JSON
 * (e.g. an "ok": false payload) as a normal, non-throwing result. */
export async function runPythonJson(scriptPath, args) {
    if (!Array.isArray(args)) {
        throw new TypeError("runPythonJson requires an argument array");
    }
    const { code, stdout, stderr } = await execArgs(pythonBin(), [scriptPath, ...args]);
    const text = stdout.trim();
    if (!text) {
        throw new Error(stderr.trim() || `${path.basename(scriptPath)} produced no output (exit ${code}).`);
    }
    try {
        return JSON.parse(text);
    } catch {
        throw new Error(`${path.basename(scriptPath)} did not return JSON: ${text.slice(0, 500)}`);
    }
}
