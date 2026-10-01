import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { joinSession, createCanvas } from "@github/copilot-sdk/extension";
import { lineageBadgeHtml, resolveLineageStatus } from "../shared/lineage-evidence.mjs";

const jobId = "opt_2fb58fc1723e461d9a1496907d029ac8";
const baselineId = "cand_opt_2fb58fc1723e461d9a1496907d029ac8_0000";
const candidateLabel = "candidate_14";
const candidateId = "cand_opt_2fb58fc1723e461d9a1496907d029ac8_0014";
const agentName = "contract-policy-expert";
const extensionDir = dirname(fileURLToPath(import.meta.url));
const fixtureDir = join(extensionDir, "fixtures", jobId);
const servers = new Map();
const candidateConfigFile = `${candidateLabel}-config.json`;
const candidateResultsFile = `${candidateLabel}-results.json`;

function defaultArtifactDir() {
    const copilotHome = process.env.COPILOT_HOME || `${process.env.USERPROFILE || ""}\\.copilot`;
    const sessionId = process.env.SESSION_ID;
    if (!copilotHome || !sessionId) {
        return "";
    }
    return `${copilotHome}\\session-state\\${sessionId}\\files\\foundry-optimizer\\${jobId}`;
}

const artifactDir = defaultArtifactDir();

const keywordGroups = [
    {
        label: "Invoice evidence shape",
        terms: ["expert_evidence", "invoice_id", "schema", "json"],
        meaning: "Contract Policy Expert is being told to return the exact evidence packet shape for invoice review.",
        business: "Finance reviewers and downstream checks can compare invoice findings without parsing free-form prose.",
    },
    {
        label: "Cited contract evidence",
        terms: ["source_ref", "classification", "confidence", "claim", "supports"],
        meaning: "The answer should attach source references, confidence, and support/contradiction metadata to each contract or policy claim.",
        business: "Auditors can see why an invoice line is supported, unsupported, or risky.",
    },
    {
        label: "Missing-evidence handling",
        terms: ["unsupported", "gap", "missing", "conflict"],
        meaning: "The agent should call out missing clauses, conflicting policy, or evidence gaps instead of inventing an answer.",
        business: "Reduces false confidence when contract/policy evidence is incomplete.",
    },
    {
        label: "Contract/policy retrieval",
        terms: ["knowledge_base", "retrieve", "contract", "policy", "rate-card"],
        meaning: "The agent should search the knowledge base for contract terms, policy rules, rate cards, SKUs, lots, and supplier evidence before deciding.",
        business: "Findings are grounded in Ledgerfield/FoundryIQ source data, not generic model memory.",
    },
    {
        label: "Read-only finance boundary",
        terms: ["read-only", "do not approve", "do not reconcile", "writeback", "recovery"],
        meaning: "Contract Policy Expert should explain evidence only; it must not approve invoices, reconcile payments, trigger recovery, or write back to finance systems.",
        business: "Keeps the agent in an advisory review lane while humans or controlled systems make operational decisions.",
    },
];

function readJson(name) {
    const dir = artifactSourceDir();
    if (!dir) {
        throw new Error(`Optimizer artifact ${name} was not found in session artifacts or committed fixtures.`);
    }
    return JSON.parse(readFileSync(join(dir, name), "utf8"));
}

const requiredArtifacts = [
    "job.json",
    "baseline-config.json",
    candidateConfigFile,
    "baseline-results.json",
    candidateResultsFile,
];

function hasArtifacts(dir) {
    return Boolean(dir && requiredArtifacts.every((name) => existsSync(join(dir, name))));
}

function artifactSourceDir() {
    if (hasArtifacts(artifactDir)) {
        return artifactDir;
    }
    if (hasArtifacts(fixtureDir)) {
        return fixtureDir;
    }
    return "";
}

function artifactSourceDescription() {
    const dir = artifactSourceDir();
    if (!dir) {
        return "missing";
    }
    return dir === fixtureDir ? "committed sample fixtures" : "session artifact storage";
}

function artifactsAvailable() {
    return Boolean(artifactSourceDir());
}

function lineageStatus() {
    const dir = artifactSourceDir();
    const configPath = dir ? join(dir, candidateConfigFile) : null;
    return resolveLineageStatus({
        extensionDir,
        agent: agentName,
        operationId: jobId,
        componentKey: "prompt_config",
        currentFilePath: configPath,
    });
}

function loadComparison() {
    return {
        job: readJson("job.json"),
        baselineConfig: readJson("baseline-config.json"),
        candidateConfig: readJson(candidateConfigFile),
        baselineResults: readJson("baseline-results.json"),
        candidateResults: readJson(candidateResultsFile),
    };
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
}

function formatPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "not reported";
    }
    return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatScore(value) {
    return Number(value || 0).toFixed(4);
}

function formatShortScore(value) {
    return Number(value || 0).toFixed(3);
}

