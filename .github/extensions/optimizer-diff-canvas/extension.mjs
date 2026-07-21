import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { joinSession, createCanvas } from "@github/copilot-sdk/extension";
import { lineageBadgeHtml, resolveLineageStatus } from "../shared/lineage-evidence.mjs";

const jobId = "opt_994a956b2d6e49939506323a15dfc5d2";
const baselineId = "cand_bc834224066e45d8938aa2fa738a9720";
const candidateId = "cand_6bf6980ed16f4538ba0faf8935d93c01";
const agentName = "contract-policy-expert";
const extensionDir = dirname(fileURLToPath(import.meta.url));
const fixtureDir = join(extensionDir, "fixtures", jobId);
const servers = new Map();

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
    "candidate_4-config.json",
    "baseline-results.json",
    "candidate_4-results.json",
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
    const configPath = dir ? join(dir, "candidate_4-config.json") : null;
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
        candidateConfig: readJson("candidate_4-config.json"),
        baselineResults: readJson("baseline-results.json"),
        candidateResults: readJson("candidate_4-results.json"),
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
    return `${(Number(value || 0) * 100).toFixed(1)}%`;
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
        <span><b>Quality:</b> Average rubric score for grounding, citations, evidence shape, gaps, and read-only behavior. <b>Passing rows:</b> cleared the threshold; 100% pass rate is not a perfect 1.0 score.</span>
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
        <p>This committed canvas first reads Foundry optimizer payloads from session artifact storage. If those are unavailable, it uses sanitized sample fixtures committed beside the extension.</p>
        <p>Expected session artifact folder:</p>
        <p><code>${escapeHtml(artifactDir || "(SESSION_ID or COPILOT_HOME not available)")}</code></p>
        <p>Committed fixture folder:</p>
        <p><code>${escapeHtml(fixtureDir)}</code></p>
        <p>Required files: <code>job.json</code>, <code>baseline-config.json</code>, <code>candidate_4-config.json</code>, <code>baseline-results.json</code>, and <code>candidate_4-results.json</code>.</p>
      </section>
    </main>
  </body>
</html>`;
}

function renderKeywordRows(summary) {
    return summary.keywordRows
        .map((row) => {
            const polarity = row.delta > 0 ? "up" : row.delta < 0 ? "down" : "flat";
            const emphasis =
                row.delta > 0
                    ? `More emphasis (+${row.delta})`
                    : row.delta < 0
                      ? `Less emphasis (${row.delta})`
                      : "Same emphasis";
            return `<article class="signal-card">
                <div class="signal-top">
                  <strong>${escapeHtml(row.label)}</strong>
                  <span class="delta ${polarity}">${escapeHtml(emphasis)}</span>
                </div>
                <p>${escapeHtml(row.meaning)}</p>
                <small>${escapeHtml(row.business)}</small>
                <em>Keyword mentions in source text: baseline ${row.before}, candidate_4 ${row.after}</em>
            </article>`;
        })
        .join("");
}

function renderHunks(title, beforeLabel, afterLabel, beforeText, afterText, open = false) {
    const hunks = changedHunks(beforeText, afterText);
    const stats = diffStats(beforeText, afterText);
    const summary = `${stats.added} added / ${stats.removed} removed`;
    if (hunks.length === 0) {
        return `<details class="hunks"><summary>${escapeHtml(title)} <span>No changes</span></summary></details>`;
    }

    return `<details class="hunks" ${open ? "open" : ""}>
        <summary>${escapeHtml(title)} <span>${escapeHtml(summary)} across ${hunks.length} focused hunks</span></summary>
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

function renderSurfaceCard({ title, beforeText, afterText, why, open = false }) {
    const summary = summarizeText(beforeText, afterText);
    const charDelta = summary.afterChars - summary.beforeChars;
    const lineDelta = summary.afterLines - summary.beforeLines;
    return `<section class="surface card">
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
        <div class="signal-grid">${renderKeywordRows(summary)}</div>
        ${renderHunks("Focused raw hunks", "Baseline", "candidate_4", beforeText, afterText, open)}
      </section>`;
}

