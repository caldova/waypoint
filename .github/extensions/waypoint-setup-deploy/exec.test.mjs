import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import {
    ADMIN_PREFLIGHT_SCRIPT,
    execArgs,
    GUIDED_SETUP_DEPLOY_SCRIPT,
    REPO_ROOT,
    resolveBin,
    runPythonJson,
    SCRIPTS_DIR,
} from "./exec.mjs";

test("execArgs rejects a joined command string instead of an argument array (no shell injection surface)", () => {
    assert.throws(() => execArgs("echo", "not an array"), TypeError);
    assert.throws(() => execArgs("echo", "rm -rf /"), TypeError);
});

test("runPythonJson rejects a joined argument string", async () => {
    await assert.rejects(() => runPythonJson(ADMIN_PREFLIGHT_SCRIPT, "--json"), TypeError);
});

test("script paths resolve under tools/deploy/scripts in the repo root", () => {
    assert.equal(SCRIPTS_DIR, path.join(REPO_ROOT, "tools", "deploy", "scripts"));
    assert.equal(ADMIN_PREFLIGHT_SCRIPT, path.join(SCRIPTS_DIR, "admin_preflight.py"));
    assert.equal(GUIDED_SETUP_DEPLOY_SCRIPT, path.join(SCRIPTS_DIR, "guided_setup_deploy.py"));
    assert.ok(path.basename(REPO_ROOT).length > 0);
});

test("resolveBin never throws and always returns a non-empty string", () => {
    for (const name of ["python3", "git", "totally-not-a-real-binary-xyz"]) {
        const resolved = resolveBin(name);
        assert.equal(typeof resolved, "string");
        assert.ok(resolved.length > 0);
    }
});

test("execArgs runs a real argv array end to end and never invokes a shell", async () => {
    const result = await execArgs(resolveBin("python3", ["python"]), ["-c", "print('hello from argv')"]);
    assert.equal(result.code, 0);
    assert.match(result.stdout, /hello from argv/);
});

test("execArgs surfaces non-zero exit codes without throwing (callers decide how to interpret failure)", async () => {
    const result = await execArgs(resolveBin("python3", ["python"]), ["-c", "import sys; sys.exit(3)"]);
    assert.equal(result.code, 3);
});

test("runPythonJson parses well-formed JSON stdout from a real script invocation", async () => {
    const names = await runPythonJson(GUIDED_SETUP_DEPLOY_SCRIPT, [
        "derive-names",
        "--subscription-id",
        "11111111-1111-1111-1111-111111111111",
        "--region",
        "swedencentral",
        "--target-repo",
        "caldova/waypoint",
    ]);
    assert.equal(typeof names, "object");
    assert.equal(names.owner, "caldova");
    assert.equal(names.repo, "waypoint");
});

test("runPythonJson throws a descriptive error when a script produces no stdout", async () => {
    await assert.rejects(
        () => runPythonJson("/tmp/definitely-does-not-exist-wsd.py", []),
        /produced no output|no such file|cannot find/i,
    );
});
