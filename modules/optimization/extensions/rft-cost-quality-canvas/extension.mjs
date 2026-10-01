// Extension: rft-cost-quality-canvas
// RFT cost and quality comparison canvas with interactive cost slider.

import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { joinSession, createCanvas } from "@github/copilot-sdk/extension";
import { lineageBadgeHtml, resolveLineageStatus } from "../shared/lineage-evidence.mjs";

const servers = new Map();
const extensionDir = dirname(fileURLToPath(import.meta.url));
const agentName = "contract-policy-expert";
// The MAI RFT serving deployment reuses the accepted candidate_14 optimized
// assets; the committed fixture config is what we re-hash here.
const goldenConfigPath = join(
    extensionDir,
    "..",
    "optimizer-diff-canvas",
    "fixtures",
    "opt_2fb58fc1723e461d9a1496907d029ac8",
    "candidate_14-config.json",
);

const metrics = {
    headline: "RFT moves the optimized agent from gpt-6-astra to MAI.",
    talkTrack:
        "The fresh Foundry replay starts from a deliberately mediocre baseline, applies candidate_14, then swaps only the model deployment to the MAI RFT model. Optimized passed 120/120 rows. Tuned MAI passed 119/120; the miss was a rubric-quality item, not infrastructure.",
    baselineFoundryMean: "61.7%",
    optimizedFoundryMean: "100%",
    tunedFoundryMean: "99.2%",
    baselineAgentVersion: "6",
    optimizedAgentVersion: "7",
    tunedAgentVersion: "10",
    baselineFoundryEvalId: "eval_2d5a13a976c14355aee3317f87e5e171",
    optimizedFoundryEvalId: "eval_9421539dcd754815b8c5443bca0e971c",
    tunedFoundryEvalId: "eval_4031396f93ac47418b78477ab712fd7e",
    baselinePassCounts: "16/24, 15/24, 11/24, 14/24, 18/24",
    optimizedPassCounts: "24/24, 24/24, 24/24, 24/24, 24/24",
    tunedPassCounts: "24/24, 24/24, 24/24, 23/24, 24/24",
    optimizerCandidateScore: 0.8000013333333332,
    optimizerBaselineScore: 0.455684,
    optimizerCandidatePassRate: "winner by score",
    tokenCostBasis:
        "Estimated cost using published Azure Global Standard token rates: GPT-6 Astra at $10 input / $50 output per 1M tokens and Microsoft Code 1.1 Flash at $0.20 input / $1.20 output per 1M tokens. Foundry hosted-agent eval usage fields reported zero, so token volume uses local o200k_base counts from actual eval input text and final assistant output text across five 24-row runs. This is an estimate before discounts, taxes, cache effects, tools, hosting, and provisioned-capacity charges.",
    artifactArchiveNote:
        "Raw eval output-items and run payloads are archived outside the repo; this canvas keeps commit-safe IDs and aggregate counts.",
    optimizerJob: "opt_2fb58fc1723e461d9a1496907d029ac8",
    optimizerCandidate: "candidate_14 / cand_opt_2fb58fc1723e461d9a1496907d029ac8_0014",
    optimizedFoundryRunId: "five sequential native Foundry eval runs",
    optimizedForgeVersion: "7",
    rftJob: "ftjob-44f31c01823d4e13a213dddf0d22fb55",
    rftDeployment: "contract-policy-expert-mai-rft-v2-pt09",
    fineTunedModel: "mai-code-1.1-flash-2026-08-27.ft-44f31c01823d4e13a213dddf0d22fb55-cpe-v2-pt09",
    costStatus: "Token estimate",
    observedRequestCount: 120,
    usageUnitSize: 10000,
    tokenOptions: [
        {
            id: "optimized",
            label: "Astra",
            model: "gpt-6-astra",
            inputTokens: 118530,
            outputTokens: 164282,
            inputPricePerMillion: 10.0,
            outputPricePerMillion: 50.0,
            quality: "120/120 passed rows",
        },
        {
            id: "tuned",
            label: "Tuned MAI",
            model: "contract-policy-expert-mai-rft-v2-pt09",
            inputTokens: 118530,
            outputTokens: 178656,
            inputPricePerMillion: 0.2,
            outputPricePerMillion: 1.2,
            quality: "119/120 passed rows",
        },
    ],
    comparisonRows: [
        {
            area: "Foundry agent mean",
            baseline: "61.7% over five 24-row runs",
            optimized: "100% over five 24-row runs",
            tuned: "99.2% over five 24-row runs",
            takeaway: "Tuned MAI stays within one row of optimized.",
        },
        {
            area: "Run spread",
            baseline: "11/24 to 18/24",
            optimized: "24/24 every run",
            tuned: "23/24 to 24/24",
            takeaway: "The optimized assets remove the noisy baseline behavior.",
        },
        {
            area: "Optimizer candidate",
            baseline: "Optimizer train score 0.456",
            optimized: "candidate_14 train score 0.800",
            tuned: "Same optimized assets",
            takeaway: "Optimizer changed instructions and the retrieval tool contract.",
        },
        {
            area: "Applied assets eval",
            baseline: "Agent v6, eval_2d5a...",
            optimized: "Agent v7, eval_9421...",
            tuned: "Agent v10, eval_4031...",
            takeaway: "All three are hosted-agent evals with the same held-out dataset and rubric.",
        },
        {
            area: "Behavior target",
            baseline: "Loose triage evidence behavior",
            optimized: "Strict evidence JSON from candidate_14",
            tuned: "Same behavior target",
            takeaway: "RFT is a model swap after the optimizer fixed the behavior.",
        },
        {
            area: "Model",
            baseline: "gpt-6-astra",
            optimized: "gpt-6-astra",
            tuned: "MAI fine-tuned deployment",
            takeaway: "The tuned run swaps the model from gpt-6-astra to the MAI RFT deployment.",
        },
        {
            area: "RFT job",
            baseline: "Not applicable",
            optimized: "Not applicable",
            tuned: "ftjob-44f31c01823d4e13a213dddf0d22fb55",
            takeaway: "This is the preserved successful MAI RFT job.",
        },
        {
            area: "Fine-tuned model",
            baseline: "Not applicable",
            optimized: "Not applicable",
            tuned: "mai-code-1.1-flash-2026-08-27.ft-44f31...-cpe-v2-pt09",
            takeaway: "Deployable MAI contract-policy expert model.",
        },
        {
            area: "RFT deployment",
            baseline: "Not applicable",
            optimized: "Not applicable",
            tuned: "contract-policy-expert-mai-rft-v2-pt09",
            takeaway: "Serving comparison uses the tuned deployment.",
        },
        {
            area: "Cost evidence",
            baseline: "Not modeled",
            optimized: "~988 input + ~1,369 output tokens/request",
            tuned: "~988 input + ~1,489 output tokens/request",
            takeaway: "Uses published Global Standard token rates; actual bill can differ by discount, cache, tools, hosting, or capacity model.",
        },
    ],
};

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function jsonScript(value) {
    return JSON.stringify(value).replaceAll("<", "\\u003c");
}