function renderBusinessSummary() {
    return `<section class="business card">
        <div class="section-head"><h2>Contract Policy Expert takeaway</h2><span>Read this before the technical diff</span></div>
        <div class="takeaways">
          <article>
            <strong>Better invoice challenge support</strong>
            <p>Candidate_4 is more explicit about producing evidence packets that explain whether invoice charges are supported by contract and policy data.</p>
          </article>
          <article>
            <strong>Grounded in contract/policy sources</strong>
            <p>The optimized candidate pushes harder on retrieving contract clauses, rate cards, supplier terms, policy rules, and prior findings before answering.</p>
          </article>
          <article>
            <strong>Clearer “we do not know” behavior</strong>
            <p>It emphasizes unsupported and missing-evidence reporting, so the agent should flag gaps instead of acting certain when source data is thin.</p>
          </article>
          <article>
            <strong>Still advisory, not operational</strong>
            <p>The candidate keeps the agent in a read-only reviewer role: explain evidence, but do not approve, reconcile, recover, or update finance systems.</p>
          </article>
        </div>
      </section>`;
}

function renderSurfaceExplainer() {
    return `<section class="card explainer">
        <div class="section-head"><h2>What changed surfaces mean</h2><span>Instructions vs. skills</span></div>
        <div class="takeaways">
          <article>
            <strong>Instructions = overall job description</strong>
            <p>The broad rules for Contract Policy Expert: what role it plays, what kind of answer to produce, and what boundaries it must follow.</p>
          </article>
          <article>
            <strong>Skills = procedural playbooks</strong>
            <p>Reusable checklists the agent follows for specific work, like retrieving contract/policy evidence or enforcing the invoice evidence shape.</p>
          </article>
        </div>
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
                    ? "Most useful for reviewing how the optimizer changed evidence gathering behavior."
                    : "Most useful for reviewing output schema, read-only limits, and evidence metadata requirements.";
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
    return `<section class="card">
        <div class="section-head"><h2>Tools: inventory diff</h2><span>Check this after instructions/skills</span></div>
        <div class="inventory">
          ${names
              .map((name) => {
                  const beforeTool = before.get(name);
                  const afterTool = after.get(name);
                  const stats = diffStats(pretty(beforeTool), pretty(afterTool));
                  const changed = stats.added + stats.removed;
                  return `<article>
                    <h3>${escapeHtml(name)}</h3>
                    <p>${changed === 0 ? "No tool-shape change." : `${changed} changed tool-shape lines.`}</p>
                    ${renderHunks("Tool shape hunks", "Baseline", "candidate_4", pretty(beforeTool), pretty(afterTool), false)}
                  </article>`;
              })
              .join("")}
        </div>
      </section>`;
}

function renderHtml() {
    if (!artifactsAvailable()) {
        return renderMissingArtifactsHtml();
    }

    const { job, baselineConfig, candidateConfig, baselineResults, candidateResults } = loadComparison();
    const scoreLift = Number(candidateResults.avgScore || 0) - Number(baselineResults.avgScore || 0);
    const passLift = Number(candidateResults.passRate || 0) - Number(baselineResults.passRate || 0);
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
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        background: var(--surface);
        color: var(--text);
        font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
        font-size: var(--text-body-medium, 14px);
      }
      main { max-width: 1320px; margin: 0 auto; padding: 20px; }
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
      .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
      .metric, .card {
        border: 1px solid var(--border);
        border-radius: 12px;
        background: var(--surface);
        box-shadow: 0 1px 2px rgb(0 0 0 / 5%);
      }
      .metric { padding: 9px 10px; }
      .metric span, .surface-stat span { color: var(--muted); font-size: 12px; }
      .metric strong { display: block; margin-top: 2px; font-size: 18px; }
      .metric p { font-size: 12px; }
      .metric-help {
        margin-top: -2px;
        padding: 7px 10px;
        color: var(--muted);
        font-size: 12px;
      }
      .metric-help b { color: var(--text); }
      .guide { padding: 11px 12px; margin-bottom: 10px; border-left: 4px solid var(--blue); }
      .guide ol { margin: 7px 0 0; padding-left: 18px; color: var(--muted); display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 16px; }
      .guide li { margin: 2px 0; }
      .card { margin-top: 10px; overflow: hidden; }
      .section-head, .surface-head {
        display: flex;
        justify-content: space-between;
        align-items: start;
        gap: 10px;
        padding: 10px 12px;
        border-bottom: 1px solid var(--border);
        background: var(--surface-muted);
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
      .signal-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding: 10px;
      }
      .signal-card {
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 9px;
        background: color-mix(in srgb, var(--surface-muted) 45%, var(--surface));
      }
      .signal-top { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
      .signal-card p { font-size: 12px; }
      .signal-card small { display: block; margin-top: 5px; color: var(--text); line-height: 1.3; }
      .signal-card em { display: block; margin-top: 5px; color: var(--muted); font-size: 11px; font-style: normal; }
      .delta {
        display: inline-block;
        min-width: max-content;
        border-radius: 999px;
        padding: 1px 7px;
        text-align: center;
        border: 1px solid var(--border);
        font-size: 12px;
      }
      .delta.up { color: var(--green); border-color: color-mix(in srgb, var(--green) 35%, var(--border)); }
      .delta.down { color: var(--red); border-color: color-mix(in srgb, var(--red) 35%, var(--border)); }
      .delta.flat { color: var(--muted); }
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
      .hunk { margin: 8px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
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
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding: 10px;
      }
      .inventory article {
        border: 1px solid var(--border);
        border-radius: 10px;
        overflow: hidden;
      }
      .inventory h3, .inventory p { padding: 8px 10px 0; }
      .takeaways {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding: 10px;
      }
      .takeaways article {
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 10px;
        background: color-mix(in srgb, var(--surface-muted) 45%, var(--surface));
      }
      .takeaways p { font-size: 12px; }
      .note {
        margin-top: 10px;
        border: 1px solid color-mix(in srgb, var(--blue) 35%, var(--border));
        border-radius: 12px;
        padding: 9px 10px;
        color: var(--muted);
        background: color-mix(in srgb, var(--blue) 7%, var(--surface));
      }
      @media (max-width: 900px) {
        header, .diff-labels, .diff-row { grid-template-columns: 1fr; }
        .meta { text-align: left; }
        .diff-row pre:first-child { border-right: 0; }
      }
      @media (max-width: 560px) {
        main { padding: 12px; }
        .metrics, .guide ol, .takeaways, .signal-grid, .inventory { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
          <p>Did candidate_4 make this agent better at contract-grounded invoice evidence review?</p>
        </div>
        <div class="meta">
          <div>Status <strong>${escapeHtml(job.status)}</strong></div>
          <div>${lineageBadgeHtml(lineage.status, lineage.reviewStatus ? `review: ${lineage.reviewStatus}` : undefined)}</div>
          <div>Baseline <code>${escapeHtml(baselineId.slice(0, 18))}...</code></div>
          <div>candidate_4 <code>${escapeHtml(candidateId.slice(0, 18))}...</code></div>
        </div>
      </header>

      <section class="metrics">
        ${renderMetric("Baseline quality", Number(baselineResults.avgScore || 0).toFixed(4), `${formatPercent(baselineResults.passRate)} rows passing threshold`)}
        ${renderMetric("candidate_4 quality", Number(candidateResults.avgScore || 0).toFixed(4), `${formatPercent(candidateResults.passRate)} rows passing threshold`)}
        ${renderMetric("Quality-score lift", `+${scoreLift.toFixed(4)}`, `${((scoreLift / Number(baselineResults.avgScore || 1)) * 100).toFixed(1)}% relative`)}
        ${renderMetric("Pass-threshold lift", `+${(passLift * 100).toFixed(1)} pts`, `${formatPercent(baselineResults.passRate)} → ${formatPercent(candidateResults.passRate)} rows passing`)}
      </section>
      ${renderMetricHelp()}

      <section class="guide card">
        <h2>How to read the signal for this agent</h2>
        <ol>
          <li><strong>More emphasis</strong> means candidate_4 talks more about a behavior Contract Policy Expert needs for invoice evidence review.</li>
          <li><strong>Same emphasis</strong> means the topic was already present; wording may still be different in the raw hunks.</li>
          <li><strong>Best first read:</strong> takeaway cards, then signal cards, then raw hunks only when someone needs audit detail.</li>
          <li><strong>The headline:</strong> candidate_4 made the agent more specific about retrieved contract evidence, missing-evidence gaps, strict evidence shape, and read-only boundaries.</li>
        </ol>
      </section>

      ${renderBusinessSummary()}
      ${renderSurfaceExplainer()}

      ${renderSurfaceCard({
          title: "Instructions: overall job description",
          beforeText: baselineConfig.instructions,
          afterText: candidateConfig.instructions,
          why: "Top-level behavior contract for invoice evidence review. Raw line hunks are collapsed because the prompt is large.",
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
        candidate4: {
            id: candidateId,
            model: candidateConfig.model,
            score: candidateResults.avgScore,
            passRate: candidateResults.passRate,
            mutations: candidateResults.mutations ?? {},
        },
        reviewModel: "semantic-summary-first-with-collapsed-focused-hunks",
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
            description: "Compare Foundry-fetched Agent Optimizer baseline and candidate_4 configs/results.",
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
                    status: "Semantic diff with collapsed raw hunks",
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