function lines(value) {
    return String(value ?? "").replace(/\r\n/g, "\n").split("\n");
}

function countTerm(text, term) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return (String(text).match(new RegExp(escaped, "gi")) ?? []).length;
}

function keywordScore(text, group) {
    return group.terms.reduce((sum, term) => sum + countTerm(text, term), 0);
}

function summarizeText(beforeText, afterText) {
    const beforeLines = lines(beforeText);
    const afterLines = lines(afterText);
    return {
        beforeChars: String(beforeText ?? "").length,
        afterChars: String(afterText ?? "").length,
        beforeLines: beforeLines.length,
        afterLines: afterLines.length,
        keywordRows: keywordGroups.map((group) => {
            const before = keywordScore(beforeText, group);
            const after = keywordScore(afterText, group);
            return { ...group, before, after, delta: after - before };
        }),
    };
}

function lineDiff(beforeText, afterText) {
    const before = lines(beforeText);
    const after = lines(afterText);
    const dp = Array.from({ length: before.length + 1 }, () => Array(after.length + 1).fill(0));
    for (let i = before.length - 1; i >= 0; i -= 1) {
        for (let j = after.length - 1; j >= 0; j -= 1) {
            dp[i][j] = before[i] === after[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
    }

    const rows = [];
    let i = 0;
    let j = 0;
    while (i < before.length && j < after.length) {
        if (before[i] === after[j]) {
            rows.push({ kind: "same", before: before[i], after: after[j], beforeLine: i + 1, afterLine: j + 1 });
            i += 1;
            j += 1;
        } else if (dp[i + 1][j] >= dp[i][j + 1]) {
            rows.push({ kind: "removed", before: before[i], after: "", beforeLine: i + 1, afterLine: "" });
            i += 1;
        } else {
            rows.push({ kind: "added", before: "", after: after[j], beforeLine: "", afterLine: j + 1 });
            j += 1;
        }
    }
    while (i < before.length) {
        rows.push({ kind: "removed", before: before[i], after: "", beforeLine: i + 1, afterLine: "" });
        i += 1;
    }
    while (j < after.length) {
        rows.push({ kind: "added", before: "", after: after[j], beforeLine: "", afterLine: j + 1 });
        j += 1;
    }
    return rows;
}

function changedHunks(beforeText, afterText, context = 2) {
    const diff = lineDiff(beforeText, afterText);
    const changed = diff.map((row, index) => (row.kind === "same" ? -1 : index)).filter((index) => index >= 0);
    if (changed.length === 0) {
        return [];
    }

    const ranges = [];
    for (const index of changed) {
        const start = Math.max(0, index - context);
        const end = Math.min(diff.length - 1, index + context);
        const previous = ranges.at(-1);
        if (previous && start <= previous.end + 1) {
            previous.end = Math.max(previous.end, end);
        } else {
            ranges.push({ start, end });
        }
    }

    return ranges.map((range) => diff.slice(range.start, range.end + 1));
}

function diffStats(beforeText, afterText) {
    const diff = lineDiff(beforeText, afterText);
    return {
        added: diff.filter((row) => row.kind === "added").length,
        removed: diff.filter((row) => row.kind === "removed").length,
        same: diff.filter((row) => row.kind === "same").length,
    };
}

function objectByName(items) {
    return new Map((items ?? []).map((item, index) => [item.name ?? item.function?.name ?? item.type ?? `item_${index + 1}`, item]));
}

function pretty(value) {
    return JSON.stringify(value ?? null, null, 2);
}

function skillBody(skill) {
    return skill?.body ?? skill?.content ?? pretty(skill);
}

function renderMetric(label, value, detail) {
    return `<article class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></article>`;
}

function renderMetricHelp() {
    return `<section class="metric-help card">
        <span><b>Quality</b> is the average evaluator score for grounding, citations, evidence shape, gap handling, and read-only behavior. This job reports scores and eval run IDs. It does not report pass thresholds.</span>
      </section>`;
}

function renderMissingArtifactsHtml() {
    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Optimizer review setup</title>
    <style>
      body {
        margin: 0;
        background: var(--background-color-default, #fff);
        color: var(--text-color-default, #1f2328);
        font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      }
      main { max-width: 720px; margin: 0 auto; padding: 24px; }
      .card {
        border: 1px solid var(--border-color-default, #d0d7de);
        border-radius: 12px;
        padding: 16px;
      }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { color: var(--text-color-muted, #57606a); line-height: 1.45; }
      code { font-family: var(--font-mono, "SFMono-Regular", Consolas, monospace); font-size: 12px; }
    </style>
  </head>
  <body>
    <main>
      <section class="card">
        <h1>Fetch optimizer artifacts first</h1>
        <p>This canvas reads Foundry optimizer payloads from session artifact storage. If those files are missing, it falls back to sanitized fixtures committed beside the extension.</p>
        <p>Expected session artifact folder:</p>
        <p><code>${escapeHtml(artifactDir || "(SESSION_ID or COPILOT_HOME not available)")}</code></p>
        <p>Committed fixture folder:</p>
        <p><code>${escapeHtml(fixtureDir)}</code></p>
        <p>Required files: <code>job.json</code>, <code>baseline-config.json</code>, <code>${candidateLabel}-config.json</code>, <code>baseline-results.json</code>, and <code>${candidateLabel}-results.json</code>.</p>
      </section>
    </main>
  </body>
</html>`;
}

function renderKeywordRows(summary) {
    const rows = summary.keywordRows
        .map((row) => {
            const emphasis =
                row.delta > 0
                    ? `+${row.delta}`
                    : row.delta < 0
                      ? `${row.delta}`
                      : "0";
            return `<tr>
                <th scope="row">${escapeHtml(row.label)}</th>
                <td class="num">${escapeHtml(String(row.before))}</td>
                <td class="num">${escapeHtml(String(row.after))}</td>
                <td class="num">${escapeHtml(emphasis)}</td>
                <td>${escapeHtml(row.meaning)} ${escapeHtml(row.business)}</td>
            </tr>`;
        })
        .join("");
    return `<table class="signal-table">
        <caption>Prompt emphasis</caption>
        <thead>
          <tr>
            <th>Behavior</th>
            <th>Base</th>
            <th>${escapeHtml(candidateLabel)}</th>
            <th>Delta</th>
            <th>Meaning</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
}

function renderHunks(title, beforeLabel, afterLabel, beforeText, afterText, open = false, id = "") {
    const hunks = changedHunks(beforeText, afterText);
    const stats = diffStats(beforeText, afterText);
    const summary = `${stats.added} added / ${stats.removed} removed`;
    const idAttr = id ? ` id="${escapeHtml(id)}"` : "";
    if (hunks.length === 0) {
        return `<details class="hunks"${idAttr}><summary>${escapeHtml(title)} <span>No changes</span></summary></details>`;
    }

    return `<details class="hunks" ${open ? "open" : ""}${idAttr}>
        <summary>${escapeHtml(title)} <span>${escapeHtml(summary)} in ${hunks.length} focused hunks</span></summary>
        <div class="diff-labels"><div>${escapeHtml(beforeLabel)}</div><div>${escapeHtml(afterLabel)}</div></div>
        ${hunks
            .map(
                (hunk, index) => `<section class="hunk">
                    <div class="hunk-title">Hunk ${index + 1}</div>
                    ${hunk
                        .map(
                            (row) => `<div class="diff-row ${row.kind}">
                              <pre><span>${escapeHtml(row.beforeLine)}</span>${escapeHtml(row.before)}</pre>
                              <pre><span>${escapeHtml(row.afterLine)}</span>${escapeHtml(row.after)}</pre>
                            </div>`,
                        )
                        .join("")}
                </section>`,
            )
            .join("")}
      </details>`;
}

function renderSurfaceCard({ title, beforeText, afterText, why, open = false, id = "", auditId = "", auditTitle = "Full text diff" }) {
    const summary = summarizeText(beforeText, afterText);
    const charDelta = summary.afterChars - summary.beforeChars;
    const lineDelta = summary.afterLines - summary.beforeLines;
    const idAttr = id ? ` id="${escapeHtml(id)}"` : "";
    return `<section class="surface card"${idAttr}>
        <div class="surface-head">
          <div>
            <h2>${escapeHtml(title)}</h2>
            <p>${escapeHtml(why)}</p>
          </div>
          <div class="surface-stat">
            <strong>${charDelta >= 0 ? "+" : ""}${charDelta.toLocaleString()}</strong>
            <span>chars</span>
            <strong>${lineDelta >= 0 ? "+" : ""}${lineDelta.toLocaleString()}</strong>
            <span>lines</span>
          </div>
        </div>
        ${renderKeywordRows(summary)}
        ${renderHunks(auditTitle, "Baseline", candidateLabel, beforeText, afterText, open, auditId)}
      </section>`;
}

function renderBusinessSummary() {
    return `<section class="business card" id="summary">
        <div class="section-head"><h2>What changed</h2><span>Review notes</span></div>
        <table class="review-table">
          <tbody>
            <tr>
              <th scope="row"><i class="mark mark-blue" aria-hidden="true"></i>Output</th>
              <td>Moved from a loose reviewer note to one strict evidence JSON object. Approval, hold, and dispute language are fenced off.</td>
            </tr>
            <tr>
              <th scope="row"><i class="mark mark-purple" aria-hidden="true"></i>Evidence</th>
              <td>Contract and policy claims now have to come from FoundryIQ context, especially <code>retrieved_context</code>.</td>
            </tr>
            <tr>
              <th scope="row"><i class="mark mark-yellow" aria-hidden="true"></i>Gaps</th>
              <td>Missing source documents, rate gaps, release status, and identifier-only references become controller checks.</td>
            </tr>
            <tr>
              <th scope="row"><i class="mark mark-green" aria-hidden="true"></i>Boundary</th>
              <td><code>decision</code> and <code>recommended_finance_action</code> stay null when the request says not to decide. No system action is claimed.</td>
            </tr>
          </tbody>
        </table>
      </section>`;
}

function renderSurfaceExplainer() {
    return `<section class="card explainer">
        <div class="section-head"><h2>Changed assets</h2><span>What candidate_14 actually changed</span></div>
        <table class="review-table compact">
          <tbody>
            <tr><th scope="row">Main prompt</th><td>Changed from loose triage guidance to a strict evidence JSON contract.</td></tr>
            <tr><th scope="row">Retrieval tool</th><td>Description tightened, and <code>query</code> became required.</td></tr>
            <tr><th scope="row">No change</th><td>Model, agent version, skills, and tool name stayed the same.</td></tr>
          </tbody>
        </table>
      </section>`;
}

function renderSkillCards(baselineSkills, candidateSkills) {
    const before = objectByName(baselineSkills);
    const after = objectByName(candidateSkills);
    const names = [...new Set([...before.keys(), ...after.keys()])];
    return names
        .map((name) => {
            const beforeSkill = before.get(name);
            const afterSkill = after.get(name);
            const why =
                name === "retrieval-discipline"
                    ? "Use this to review how evidence gathering changed."
                    : "Use this to review schema, read-only limits, and evidence metadata.";
            return renderSurfaceCard({
                title: `Skill: ${name}`,
                beforeText: skillBody(beforeSkill),
                afterText: skillBody(afterSkill),
                why,
                open: name === "read-only-evidence-contract",
            });
        })
        .join("");
}

function renderToolInventory(baselineTools, candidateTools) {
    const before = objectByName(baselineTools);
    const after = objectByName(candidateTools);
    const names = [...new Set([...before.keys(), ...after.keys()])];
    return `<section class="card" id="tool">
        <div class="section-head"><h2>Retrieval tool changes</h2><span>Description and schema</span></div>
        <p class="section-note">The tool name stayed the same. candidate_14 tightened how the tool is described and made the search query required.</p>
        <div class="inventory">
          ${names
              .map((name) => {
                  const beforeTool = before.get(name);
                  const afterTool = after.get(name);
                  const stats = diffStats(pretty(beforeTool), pretty(afterTool));
                  const changed = stats.added + stats.removed;
                  return `<article>
                    <h3>${escapeHtml(name)}</h3>
                    <p>${changed === 0 ? "No tool shape changed." : `${changed} tool shape lines changed.`}</p>
                    ${renderToolReadableDiff(beforeTool, afterTool)}
                    ${renderHunks("Full tool JSON diff", "Baseline", candidateLabel, pretty(beforeTool), pretty(afterTool), false)}
                  </article>`;
              })
              .join("")}
        </div>
      </section>`;
}

function toolFunction(tool) {
    return tool?.function ?? {};
}

function renderToolReadableDiff(beforeTool, afterTool) {
    const beforeFn = toolFunction(beforeTool);
    const afterFn = toolFunction(afterTool);
    const beforeDescription = String(beforeFn.description ?? "").trim();
    const afterDescription = String(afterFn.description ?? "").trim();
    const beforeRequired = beforeFn.parameters?.required ?? [];
    const afterRequired = afterFn.parameters?.required ?? [];
    const beforeProps = Object.keys(beforeFn.parameters?.properties ?? {});
    const afterProps = Object.keys(afterFn.parameters?.properties ?? {});
    const sameInputs = sameStringList(beforeProps, afterProps);
    const addedRequired = afterRequired.filter((field) => !beforeRequired.includes(field));
    const removedRequired = beforeRequired.filter((field) => !afterRequired.includes(field));
    const inputSummary = sameInputs
        ? `${beforeProps.join(", ") || "none"} (unchanged)`
        : `${beforeProps.join(", ") || "none"} changed to ${afterProps.join(", ") || "none"}`;
    const requiredSummary = addedRequired.length
        ? `${addedRequired.join(", ")} is now required`
        : removedRequired.length
          ? `${removedRequired.join(", ")} is no longer required`
          : `${afterRequired.join(", ") || "none"} (unchanged)`;
    const behaviorSummary =
        beforeDescription === afterDescription
            ? "Retrieval guidance unchanged."
            : "Retrieval guidance is stricter about source-grounded evidence and no business-system actions.";

    return `<div class="tool-readable">
        <table class="tool-summary">
          <tbody>
            <tr><th scope="row">Tool</th><td>${escapeHtml(beforeFn.name ?? afterFn.name ?? "unknown")} stayed in place.</td></tr>
            <tr><th scope="row">Input</th><td>${escapeHtml(inputSummary)}.</td></tr>
            <tr><th scope="row">Contract</th><td>${escapeHtml(requiredSummary)}.</td></tr>
            <tr><th scope="row">Behavior</th><td>${escapeHtml(behaviorSummary)}</td></tr>
          </tbody>
        </table>
        <details class="tool-full-copy">
          <summary>Full tool descriptions</summary>
          <div class="tool-copy-grid">
            <section>
              <strong>Baseline</strong>
              <p>${escapeHtml(beforeDescription || "No description.")}</p>
            </section>
            <section>
              <strong>${escapeHtml(candidateLabel)}</strong>
              <p>${escapeHtml(afterDescription || "No description.")}</p>
            </section>
          </div>
        </details>
      </div>`;
}

function sameStringList(left, right) {
    return left.length === right.length && left.every((value, index) => value === right[index]);
}

function renderLeaderboard(job, candidateResults) {
    const best = job?.result?.best;
    const candidates = [...(candidateResults.leaderboard ?? job?.result?.candidates ?? [])].sort(
        (a, b) => Number(b.avg_score || 0) - Number(a.avg_score || 0),
    );
    if (candidates.length === 0) return "";
    return `<section class="card" id="candidates">
        <div class="section-head"><h2>Candidate search</h2><span>${escapeHtml(job.id)} | winner chosen by score</span></div>
        <table class="leaderboard">
          <thead><tr><th>Rank</th><th>Candidate</th><th>Score</th><th>Status</th></tr></thead>
          <tbody>
          ${candidates
              .map((candidate, index) => {
                  const isBest = candidate.candidate_id === best;
                  const isBaseline = candidate.name === "baseline" || candidate.candidate_id === job?.result?.baseline;
                  return `<tr class="${isBest ? "winner" : ""}">
                    <td class="num">${index + 1}</td>
                    <td><strong>${escapeHtml(candidate.name || candidate.candidate_id)}</strong><br /><code>${escapeHtml(candidate.candidate_id)}</code></td>
                    <td class="num">${formatScore(candidate.avg_score)}</td>
                    <td>${isBest ? "winner" : isBaseline ? "baseline" : "candidate"}</td>
                  </tr>`;
              })
              .join("")}
          </tbody>
        </table>
      </section>`;
}

function renderDecisionStrip({ job, baselineResults, candidateResults, scoreLift, relativeLift, lineage }) {
    return `<section class="decision-strip" aria-label="Optimizer result summary">
        <div class="strip-score"><i class="mark mark-blue" aria-hidden="true"></i><span>Score</span><strong>${formatShortScore(baselineResults.avgScore)} to ${formatShortScore(candidateResults.avgScore)}</strong></div>
        <div class="strip-lift"><i class="mark mark-green" aria-hidden="true"></i><span>Lift</span><strong>+${scoreLift.toFixed(3)} (${relativeLift.toFixed(1)}%)</strong></div>
        <div class="strip-state"><i class="mark mark-yellow" aria-hidden="true"></i><span>Status</span><strong>${escapeHtml(job.status)} / ${escapeHtml(lineage.reviewStatus ?? "unreviewed")}</strong></div>
        <div class="strip-proof"><i class="mark mark-purple" aria-hidden="true"></i><span>Lineage</span><strong>${escapeHtml(lineage.status.replaceAll("_", "-"))}${lineage.hashIntegrity ? ", hash match" : ""}</strong></div>
      </section>`;
}

function renderLineageNote(lineage) {
    return `<details class="lineage-note">
        <summary>What lineage means</summary>
        <p>Reference-only means this is a saved review artifact, not proof of what is deployed. Hash match means the rendered candidate file matches the recorded snapshot.</p>
        <p>Snapshot <code>${escapeHtml(lineage.snapshotId ? lineage.snapshotId.slice(0, 12) : "not found")}</code>. Evidence file <code>${escapeHtml(lineage.referencePath ?? "not found")}</code>.</p>
      </details>`;
}

function renderHtml() {
    if (!artifactsAvailable()) {
        return renderMissingArtifactsHtml();
    }

    const { job, baselineConfig, candidateConfig, baselineResults, candidateResults } = loadComparison();
    const scoreLift = Number(candidateResults.avgScore || 0) - Number(baselineResults.avgScore || 0);
    const relativeLift = (scoreLift / Number(baselineResults.avgScore || 1)) * 100;
    const candidatesEvaluated = job?.result?.candidates?.length ?? candidateResults.leaderboard?.length ?? 0;
    const lineage = lineageStatus();

    return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Optimizer review</title>
    <style>
      :root {
        color-scheme: light dark;
        --surface: var(--background-color-default, #fff);
        --surface-muted: color-mix(in srgb, var(--background-color-default, #fff) 92%, var(--text-color-default, #1f2328));
        --border: var(--border-color-default, #d0d7de);
        --text: var(--text-color-default, #1f2328);
        --muted: var(--text-color-muted, #57606a);
        --blue: var(--true-color-blue, #0969da);
        --green: var(--true-color-green, #1a7f37);
        --red: var(--true-color-red, #cf222e);
        --yellow: var(--true-color-yellow, #9a6700);
        --purple: #8250df;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: var(--surface);
        color: var(--text);
        font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
        font-size: var(--text-body-medium, 14px);
      }
      main { max-width: 1180px; margin: 0 auto; padding: 20px 24px 36px; }
      h1, h2, h3 { margin: 0; }
      h1 { font-size: 20px; }
      h2 { font-size: 15px; }
      h3 { font-size: 14px; }
      p { margin: 3px 0 0; color: var(--muted); line-height: 1.35; }
      code, pre { font-family: var(--font-mono, "SFMono-Regular", Consolas, monospace); font-size: 12px; }
      header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 10px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border);
      }
      .meta { color: var(--muted); text-align: right; font-size: 12px; }
      .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 14px 0 0; border: 1px solid var(--border); border-bottom: 0; }
      .metric, .card {
        border: 1px solid var(--border);
        background: var(--surface);
      }
      .metric { padding: 10px 12px; border-width: 0 1px 1px 0; }
      .metric:last-child { border-right: 0; }
      .metric span, .surface-stat span { color: var(--muted); font-size: 12px; }
      .metric strong { display: block; margin-top: 2px; font-size: 18px; }
      .metric p { font-size: 12px; }
      .metric-help {
        margin-top: 0;
        padding: 8px 12px;
        color: var(--muted);
        font-size: 12px;
        border-top: 0;
      }
      .metric-help b { color: var(--text); }
      .decision-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin-top: 14px;
        border: 1px solid var(--border);
      }
      .decision-strip div {
        position: relative;
        padding: 10px 12px;
        border-right: 1px solid var(--border);
        border-top: 3px solid var(--border);
      }
      .decision-strip div:last-child { border-right: 0; }
      .decision-strip .strip-score { border-top-color: var(--blue); }
      .decision-strip .strip-lift { border-top-color: var(--green); }
      .decision-strip .strip-state { border-top-color: var(--yellow); }
      .decision-strip .strip-proof { border-top-color: var(--purple); }
      .decision-strip span {
        display: block;
        color: var(--muted);
        font-size: 12px;
        padding-left: 18px;
      }
      .decision-strip strong {
        display: block;
        margin-top: 2px;
        font-size: 17px;
        font-weight: 650;
        padding-left: 18px;
      }
      .mark {
        display: inline-block;
        width: 10px;
        height: 10px;
        margin-right: 8px;
        border: 2px solid currentColor;
        vertical-align: -1px;
      }
      .decision-strip .mark {
        position: absolute;
        top: 13px;
        left: 12px;
        margin-right: 0;
      }
      .mark-blue { color: var(--blue); border-radius: 50%; }
      .mark-green { color: var(--green); border-radius: 2px; }
      .mark-yellow { color: var(--yellow); width: 0; height: 0; border-left: 6px solid transparent; border-right: 6px solid transparent; border-bottom: 11px solid currentColor; border-top: 0; }
      .mark-purple { color: var(--purple); transform: rotate(45deg); border-radius: 2px; }
      .quick-nav {
        position: sticky;
        top: 0;
        z-index: 1;
        display: flex;
        gap: 14px;
        padding: 8px 0;
        margin-top: 10px;
        border-bottom: 1px solid var(--border);
        background: var(--surface);
        font-size: 12px;
      }
      .quick-nav a { color: var(--blue); text-decoration: none; }
      .quick-nav a:hover { text-decoration: underline; }
      .quiet-note {
        margin: 10px 0 0;
        color: var(--muted);
        font-size: 13px;
      }
      .lineage-note {
        margin-top: 10px;
        border: 1px solid var(--border);
        padding: 8px 12px;
        color: var(--muted);
        font-size: 12px;
      }
      .lineage-note summary {
        cursor: pointer;
        color: var(--text);
        font-weight: 600;
      }
      .lineage-note p { margin-top: 6px; }
      .card { margin-top: 14px; overflow: hidden; }
      .section-head, .surface-head {
        display: flex;
        justify-content: space-between;
        align-items: start;
        gap: 10px;
        padding: 9px 12px;
        border-bottom: 1px solid var(--border);
        background: var(--surface);
      }
      .section-head span { color: var(--muted); font-size: 12px; }
      .surface-stat {
        min-width: 104px;
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 2px 8px;
        text-align: right;
      }
      .surface-stat strong { font-size: 14px; }
      table { width: 100%; border-collapse: collapse; }
      caption {
        caption-side: top;
        padding: 8px 10px;
        color: var(--muted);
        text-align: left;
        font-size: 12px;
        font-weight: 600;
      }
      th, td { border-top: 1px solid var(--border); padding: 8px 10px; text-align: left; vertical-align: top; }
      thead th { color: var(--muted); font-size: 12px; font-weight: 600; background: var(--surface-muted); }
      tbody th { width: 150px; font-weight: 600; }
      .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
      .review-table td { line-height: 1.35; }
      .review-table tbody th {
        white-space: nowrap;
      }
      .review-table.compact tbody th { width: 120px; }
      .signal-table th:nth-child(1) { width: 170px; }
      .signal-table th:nth-child(2),
      .signal-table th:nth-child(3),
      .signal-table th:nth-child(4) { width: 72px; }
      details.hunks {
        border-top: 1px solid var(--border);
        background: color-mix(in srgb, var(--surface-muted) 45%, var(--surface));
      }
      details.hunks summary {
        cursor: pointer;
        padding: 9px 12px;
        font-weight: 600;
      }
      details.hunks summary span {
        color: var(--muted);
        font-size: 12px;
        font-weight: 400;
        margin-left: 8px;
      }
      .diff-labels, .diff-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
      }
      .diff-labels {
        color: var(--muted);
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        border-top: 1px solid var(--border);
        border-bottom: 1px solid var(--border);
      }
      .diff-labels div { padding: 8px 12px; }
      .hunk { margin: 8px; border: 1px solid var(--border); overflow: hidden; background: var(--surface); }
      .hunk-title { padding: 6px 9px; color: var(--muted); font-size: 12px; border-bottom: 1px solid var(--border); }
      .diff-row pre {
        margin: 0;
        min-height: 20px;
        padding: 2px 8px;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        border-top: 1px solid color-mix(in srgb, var(--border) 55%, transparent);
      }
      .diff-row pre:first-child { border-right: 1px solid var(--border); }
      .diff-row pre span {
        display: inline-block;
        width: 42px;
        margin-right: 8px;
        text-align: right;
        color: var(--muted);
        user-select: none;
      }
      .diff-row.added pre:last-child { background: color-mix(in srgb, var(--green) 12%, transparent); }
      .diff-row.removed pre:first-child { background: color-mix(in srgb, var(--red) 12%, transparent); }
      .diff-row.same pre { color: color-mix(in srgb, var(--text) 72%, var(--muted)); }
      .inventory {
        display: grid;
        grid-template-columns: 1fr;
        gap: 8px;
        padding: 10px;
      }
      .section-note {
        margin: 0;
        padding: 9px 12px;
        border-bottom: 1px solid var(--border);
        color: var(--muted);
        font-size: 13px;
      }
      .inventory article {
        border: 1px solid var(--border);
        overflow: hidden;
      }
      .inventory h3, .inventory p { padding: 8px 10px 0; }
      .tool-readable {
        padding: 10px;
        border-top: 1px solid var(--border);
      }
      .tool-copy-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }
      .tool-copy-grid section {
        border: 1px solid var(--border);
        padding: 9px;
        background: var(--surface);
      }
      .tool-copy-grid strong {
        display: block;
        margin-bottom: 5px;
      }
      .tool-copy-grid p {
        padding: 0;
        white-space: pre-wrap;
      }
      .tool-summary {
        width: 100%;
        border-collapse: collapse;
      }
      .tool-summary th, .tool-summary td {
        border-bottom: 1px solid var(--border);
        padding: 7px 0;
        text-align: left;
        vertical-align: top;
      }
      .tool-summary th {
        color: var(--muted);
        font-size: 12px;
        font-weight: 600;
        width: 96px;
      }
      .tool-full-copy {
        margin-top: 8px;
        border: 1px solid var(--border);
        background: var(--surface);
      }
      .tool-full-copy summary {
        cursor: pointer;
        padding: 8px 9px;
        color: var(--muted);
        font-size: 12px;
        font-weight: 600;
      }
      .tool-full-copy .tool-copy-grid {
        padding: 0 9px 9px;
      }
      .leaderboard code {
        display: block;
        margin-top: 2px;
        color: var(--muted);
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .leaderboard tr.winner td,
      .leaderboard tr.winner th { background: color-mix(in srgb, var(--green) 7%, var(--surface)); }
      .note {
        margin-top: 10px;
        border: 1px solid var(--border);
        padding: 9px 10px;
        color: var(--muted);
        background: var(--surface);
      }
      @media (max-width: 900px) {
        header, .diff-labels, .diff-row { grid-template-columns: 1fr; }
        .meta { text-align: left; }
        .diff-row pre:first-child { border-right: 0; }
        .decision-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .decision-strip div:nth-child(2) { border-right: 0; }
        .decision-strip div:nth-child(-n + 2) { border-bottom: 1px solid var(--border); }
      }
      @media (max-width: 560px) {
        main { padding: 12px; }
        .metrics, .tool-copy-grid, .decision-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .surface-head { display: grid; grid-template-columns: 1fr; }
        .surface-stat { text-align: left; grid-template-columns: auto 1fr auto 1fr; }
      }
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>Contract Policy Expert optimizer review</h1>
          <p>Foundry Agent Optimizer job. Baseline agent version ${escapeHtml(job.inputs?.agent?.agent_version ?? "unknown")} to ${candidateLabel}.</p>
        </div>
        <div class="meta">
          <div>Status <strong>${escapeHtml(job.status)}</strong></div>
          <div>${lineageBadgeHtml(lineage.status, lineage.reviewStatus ? `review: ${lineage.reviewStatus}` : undefined)}</div>
          <div>Baseline <code>${escapeHtml(baselineId.slice(0, 18))}...</code></div>
          <div>${candidateLabel} <code>${escapeHtml(candidateId.slice(0, 18))}...</code></div>
        </div>
      </header>

      ${renderDecisionStrip({ job, baselineResults, candidateResults, scoreLift, relativeLift, lineage })}
      <nav class="quick-nav" aria-label="Review sections">
        <a href="#summary">Summary</a>
        <a href="#candidates">Candidates</a>
        <a href="#instructions">Main prompt</a>
        <a href="#tool">Tool</a>
        <a href="#audit">Full diff</a>
      </nav>
      <p class="quiet-note">Start with Changed assets. Open full diffs only when you need audit detail.</p>
      ${renderLineageNote(lineage)}

      ${renderBusinessSummary()}
      ${renderLeaderboard(job, candidateResults)}
      ${renderSurfaceExplainer()}

      ${renderSurfaceCard({
          title: "Main prompt changes",
          beforeText: baselineConfig.instructions,
          afterText: candidateConfig.instructions,
          why: "This is the primary behavior contract for invoice evidence review.",
          id: "instructions",
          auditId: "audit",
          auditTitle: "Full main prompt diff",
          open: false,
      })}
      ${renderSkillCards(baselineConfig.skills, candidateConfig.skills)}
      ${renderToolInventory(baselineConfig.tools, candidateConfig.tools)}

      <div class="note">Loaded from ${escapeHtml(artifactSourceDescription())}: <code>${escapeHtml(artifactSourceDir())}</code></div>
      <div class="note">Lineage evidence: <code>${escapeHtml(lineage.referencePath ?? "not found")}</code>${lineage.snapshotId ? ` (snapshot <code>${escapeHtml(lineage.snapshotId.slice(0, 12))}...</code>)` : ""}</div>
    </main>
  </body>
</html>`;
}

function comparisonSummary() {
    const lineage = lineageStatus();
    if (!artifactsAvailable()) {
        return {
            jobId,
            status: "missing_artifacts",
            artifactDir,
            fixtureDir,
            requiredFiles: requiredArtifacts,
            lineage,
        };
    }

    const { job, baselineConfig, candidateConfig, baselineResults, candidateResults } = loadComparison();
    return {
        jobId,
        status: job.status,
        source: artifactSourceDescription(),
        sourceDir: artifactSourceDir(),
        lineage,
        baseline: {
            id: baselineId,
            model: baselineConfig.model,
            score: baselineResults.avgScore,
            passRate: baselineResults.passRate,
        },
        candidate: {
            label: candidateLabel,
            id: candidateId,
            model: candidateConfig.model,
            score: candidateResults.avgScore,
            passRate: candidateResults.passRate,
            mutations: candidateResults.mutations ?? {},
            evalRunId: candidateResults.evalRunId,
        },
        leaderboard: candidateResults.leaderboard ?? job?.result?.candidates ?? [],
        reviewModel: "actual-optimizer-job-with-score-path-and-focused-hunks",
    };
}

async function startServer() {
    const server = createServer((req, res) => {
        if (req.url === "/state.json") {
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(JSON.stringify(comparisonSummary(), null, 2));
            return;
        }
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(renderHtml());
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    return { server, url: `http://127.0.0.1:${port}/` };
}

await joinSession({
    canvases: [
        createCanvas({
            id: "optimizer-diff",
            displayName: "Optimizer Diff",
            description: `Compare Foundry-fetched Agent Optimizer baseline and ${candidateLabel} configs/results.`,
            actions: [
                {
                    name: "get_comparison",
                    description: "Return the sanitized Foundry-fetched optimizer comparison summary.",
                    handler: async () => comparisonSummary(),
                },
            ],
            open: async (ctx) => {
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer();
                    servers.set(ctx.instanceId, entry);
                }
                return {
                    title: "Optimizer review",
                    status: `${jobId} | baseline to ${candidateLabel}`,
                    url: entry.url,
                };
            },
            onClose: async (ctx) => {
                const entry = servers.get(ctx.instanceId);
                if (entry) {
                    servers.delete(ctx.instanceId);
                    await new Promise((resolve) => entry.server.close(() => resolve()));
                }
            },
        }),
    ],
});