function rftLineageStatus() {
    return resolveLineageStatus({
        extensionDir,
        agent: agentName,
        operationId: metrics.rftJob,
        componentKey: "prompt_config",
        currentFilePath: goldenConfigPath,
    });
}

function renderDecisionStrip(lineage) {
    return `<section class="decision-strip" aria-label="RFT result summary">
        <div class="strip-score"><i class="mark mark-blue" aria-hidden="true"></i><span>Baseline</span><strong>${escapeHtml(metrics.baselineFoundryMean)}</strong></div>
        <div class="strip-lift"><i class="mark mark-green" aria-hidden="true"></i><span>Optimized</span><strong>${escapeHtml(metrics.optimizedFoundryMean)}</strong></div>
        <div class="strip-state"><i class="mark mark-yellow" aria-hidden="true"></i><span>Tuned MAI</span><strong>${escapeHtml(metrics.tunedFoundryMean)}</strong></div>
        <div class="strip-proof"><i class="mark mark-purple" aria-hidden="true"></i><span>Cost</span><strong>${escapeHtml(metrics.costStatus)}</strong></div>
      </section>
      <details class="lineage-note">
        <summary>What lineage means</summary>
        <p>Reference-only means this is a saved review artifact, not proof of what is deployed now. Hash match means the rendered optimized config matches the recorded snapshot.</p>
        <p>Snapshot <code>${escapeHtml(lineage.snapshotId ? lineage.snapshotId.slice(0, 12) : "not found")}</code>. Evidence file <code>${escapeHtml(lineage.referencePath ?? "not found")}</code>.</p>
      </details>`;
}

