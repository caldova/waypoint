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
// The RFT serving deployment was cloned from the golden optimizer candidate
// (agent version 178); the surviving fixture config for that candidate is
// committed beside the optimizer-diff-canvas, so it is what we re-hash here.
const goldenConfigPath = join(
    extensionDir,
    "..",
    "optimizer-diff-canvas",
    "fixtures",
    "opt_994a956b2d6e49939506323a15dfc5d2",
    "candidate_4-config.json",
);

const metrics = {
    headline:
        "Golden GPT-5.5 and golden RFT perform side by side.",
    talkTrack:
        "Across five full Foundry agent eval runs, golden gpt-5.5 averaged 81.7% and golden RFT o4-mini averaged 82.5%. On the observed 24-row golden model-swap token profile, RFT lowers estimated inference cost by 69.6% even though it emits more output tokens.",
    goldenGptFoundryMean: "81.7%",
    goldenRftFoundryMean: "82.5%",
    goldenGptAgentVersion: "178",
    goldenRftAgentVersion: "180",
    goldenGptFoundryEvalId: "eval_f5c6c2353d394846a4509b6c4c79bc94",
    goldenRftFoundryEvalId: "eval_d7e99889495f4400a89412d0650acd92",
    goldenGptPassCounts: "19/24, 21/24, 19/24, 20/24, 19/24",
    goldenRftPassCounts: "19/24, 20/24, 20/24, 19/24, 21/24",
    optimizerCandidateScore: 0.8521,
    optimizerCandidatePassRate: "100%",
    optimizedAssetsFoundryPass: "23/24",
    optimizedAssetsFoundryPassPercent: "95.8%",
    sameHarnessLargeScore: 0.95033,
    sameHarnessRftScore: 0.94433,
    sameHarnessDelta: 0.006,
    rftLocalPass: "24/24",
    averageGraderScore: 0.94433,
    estimatedSavingsPercent: 69.6,
    observedRequestCount: 24,
    usageUnitSize: 10000,
    tokenCostBasis:
        "Observed target model usage from the same 24-row golden model-swap runs. The slider shows actual evidence-request volume from 10k to 5M in 10k increments, using observed average input/output tokens per request for each model.",
    artifactArchiveNote:
        "Raw output-items and run payloads are archived in private durable storage; ask Seth for the location if row-level re-analysis is needed.",
    optimizerJob: "opt_994a956b2d6e49939506323a15dfc5d2",
    optimizerCandidate: "candidate_4 / cand_6bf6980ed16f4538ba0faf8935d93c01",
    optimizedFoundryEvalId: "eval_0e045fa812ca4f0d8401b5a0865a63fa",
    optimizedFoundryRunId: "evalrun_08926c405acc464a8e0079aede3a49b2",
    optimizedForgeVersion: "178",
    rftJob: "ftjob-0265d673736e496dbd360530958c6149",
    rftDeployment: "contract-policy-expert-rft-o4-mini",
    fineTunedModel: "o4-mini-2025-04-16.ft-0265d673736e496dbd360530958c6149",
    costOptions: [
        {
            id: "large",
            label: "Golden assets + large model",
            model: "gpt-5.5",
            inputTokens: 117842,
            outputTokens: 18984,
            totalTokens: 136826,
            inputPricePerMillion: 5.0,
            outputPricePerMillion: 30.0,
            costPerRun: 1.15873,
            quality: "Foundry agent mean 81.7%; token-costed 24-row run",
            role: "Quality reference",
        },
        {
            id: "rft",
            label: "Golden assets + RFT model",
            model: "o4-mini-2025-04-16 RFT",
            inputTokens: 117842,
            outputTokens: 50640,
            totalTokens: 168482,
            inputPricePerMillion: 1.1,
            outputPricePerMillion: 4.4,
            costPerRun: 0.352442,
            quality: "Foundry agent mean 82.5%; token-costed 24-row run",
            role: "Cost-optimized serving candidate",
        },
    ],
    comparisonRows: [
        {
            area: "Foundry agent mean",
            original: "Golden gpt-5.5: 81.7% mean over five 24-row runs",
            rft: "Golden RFT o4-mini: 82.5% mean over five 24-row runs",
            takeaway: "RFT maintains mean accuracy while using the cheaper model",
        },
        {
            area: "Run spread",
            original: "Golden gpt-5.5: 79%-88% across five runs",
            rft: "Golden RFT: 79%-88% across five runs",
            takeaway: "Repeated runs smooth stochastic variation and keep the comparison side by side",
        },
        {
            area: "Optimizer candidate",
            original: "candidate_4 cand_6bf..., optimizer score 0.8521, 100% optimizer pass",
            rft: "Trained to preserve this candidate's evidence contract behavior",
            takeaway: "Candidate 4 is the golden Foundry-optimized target",
        },
        {
            area: "Applied assets eval",
            original: "Forge v178 Foundry eval group: eval_f5c6...",
            rft: "Forge v180 RFT Foundry eval group: eval_d7e9...",
            takeaway: "Both are actual hosted agent evals with tools, not model-only completions",
        },
        {
            area: "Behavior target",
            original: "Candidate 4 system prompt + skills from opt_994",
            rft: "Same candidate 4 instructions with RFT o4-mini deployment",
            takeaway: "Optimizer found the behavior; RFT compressed the economics",
        },
        {
            area: "Model",
            original: "gpt-5.5",
            rft: "o4-mini-2025-04-16 fine-tuned with RFT",
            takeaway: "Same expert pattern on a smaller serving model",
        },
        {
            area: "RFT job",
            original: "Not applicable",
            rft: "ftjob-0265d673736e496dbd360530958c6149",
            takeaway: "Training completed successfully",
        },
        {
            area: "Fine-tuned model",
            original: "Not applicable",
            rft: "o4-mini-2025-04-16.ft-0265d673736e496dbd360530958c6149",
            takeaway: "Deployable cheaper expert model",
        },
        {
            area: "RFT deployment",
            original: "Not applicable",
            rft: "contract-policy-expert-rft-o4-mini",
            takeaway: "Fine-tuned model is deployed for serving comparisons",
        },
        {
            area: "Raw RFT prompt",
            original: "Not applicable",
            rft: "0.353 avg, 0/24 without golden candidate context",
            takeaway: "The story is RFT inside the optimized agent assets, not raw standalone prompting",
        },
        {
            area: "Estimated inference cost",
            original: "$1.16 per observed 24-row token-costed run",
            rft: "$0.35 per observed 24-row token-costed run",
            takeaway: "Cost comparison shows 69.6% estimated savings from consumed tokens",
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
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--background-color-default);
      color: var(--text-color-default);
      font-family: var(--font-sans);
      font-size: var(--text-body-medium, 14px);
      line-height: var(--leading-body-medium, 20px);
    }
    main {
      width: min(920px, 100%);
      margin: 0 auto;
      padding: 12px;
    }
    .hero {
      display: grid;
      gap: 6px;
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
      font-size: clamp(24px, 3vw, 36px);
      font-weight: var(--font-weight-semibold, 700);
      letter-spacing: -0.04em;
      line-height: 1.02;
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
    .agent-card,
    .performance-card {
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--background-color-muted);
      padding: 10px;
    }
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
      border: 1px solid var(--border-color-default);
      border-radius: 0.625rem;
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
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--background-color-muted);
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
      max-width: 0;
      white-space: nowrap;
    }
    .takeaway {
      color: var(--text-color-muted);
    }
    .panel {
      display: grid;
      gap: 16px;
    }
    .slider-card {
      border: 1px solid var(--border-color-default);
      border-radius: 16px;
      background: var(--background-color-muted);
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
    .bar {
      height: 12px;
      overflow: hidden;
      border-radius: 0.625rem;
      background: var(--background-color-default);
      border: 1px solid var(--border-color-default);
    }
    .bar span {
      display: block;
      height: 100%;
      border-radius: 0.625rem;
      background: var(--color-focus-outline);
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
      border-radius: 0.625rem;
      background: var(--control-transparent-bg-rest);
      color: var(--text-color-default);
      font-weight: 700;
    }
    .callout {
      padding: 12px;
      border-color: var(--border-color-default);
      background: var(--background-color-muted);
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
    @media (max-width: 640px) {
      main {
        padding: 10px;
      }
      .slider-head {
        align-items: start;
        flex-direction: column;
        gap: 4px;
      }
      .evidence-grid {
        grid-template-columns: 1fr;
      }
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
      <div class="eyebrow">Contract-policy expert RFT payoff</div>
      <h1 id="page-title">${escapeHtml(metrics.headline)}</h1>
      <p>These are full Foundry hosted-agent evals for <code>contract-policy-expert</code>, not model-only completions. The side-by-side metric is the mean over five full 24-row runs per golden agent version.</p>
    </section>

    <section aria-label="Evidence and lineage">
      <div class="link-row">
        <span class="meta">Golden GPT-5.5 eval: <code>${escapeHtml(metrics.goldenGptFoundryEvalId)}</code></span>
        <span class="meta">Golden RFT eval: <code>${escapeHtml(metrics.goldenRftFoundryEvalId)}</code></span>
        <span class="meta">${lineageBadgeHtml(lineage.status, lineage.reviewStatus ? `review: ${lineage.reviewStatus}` : undefined)}</span>
        <span class="meta">${escapeHtml(metrics.artifactArchiveNote)}</span>
      </div>
    </section>

    <section class="section-block" aria-label="Agent and model comparison">
      <div class="section-label">Agent + model</div>
      <div class="compare-grid">
        <article class="agent-card">
          <div class="agent-label">Golden assets + large model</div>
          <h2>Contract-policy expert</h2>
          <div class="agent-model">gpt-5.5</div>
          <p>Candidate 4 instructions and skills from <code>opt_994</code>, served by the larger model.</p>
        </article>
        <article class="agent-card">
          <div class="agent-label">Golden assets + RFT model</div>
          <h2>Contract-policy expert</h2>
          <div class="agent-model">o4-mini-2025-04-16 RFT</div>
          <p>The same optimized assets, swapping only to the fine-tuned cheaper model.</p>
        </article>
      </div>
    </section>

    <section class="section-block" aria-label="Performance comparison">
      <div class="section-label">Performance</div>
      <div class="compare-grid">
        <article class="performance-card">
          <div class="metric-label">Golden GPT-5.5 agent mean</div>
          <div class="metric-value">${escapeHtml(metrics.goldenGptFoundryMean)}</div>
          <p>Version ${escapeHtml(metrics.goldenGptAgentVersion)} with candidate 4 golden assets; actual hosted agent + tools.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.goldenGptFoundryEvalId)}">${escapeHtml(metrics.goldenGptFoundryEvalId)}</span><br /><span class="mono-truncate" title="${escapeHtml(metrics.goldenGptPassCounts)}">${escapeHtml(metrics.goldenGptPassCounts)}</span></div>
        </article>
        <article class="performance-card">
          <div class="metric-label">Golden RFT agent mean</div>
          <div class="metric-value">${escapeHtml(metrics.goldenRftFoundryMean)}</div>
          <p>Version ${escapeHtml(metrics.goldenRftAgentVersion)} swaps only to the RFT model deployment while preserving tools.</p>
          <div class="source"><span class="mono-truncate" title="${escapeHtml(metrics.goldenRftFoundryEvalId)}">${escapeHtml(metrics.goldenRftFoundryEvalId)}</span><br /><span class="mono-truncate" title="${escapeHtml(metrics.goldenRftPassCounts)}">${escapeHtml(metrics.goldenRftPassCounts)}</span></div>
        </article>
      </div>
    </section>

    <section class="slider-card" aria-labelledby="cost-title">
      <div class="slider-head">
        <h2 id="cost-title">Token cost comparison</h2>
        <div class="volume"><span id="volume-label"></span> evidence requests</div>
      </div>
      <input id="volume-slider" type="range" min="10000" max="5000000" step="10000" value="10000" aria-label="Evidence request volume" />
      <div class="range-labels">
        <span>10k</span>
        <span>5M</span>
      </div>
      <div id="cost-cards" class="cost-row"></div>
      <div id="savings" class="savings"></div>
      <p class="meta">Cost is computed from observed average input/output tokens per evidence request, then scaled by usage volume in 10k-request increments. ${escapeHtml(metrics.tokenCostBasis)}</p>
    </section>

    <section class="layout" aria-label="Detailed comparison">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Area</th>
              <th>gpt-5.5 + golden assets</th>
              <th>RFT o4-mini + golden assets</th>
              <th>Demo takeaway</th>
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
    const currencyFormatter = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    const comparisonBody = document.getElementById("comparison-body");
    const volumeSlider = document.getElementById("volume-slider");
    const volumeLabel = document.getElementById("volume-label");
    const costCards = document.getElementById("cost-cards");
    const savings = document.getElementById("savings");

    comparisonBody.innerHTML = metrics.comparisonRows.map((row) => (
      "<tr>" +
      "<td data-label=\\"Area\\" title=\\"" + escapeHtml(row.area) + "\\">" + escapeHtml(row.area) + "</td>" +
      "<td data-label=\\"Original\\" title=\\"" + escapeHtml(row.original) + "\\">" + escapeHtml(row.original) + "</td>" +
      "<td data-label=\\"RFT\\" title=\\"" + escapeHtml(row.rft) + "\\">" + escapeHtml(row.rft) + "</td>" +
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

    function renderCosts() {
      const requestVolume = Number(volumeSlider.value);
      const estimateCost = (option, requests) => {
        const inputTokenVolume = Math.round((option.inputTokens / metrics.observedRequestCount) * requests);
        const outputTokenVolume = Math.round((option.outputTokens / metrics.observedRequestCount) * requests);
        const cost = ((inputTokenVolume * option.inputPricePerMillion) + (outputTokenVolume * option.outputPricePerMillion)) / 1000000;
        return { cost, inputTokenVolume, outputTokenVolume };
      };
      const estimateCurrentCost = (option) => estimateCost(option, requestVolume);
      const large = estimateCurrentCost(metrics.costOptions[0]);
      const rft = estimateCurrentCost(metrics.costOptions[1]);
      const maxCost = Math.max(...metrics.costOptions.map((option) => estimateCurrentCost(option).cost));
      volumeLabel.textContent = formatter.format(requestVolume);
      costCards.innerHTML = metrics.costOptions.map((option) => {
        const estimate = estimateCurrentCost(option);
        const cost = estimate.cost;
        const width = Math.max(2, Math.round((cost / maxCost) * 100));
        const extraClass = option.id === "rft" ? " is-rft" : "";
        const costPerUsageUnit = estimateCost(option, metrics.usageUnitSize).cost;
        return (
          "<article class=\\"cost-card" + extraClass + "\\">" +
            "<div class=\\"cost-card-head\\">" +
              "<div>" +
                "<div class=\\"cost-name\\">" + escapeHtml(option.label) + "</div>" +
                "<div class=\\"meta\\">" + escapeHtml(option.model) + "</div>" +
              "</div>" +
              "<div class=\\"cost-subvalue\\">$" + currencyFormatter.format(costPerUsageUnit) + " / 10k requests</div>" +
            "</div>" +
            "<div class=\\"cost-value\\">$" + currencyFormatter.format(cost) + "</div>" +
            "<div class=\\"cost-subvalue\\">" + formatter.format(estimate.inputTokenVolume) + " input + " + formatter.format(estimate.outputTokenVolume) + " output tokens</div>" +
            "<div class=\\"bar\\" aria-hidden=\\"true\\"><span style=\\"width: " + width + "%\\"></span></div>" +
          "</article>"
        );
      }).join("");
      savings.textContent = metrics.estimatedSavingsPercent + "% estimated savings; $" + currencyFormatter.format(large.cost - rft.cost) + " avoided across " + formatter.format(requestVolume) + " evidence requests.";
    }

    volumeSlider.addEventListener("input", renderCosts);
    renderCosts();
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
                "Interactive RFT cost and quality comparison with a token-cost savings slider.",
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