function sendJson(res, value) {
    res.writeHead(200, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
    });
    res.end(JSON.stringify(value));
}

function renderHtml(instanceId) {
    const lineage = rftLineageStatus();
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RFT Cost Quality</title>
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
      --yellow: var(--true-color-yellow, #9a6700);
      --purple: #8250df;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--surface);
      color: var(--text);
      font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      font-size: var(--text-body-medium, 14px);
      line-height: var(--leading-body-medium, 20px);
    }
    main {
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 20px 24px 36px;
    }
    .hero {
      display: grid;
      gap: 6px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 12px;
    }
    .eyebrow {
      color: var(--text-color-muted);
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0;
      max-width: 980px;
      font-family: var(--font-sans-display, var(--font-sans));
      font-size: 20px;
      font-weight: var(--font-weight-semibold, 700);
      letter-spacing: -0.02em;
      line-height: 1.15;
    }
    .hero p {
      max-width: 960px;
      margin: 0;
      color: var(--text-color-muted);
      font-size: 14px;
      line-height: 20px;
    }
    .thesis {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.7fr);
      gap: 12px;
      margin: 14px 0;
    }
    .proof {
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--background-color-muted);
      padding: 12px 14px;
    }
    .proof-title {
      color: var(--text-color-muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .proof-line {
      display: flex;
      gap: 14px;
      align-items: center;
      margin-top: 8px;
    }
    .proof-model {
      flex: 1;
      min-width: 0;
      padding: 12px;
      border: 1px solid var(--border-color-default);
      border-radius: 0.625rem;
      background: var(--control-transparent-bg-rest);
    }
    .proof-equals {
      color: var(--text-color-muted);
      font-size: 34px;
      font-weight: 700;
      line-height: 1;
    }
    .model-name {
      font-size: 13px;
      font-weight: 700;
    }
    .model-proof {
      color: var(--text-color-muted);
      font-size: 12px;
      margin-top: 4px;
    }
    .section-block {
      display: grid;
      gap: 6px;
      margin: 10px 0;
    }
    .evidence-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin: 10px 0 12px;
    }
    .evidence-card {
      min-width: 0;
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--background-color-muted);
      padding: 10px;
    }
    .evidence-card h2 {
      margin: 4px 0 6px;
      font-size: 15px;
      line-height: 19px;
    }
    .evidence-card p {
      margin: 0;
      color: var(--text-color-muted);
      font-size: 12px;
      line-height: 17px;
    }
    .link-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin: 0 0 12px;
      font-size: 12px;
    }
    a {
      color: var(--text-color-accent, var(--color-focus-outline));
      text-decoration: none;
    }
    a:hover {
      text-decoration: underline;
    }
    .mono-truncate {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: var(--text-code-inline, 12px);
    }
    .section-label {
      color: var(--text-color-muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .compare-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(140px, 1fr));
      gap: 8px;
    }
    .compare-grid.three-up {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .agent-card,
    .performance-card {
      border: 1px solid var(--border);
      border-top: 3px solid var(--border);
      background: var(--surface);
      padding: 10px 12px;
    }
    .compare-grid article:nth-child(1) { border-top-color: var(--blue); }
    .compare-grid article:nth-child(2) { border-top-color: var(--green); }
    .compare-grid article:nth-child(3) { border-top-color: var(--yellow); }
    .agent-label,
    .metric-label {
      color: var(--text-color-muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .agent-card h2 {
      margin: 6px 0 6px;
      font-size: 16px;
      letter-spacing: -0.02em;
      line-height: 20px;
    }
    .agent-model {
      display: inline-block;
      margin: 0 0 8px;
      padding: 3px 6px;
      border: 1px solid var(--border);
      background: var(--control-transparent-bg-rest);
      font-family: var(--font-mono);
      font-size: var(--text-code-inline, 12px);
    }
    .agent-card p,
    .performance-card p {
      margin: 0;
      color: var(--text-color-muted);
      font-size: 12px;
      line-height: 17px;
    }
    .source {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--border-color-default);
      color: var(--text-color-muted);
      font-size: 12px;
      line-height: 17px;
    }
    .metric-value {
      margin: 6px 0 4px;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.04em;
      line-height: 26px;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin: 0;
    }
    .card,
    .table-wrap,
    .callout {
      border: 1px solid var(--border);
      background: var(--surface);
    }
    .card {
      padding: 12px;
    }
    .card .label {
      color: var(--text-color-muted);
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 4px;
    }
    .card .value {
      color: var(--text-color-default);
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 30px;
    }
    .card .note {
      margin-top: 4px;
      color: var(--text-color-muted);
      font-size: 12px;
    }
    .layout {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
      align-items: start;
    }
    .table-wrap {
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 12px;
    }
    th,
    td {
      padding: 10px;
      border-bottom: 1px solid var(--border-color-default);
      text-align: left;
      vertical-align: top;
    }
    th {
      background: var(--control-transparent-bg-rest);
      color: var(--text-color-muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    tr:last-child td {
      border-bottom: 0;
    }
    td:first-child {
      width: 18%;
      font-weight: 700;
    }
    td {
      overflow: hidden;
      text-overflow: ellipsis;
    }
    td:not(:first-child) {
      max-width: none;
      white-space: normal;
    }
    .takeaway {
      color: var(--text-color-muted);
    }
    .panel {
      display: grid;
      gap: 16px;
    }
    .slider-card {
      border: 1px solid var(--border);
      border-top: 3px solid var(--purple);
      background: var(--surface);
      padding: 12px;
      margin: 12px 0;
    }
    .slider-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .slider-head h2 {
      margin: 0;
      font-size: 18px;
      letter-spacing: -0.02em;
    }
    .volume {
      color: var(--text-color-muted);
      font-family: var(--font-mono);
      font-size: 13px;
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--control-checked-bg-rest);
    }
    .range-labels {
      display: flex;
      justify-content: space-between;
      color: var(--text-color-muted);
      font-size: 12px;
      margin: 4px 0 16px;
    }
    .cost-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(140px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .cost-card {
      display: grid;
      gap: 8px;
      padding: 10px;
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--control-transparent-bg-rest);
    }
    .cost-card.is-rft {
      border-color: var(--color-focus-outline);
      background: var(--control-checked-bg-rest);
      color: var(--control-checked-fg-rest);
    }
    .cost-card-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }
    .cost-name {
      font-weight: 700;
    }
    .cost-value {
      color: inherit;
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 22px;
      letter-spacing: -0.04em;
      line-height: 26px;
    }
    .rate-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(180px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .rate-card {
      border: 1px solid var(--border);
      background: var(--surface);
      padding: 10px;
    }
    .rate-card strong {
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
    }
    .assumption-note {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .rate-fields {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .rate-fields label {
      display: grid;
      gap: 3px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .rate-fields input {
      width: 100%;
      padding: 5px 6px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-family: var(--font-mono);
    }
    .cost-subvalue {
      color: var(--text-color-muted);
      font-size: 12px;
    }
    .is-rft .cost-subvalue,
    .is-rft .meta {
      color: inherit;
    }
    .savings {
      margin-top: 10px;
      padding: 10px;
      background: var(--control-transparent-bg-rest);
      color: var(--text-color-default);
      font-weight: 700;
    }
    .callout {
      padding: 12px;
      border-color: var(--border);
      background: var(--surface);
    }
    .callout h2 {
      margin: 0 0 8px;
      font-size: 18px;
    }
    .callout p {
      margin: 0;
      font-size: 14px;
      line-height: 21px;
      font-weight: 650;
    }
    code {
      font-family: var(--font-mono);
      font-size: var(--text-code-inline, 12px);
    }
    .meta {
      color: var(--text-color-muted);
      font-size: 12px;
    }
    .lineage {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin-top: 10px;
      color: var(--text-color-muted);
      font-size: 12px;
    }
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
    .lineage-note p { margin: 6px 0 0; }
    @media (max-width: 640px) {
      main {
        padding: 12px;
      }
      .slider-head {
        align-items: start;
        flex-direction: column;
        gap: 4px;
      }
      .evidence-grid {
        grid-template-columns: 1fr;
      }
      .decision-strip,
      .compare-grid.three-up {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .decision-strip div:nth-child(2) { border-right: 0; }
      .decision-strip div:nth-child(-n + 2) { border-bottom: 1px solid var(--border); }
      thead {
        display: none;
      }
      table,
      tbody,
      tr,
      td {
        display: block;
        width: 100%;
      }
      tr {
        padding: 8px 0;
        border-bottom: 1px solid var(--border-color-default);
      }
      tr:last-child {
        border-bottom: 0;
      }
      td {
        display: grid;
        grid-template-columns: 86px minmax(0, 1fr);
        gap: 8px;
        padding: 4px 10px;
        border-bottom: 0;
      }
      td::before {
        content: attr(data-label);
        color: var(--text-color-muted);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      td:first-child {
        width: 100%;
      }
    }
    @media (max-width: 360px) {
      .compare-grid,
      .cost-row {
        grid-template-columns: 1fr;
      }
      table {
        min-width: 0;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero" aria-labelledby="page-title">
      <div class="eyebrow">Contract-policy expert MAI RFT payoff</div>
      <h1 id="page-title">${escapeHtml(metrics.headline)}</h1>
      <p>These are full Foundry hosted-agent evals for <code>contract-policy-expert</code>, not model-only completions. Each stage uses five sequential 24-row runs against the same held-out dataset and rubric.</p>
    </section>

    <section aria-label="Evidence and lineage">
      <div class="link-row">
        <span class="meta">Baseline eval: <code>${escapeHtml(metrics.baselineFoundryEvalId)}</code></span>
        <span class="meta">Optimized eval: <code>${escapeHtml(metrics.optimizedFoundryEvalId)}</code></span>
        <span class="meta">Tuned eval: <code>${escapeHtml(metrics.tunedFoundryEvalId)}</code></span>
        <span class="meta">${lineageBadgeHtml(lineage.status, lineage.reviewStatus ? `review: ${lineage.reviewStatus}` : undefined)}</span>
        <span class="meta">${escapeHtml(metrics.artifactArchiveNote)}</span>
      </div>
    </section>
    ${renderDecisionStrip(lineage)}

    <section class="section-block" aria-label="Agent and model comparison">
      <div class="section-label">Agent + model</div>
      <div class="compare-grid">
        <article class="agent-card">
          <div class="agent-label">Optimized assets</div>
          <h2>Contract-policy expert</h2>
          <div class="agent-model">gpt-6-astra</div>
          <p>candidate_14 instructions and retrieval-tool contract from <code>opt_2fb58...</code>.</p>
        </article>
        <article class="agent-card">
          <div class="agent-label">Same assets + tuned model</div>
          <h2>Contract-policy expert</h2>
          <div class="agent-model">${escapeHtml(metrics.rftDeployment)}</div>
          <p>The same optimized assets, swapping only to the MAI fine-tuned model deployment.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.fineTunedModel)}">${escapeHtml(metrics.fineTunedModel)}</span></div>
        </article>
      </div>
    </section>

    <section class="section-block" aria-label="Performance comparison">
      <div class="section-label">Performance</div>
      <div class="compare-grid three-up">
        <article class="performance-card">
          <div class="metric-label">Baseline mean</div>
          <div class="metric-value">${escapeHtml(metrics.baselineFoundryMean)}</div>
          <p>Version ${escapeHtml(metrics.baselineAgentVersion)} with the intentionally weak baseline assets.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.baselineFoundryEvalId)}">${escapeHtml(metrics.baselineFoundryEvalId)}</span><br /><span class="mono-truncate" title="${escapeHtml(metrics.baselinePassCounts)}">${escapeHtml(metrics.baselinePassCounts)}</span></div>
        </article>
        <article class="performance-card">
          <div class="metric-label">Optimized mean</div>
          <div class="metric-value">${escapeHtml(metrics.optimizedFoundryMean)}</div>
          <p>Version ${escapeHtml(metrics.optimizedAgentVersion)} with candidate_14 assets on gpt-6-astra.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.optimizedFoundryEvalId)}">${escapeHtml(metrics.optimizedFoundryEvalId)}</span><br /><span class="mono-truncate" title="${escapeHtml(metrics.optimizedPassCounts)}">${escapeHtml(metrics.optimizedPassCounts)}</span></div>
        </article>
        <article class="performance-card">
          <div class="metric-label">Tuned MAI mean</div>
          <div class="metric-value">${escapeHtml(metrics.tunedFoundryMean)}</div>
          <p>Version ${escapeHtml(metrics.tunedAgentVersion)} changes only the model deployment.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.tunedFoundryEvalId)}">${escapeHtml(metrics.tunedFoundryEvalId)}</span><br /><span class="mono-truncate" title="${escapeHtml(metrics.tunedPassCounts)}">${escapeHtml(metrics.tunedPassCounts)}</span></div>
        </article>
      </div>
    </section>

    <section class="slider-card" aria-labelledby="cost-title">
      <div class="slider-head">
        <h2 id="cost-title">Estimated cost: Astra vs RFT MAI</h2>
        <div class="volume"><span id="volume-label"></span> evidence requests</div>
      </div>
      <input id="volume-slider" type="range" min="10000" max="5000000" step="10000" value="10000" aria-label="Evidence request volume" />
      <div class="range-labels">
        <span>10k</span>
        <span>5M</span>
      </div>
      <div id="rate-fields" class="rate-grid" aria-label="Price assumptions"></div>
      <p class="assumption-note">Defaults use published Azure Global Standard rates. Edit them if this deployment uses a different meter, discount, or capacity model.</p>
      <div id="token-cards" class="cost-row"></div>
      <div id="token-delta" class="savings"></div>
      <p class="meta">${escapeHtml(metrics.tokenCostBasis)}</p>
    </section>

    <section class="layout" aria-label="Detailed comparison">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Area</th>
              <th>Baseline</th>
              <th>Optimized</th>
              <th>Tuned MAI</th>
              <th>Takeaway</th>
            </tr>
          </thead>
          <tbody id="comparison-body"></tbody>
        </table>
      </div>

      <section class="callout" aria-labelledby="talk-track-title">
        <h2 id="talk-track-title">Final Results</h2>
        <p>${escapeHtml(metrics.talkTrack)}</p>
        <div class="lineage">
          <span>Optimizer: <code>${escapeHtml(metrics.optimizerJob)}</code></span>
          <span>Candidate: <code>${escapeHtml(metrics.optimizerCandidate)}</code></span>
          <span>Foundry eval: <code>${escapeHtml(metrics.optimizedFoundryEvalId)}</code></span>
          <span>Eval run: <code>${escapeHtml(metrics.optimizedFoundryRunId)}</code></span>
          <span>RFT: <code>${escapeHtml(metrics.rftJob)}</code></span>
          <span>RFT deployment: <code>${escapeHtml(metrics.rftDeployment)}</code></span>
        </div>
      </section>
    </section>
  </main>

  <script>
    const metrics = ${jsonScript(metrics)};

    const formatter = new Intl.NumberFormat("en-US");
    const comparisonBody = document.getElementById("comparison-body");
    const volumeSlider = document.getElementById("volume-slider");
    const volumeLabel = document.getElementById("volume-label");
    const rateFields = document.getElementById("rate-fields");
    const tokenCards = document.getElementById("token-cards");
    const tokenDelta = document.getElementById("token-delta");

    comparisonBody.innerHTML = metrics.comparisonRows.map((row) => (
      "<tr>" +
      "<td data-label=\\"Area\\" title=\\"" + escapeHtml(row.area) + "\\">" + escapeHtml(row.area) + "</td>" +
      "<td data-label=\\"Baseline\\" title=\\"" + escapeHtml(row.baseline) + "\\">" + escapeHtml(row.baseline) + "</td>" +
      "<td data-label=\\"Optimized\\" title=\\"" + escapeHtml(row.optimized) + "\\">" + escapeHtml(row.optimized) + "</td>" +
      "<td data-label=\\"Tuned MAI\\" title=\\"" + escapeHtml(row.tuned) + "\\">" + escapeHtml(row.tuned) + "</td>" +
      "<td data-label=\\"Takeaway\\" class=\\"takeaway\\" title=\\"" + escapeHtml(row.takeaway) + "\\">" + escapeHtml(row.takeaway) + "</td>" +
      "</tr>"
    )).join("");

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    const currencyFormatter = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

    rateFields.innerHTML = metrics.tokenOptions.map((option) => (
      "<section class=\\"rate-card\\">" +
        "<strong>" + escapeHtml(option.label) + "</strong>" +
        "<div class=\\"rate-fields\\">" +
          "<label>Input $/1M<input data-rate=\\"" + option.id + "-input\\" type=\\"number\\" min=\\"0\\" step=\\"0.01\\" value=\\"" + option.inputPricePerMillion + "\\" /></label>" +
          "<label>Output $/1M<input data-rate=\\"" + option.id + "-output\\" type=\\"number\\" min=\\"0\\" step=\\"0.01\\" value=\\"" + option.outputPricePerMillion + "\\" /></label>" +
        "</div>" +
      "</section>"
    )).join("");

    function readPrice(option, kind) {
      const input = document.querySelector("[data-rate='" + option.id + "-" + kind + "']");
      return Number(input && input.value ? input.value : 0);
    }

    function renderTokenVolume() {
      const requestVolume = Number(volumeSlider.value);
      const estimateTokens = (option, requests) => {
        const inputTokenVolume = Math.round((option.inputTokens / metrics.observedRequestCount) * requests);
        const outputTokenVolume = Math.round((option.outputTokens / metrics.observedRequestCount) * requests);
        const inputPrice = readPrice(option, "input");
        const outputPrice = readPrice(option, "output");
        const cost = ((inputTokenVolume * inputPrice) + (outputTokenVolume * outputPrice)) / 1000000;
        return {
          inputTokenVolume,
          outputTokenVolume,
          totalTokenVolume: inputTokenVolume + outputTokenVolume,
          inputPrice,
          outputPrice,
          cost,
        };
      };
      const estimates = metrics.tokenOptions.map((option) => ({ option, estimate: estimateTokens(option, requestVolume) }));
      const maxTokens = Math.max(...estimates.map(({ estimate }) => estimate.totalTokenVolume));
      const optimized = estimates.find(({ option }) => option.id === "optimized").estimate;
      const tuned = estimates.find(({ option }) => option.id === "tuned").estimate;
      const extraOutput = tuned.outputTokenVolume - optimized.outputTokenVolume;
      const outputDeltaPct = (extraOutput / optimized.outputTokenVolume) * 100;
      const costDelta = optimized.cost - tuned.cost;
      const hasPrices = estimates.some(({ estimate }) => estimate.inputPrice > 0 || estimate.outputPrice > 0);
      volumeLabel.textContent = formatter.format(requestVolume);
      tokenCards.innerHTML = estimates.map(({ option, estimate }) => {
        const extraClass = option.id === "tuned" ? " is-rft" : "";
        const perRequestInput = Math.round(option.inputTokens / metrics.observedRequestCount);
        const perRequestOutput = Math.round(option.outputTokens / metrics.observedRequestCount);
        const per10kCost = estimateTokens(option, metrics.usageUnitSize).cost;
        return (
          "<article class=\\"cost-card" + extraClass + "\\">" +
            "<div class=\\"cost-card-head\\">" +
              "<div>" +
                "<div class=\\"cost-name\\">" + escapeHtml(option.label) + "</div>" +
                "<div class=\\"meta\\">" + escapeHtml(option.model) + "</div>" +
              "</div>" +
              "<div class=\\"cost-subvalue\\">$" + currencyFormatter.format(per10kCost) + " / 10k requests</div>" +
            "</div>" +
            "<div class=\\"cost-value\\">$" + currencyFormatter.format(estimate.cost) + "</div>" +
            "<div class=\\"cost-subvalue\\">" + formatter.format(perRequestInput) + " in + " + formatter.format(perRequestOutput) + " out / request</div>" +
            "<div class=\\"cost-subvalue\\">" + formatter.format(estimate.inputTokenVolume) + " input + " + formatter.format(estimate.outputTokenVolume) + " output tokens</div>" +
          "</article>"
        );
      }).join("");
      if (!hasPrices) {
        tokenDelta.textContent = "Enter input/output prices per 1M tokens above to calculate cost. Token volume: RFT MAI emits " + formatter.format(extraOutput) + " more output tokens than Astra (" + outputDeltaPct.toFixed(1) + "%).";
      } else if (costDelta >= 0) {
        tokenDelta.textContent = "At " + formatter.format(requestVolume) + " requests, RFT MAI is $" + currencyFormatter.format(costDelta) + " lower than Astra under these price assumptions.";
      } else {
        tokenDelta.textContent = "At " + formatter.format(requestVolume) + " requests, RFT MAI is $" + currencyFormatter.format(Math.abs(costDelta)) + " higher than Astra under these price assumptions.";
      }
    }

    volumeSlider.addEventListener("input", renderTokenVolume);
    rateFields.addEventListener("input", renderTokenVolume);
    renderTokenVolume();

  </script>
</body>
</html>`;
}

async function startServer(instanceId) {
    const server = createServer((req, res) => {
        const url = new URL(req.url || "/", "http://127.0.0.1");
        if (url.pathname === "/metrics") {
            sendJson(res, { ...metrics, lineage: rftLineageStatus() });
            return;
        }
        if (url.pathname !== "/") {
            res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
            res.end("Not found");
            return;
        }
        res.writeHead(200, {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        });
        res.end(renderHtml(instanceId));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    return { server, url: `http://127.0.0.1:${port}/` };
}

await joinSession({
    canvases: [
        createCanvas({
            id: "rft-cost-quality",
            displayName: "RFT Cost Quality",
            description:
                "RFT quality comparison for the current MAI tuned model, with cost evidence marked pending until measured usage is captured.",
            actions: [
                {
                    name: "get_metrics",
                    description:
                        "Return the RFT comparison metrics rendered by the canvas, plus lineage status " +
                        "(current/stale/reference_only/unverifiable) sourced from the shared quality-" +
                        "evidence lineage evidence file.",
                    handler: async () => ({ ...metrics, lineage: rftLineageStatus() }),
                },
            ],
            open: async (ctx) => {
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer(ctx.instanceId);
                    servers.set(ctx.instanceId, entry);
                }
                return {
                    title: "RFT Cost Quality",
                    status: "Ready",
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
