import {
    AGENT_ANATOMY,
    CANONICAL_AUDIT_PROMPT,
    DEMO_BEATS,
    HERO_INVOICE,
    JOURNEY_STAGES,
} from "./demo-data.mjs";

const ICONS = {
    model: icon('<path d="M8 3h8v3h3v12h-3v3H8v-3H5V6h3V3Z"/><path d="M9 9h6v6H9z"/>'),
    instructions: icon('<path d="M7 3h10v18H7z"/><path d="M10 8h4M10 12h4M10 16h3"/>'),
    context: icon('<path d="M8 3h8l3 3v15H8z"/><path d="M16 3v4h4M11 11h5M11 15h5"/>'),
    memory: icon('<path d="M7 7a5 5 0 0 1 10 0v2a4 4 0 0 1 0 8h-1"/><path d="M8 17a4 4 0 0 1 0-8V7M8 13h8"/>'),
    tools: icon('<path d="m14 6 4-3 3 3-3 4"/><path d="m15 9-9 9-3 3M6 14l4 4"/>'),
    chat: icon('<path d="M4 5h16v11H9l-5 4z"/>'),
    trace: icon('<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5M8 11h6M11 8v6"/>'),
    connection: icon('<path d="M8 8V4M16 8V4M6 8h12v4a6 6 0 0 1-12 0zM12 18v3"/>'),
    shield: icon('<path d="M12 3 5 6v5c0 4.6 2.8 8.3 7 10 4.2-1.7 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-4"/>'),
    arrow: icon('<path d="M5 12h14M14 7l5 5-5 5"/>'),
};

const invoiceRows = HERO_INVOICE.lines
    .map(
        (line) => `
          <tr>
            <td><code>${line.id}</code></td>
            <td>${line.description}</td>
            <td class="num">${line.quantity.toLocaleString("en-US")}</td>
            <td class="num">${money(line.unitPrice)}</td>
            <td class="num">${money(line.amount)}</td>
          </tr>`,
    )
    .join("");

const anatomyRows = AGENT_ANATOMY.map(
    (part) => `
      <details class="anatomy-part part-${part.id}" data-part="${part.id}" open>
        <summary>
          <span class="part-icon" aria-hidden="true">${ICONS[part.id]}</span>
          <span class="part-title"><strong>${part.label}</strong><small${part.id === "model" ? ' id="anatomy-model"' : ""}>${part.value}</small></span>
          <span class="part-state" aria-hidden="true"></span>
          <span class="chevron" aria-hidden="true">›</span>
        </summary>
        <p>${part.detail}</p>
      </details>`,
).join("");

const beatRows = DEMO_BEATS.map(
    (beat, index) => `
      <li>
        <span class="beat-number">${index + 1}</span>
        <div><strong>${beat.label}</strong><p>${beat.talkTrack}</p></div>
      </li>`,
).join("");

const journeyRows = JOURNEY_STAGES.map(
    (stage, index) => `
      <li class="${stage.state}" data-stage="${stage.id}">
        <div class="stage-top"><span>${stage.label}</span>${index < JOURNEY_STAGES.length - 1 ? ICONS.arrow : ""}</div>
        <strong>${stage.title}</strong>
        <small>${stage.detail}</small>
      </li>`,
).join("");

export function renderHtml() {
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <title>Pharmashield · Foundry Agent</title>
  <script>
    (() => {
      const root = document.documentElement;
      const media = window.matchMedia('(prefers-color-scheme: light)');
      const readMode = (name) => root.getAttribute(name) || document.body?.getAttribute(name) || '';
      const resolveTheme = () => {
        const hostMode = [readMode('data-visual-mode'), readMode('data-color-mode')]
          .find((mode) => mode === 'light' || mode === 'dark');
        root.setAttribute('data-theme', hostMode === 'light' || hostMode === 'dark' ? hostMode : media.matches ? 'light' : 'dark');
      };
      resolveTheme();
      const observer = new MutationObserver(resolveTheme);
      const options = {
        attributes: true,
        attributeFilter: ['data-visual-mode', 'data-color-mode', 'data-light-theme', 'data-dark-theme'],
      };
      observer.observe(root, options);
      document.addEventListener('DOMContentLoaded', () => observer.observe(document.body, options), { once: true });
      media.addEventListener?.('change', resolveTheme);
    })();
  </script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0d1117;
      --surface: #161b22;
      --surface-subtle: #21262d;
      --surface-raised: #1c2128;
      --border: #30363d;
      --border-strong: #484f58;
      --text: #e6edf3;
      --muted: #9da7b3;
      --faint: #8b949e;
      --accent: #58a6ff;
      --accent-hover: #79c0ff;
      --accent-soft: #102f4c;
      --iq: #f778ba;
      --iq-soft: #421c33;
      --success: #56d364;
      --success-soft: #173b22;
      --warning: #e3b341;
      --warning-soft: #3d2f05;
      --danger: #ff7b72;
      --danger-soft: #4c1f24;
      --focus: #58a6ff;
      --shadow: 0 1px 2px rgba(0, 0, 0, .45);
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, monospace;
      --radius-sm: 6px;
      --radius-md: 8px;
      --radius-lg: 12px;
      --ease: cubic-bezier(.16, 1, .3, 1);
    }
    :root[data-theme="light"],
    :root[data-color-mode="light"],
    :root[data-visual-mode="light"] {
      color-scheme: light;
      --bg: #f6f8fa;
      --surface: #ffffff;
      --surface-subtle: #f0f3f6;
      --surface-raised: #ffffff;
      --border: #d0d7de;
      --border-strong: #afb8c1;
      --text: #1f2328;
      --muted: #59636e;
      --faint: #656d76;
      --accent: #0969da;
      --accent-hover: #075bbf;
      --accent-soft: #ddf4ff;
      --iq: #bf3989;
      --iq-soft: #ffeff7;
      --success: #1a7f37;
      --success-soft: #dafbe1;
      --warning: #9a6700;
      --warning-soft: #fff8c5;
      --danger: #cf222e;
      --danger-soft: #ffebe9;
      --focus: #0969da;
      --shadow: 0 1px 2px rgba(31, 35, 40, .06);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 var(--font);
      -webkit-font-smoothing: antialiased;
    }
    button, select { font: inherit; }
    button:focus-visible, select:focus-visible, summary:focus-visible, [role="tab"]:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    svg { display: block; width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    code, pre { font-family: var(--mono); }
    .app { min-height: 100vh; display: grid; grid-template-columns: 280px minmax(0, 1fr); }
    .anatomy {
      min-width: 0;
      padding: 20px 16px;
      background: var(--surface-subtle);
      border-right: 1px solid var(--border);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }
    .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; }
    .brand-mark {
      width: 36px; height: 36px; display: grid; place-items: center; border-radius: 10px;
      color: var(--accent); background: var(--accent-soft); border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border));
    }
    .brand strong, .brand small { display: block; }
    .brand strong { font-size: 14px; }
    .brand small { color: var(--muted); font-size: 11px; }
    .section-label {
      margin: 0 0 8px; color: var(--faint); font-size: 11px; font-weight: 700;
      letter-spacing: .06em; text-transform: uppercase;
    }
    .anatomy-intro { color: var(--muted); font-size: 12px; margin: 0 0 16px; }
    .anatomy-part {
      --part: var(--faint);
      margin: 0 0 8px; border: 1px solid var(--border); border-radius: 10px;
      background: var(--surface); opacity: .62; transition: opacity 180ms, border-color 180ms, box-shadow 180ms;
    }
    .part-model { --part: #7c8cff; }
    .part-instructions { --part: #a371f7; }
    .part-context { --part: var(--success); }
    .part-memory { --part: var(--warning); }
    .part-tools { --part: var(--iq); }
    .anatomy-part.on { opacity: 1; border-color: color-mix(in srgb, var(--part) 55%, var(--border)); box-shadow: inset 3px 0 0 var(--part); }
    .anatomy-part summary {
      min-height: 48px; padding: 8px 10px; display: grid; grid-template-columns: 28px 1fr 8px 12px;
      gap: 8px; align-items: center; list-style: none; cursor: pointer;
    }
    .anatomy-part summary::-webkit-details-marker { display: none; }
    .part-icon {
      width: 28px; height: 28px; display: grid; place-items: center; border-radius: 7px;
      color: var(--part); background: color-mix(in srgb, var(--part) 13%, transparent);
    }
    .part-title { min-width: 0; }
    .part-title strong, .part-title small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .part-title strong { font-size: 12px; }
    .part-title small { color: var(--muted); font-size: 10px; margin-top: 1px; }
    .part-state { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); }
    .anatomy-part.on .part-state { background: var(--part); box-shadow: 0 0 7px color-mix(in srgb, var(--part) 72%, transparent); }
    .chevron { color: var(--faint); font-size: 15px; transition: transform 150ms; }
    .anatomy-part[open] .chevron { transform: rotate(90deg); }
    .anatomy-part > p { margin: 0; padding: 0 12px 12px 46px; color: var(--muted); font-size: 11px; line-height: 1.45; }
    .equation {
      margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--border);
      color: var(--muted); font-size: 11px;
    }
    .equation strong { color: var(--text); }
    .workspace { min-width: 0; }
    .topbar {
      min-height: 56px; padding: 8px 20px; display: flex; align-items: center; gap: 16px;
      position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--surface) 94%, transparent);
      border-bottom: 1px solid var(--border); backdrop-filter: blur(12px);
    }
    .agent-title { min-width: 170px; }
    .agent-title strong, .agent-title small { display: block; }
    .agent-title strong { font-size: 13px; }
    .agent-title small { color: var(--muted); font-size: 10px; }
    .tabs { display: inline-flex; gap: 2px; padding: 3px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-subtle); }
    .tab {
      min-height: 36px; padding: 0 12px; display: inline-flex; align-items: center; gap: 7px;
      border: 0; border-radius: 7px; color: var(--muted); background: transparent; cursor: pointer;
    }
    .tab:hover { color: var(--text); }
    .tab[aria-selected="true"] { color: var(--text); background: var(--surface); box-shadow: var(--shadow); font-weight: 600; }
    .tab .count { min-width: 18px; padding: 0 6px; border-radius: 999px; color: var(--iq); background: var(--iq-soft); font-size: 10px; text-align: center; white-space: nowrap; }
    .status-pill {
      margin-left: auto; min-height: 32px; padding: 4px 10px; display: inline-flex; align-items: center; gap: 7px;
      border: 1px solid var(--border); border-radius: 999px; color: var(--muted); background: var(--surface); font-size: 11px; white-space: nowrap;
    }
    .status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning); }
    .status-pill.ready .status-dot { background: var(--success); }
    .status-pill.error .status-dot { background: var(--danger); }
    .journey {
      margin: 0; padding: 14px 20px; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
      list-style: none; border-bottom: 1px solid var(--border); background: var(--surface);
    }
    .journey li { min-width: 0; padding: 0 14px; border-left: 1px solid var(--border); }
    .journey li:first-child { padding-left: 0; border-left: 0; }
    .journey li:last-child { padding-right: 0; }
    .stage-top { display: flex; align-items: center; justify-content: space-between; color: var(--faint); font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
    .stage-top svg { width: 14px; height: 14px; }
    .journey strong, .journey small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .journey strong { margin-top: 3px; font-size: 11px; }
    .journey small { color: var(--muted); font-size: 10px; margin-top: 1px; }
    .journey .active .stage-top, .journey .active strong { color: var(--accent); }
    .pane { display: none; }
    .pane.active { display: block; }
    .pane-wrap { max-width: 1240px; margin: 0 auto; padding: 24px; }
    .chat-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; align-items: start; }
    .panel, .card {
      border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); box-shadow: var(--shadow);
    }
    .conversation { overflow: hidden; }
    .conversation-head {
      padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px;
      border-bottom: 1px solid var(--border);
    }
    .conversation-head h1 { margin: 0 0 2px; font-size: 16px; }
    .conversation-head p { margin: 0; color: var(--muted); font-size: 12px; }
    .context-chip {
      min-height: 32px; padding: 4px 9px; border-radius: 999px; display: inline-flex; align-items: center; gap: 6px;
      color: var(--success); background: var(--success-soft); font-size: 11px; font-weight: 600; white-space: nowrap;
    }
    .messages { min-height: 560px; padding: 20px; display: flex; flex-direction: column; gap: 16px; background: var(--bg); }
    .message-row { max-width: 88%; display: flex; gap: 10px; }
    .message-row.user { margin-left: auto; flex-direction: row-reverse; }
    .avatar {
      width: 30px; height: 30px; flex: none; display: grid; place-items: center; border-radius: 8px;
      color: var(--accent); background: var(--accent-soft);
    }
    .avatar svg { width: 16px; height: 16px; }
    .message-row.user .avatar { color: #ffffff; background: var(--accent); }
    .bubble { padding: 11px 13px; border: 1px solid var(--border); border-radius: 11px; background: var(--surface); }
    .message-row.user .bubble { color: #ffffff; border-color: var(--accent); background: var(--accent); }
    .bubble p { margin: 0; }
    .bubble p + p { margin-top: 8px; }
    .bubble .meta-line { color: var(--muted); font-size: 11px; margin-top: 8px; }
    .message-row.user .meta-line { color: rgba(255, 255, 255, .78); }
    .context-note {
      margin-top: 10px; padding: 10px; border-radius: 8px; color: var(--accent); background: var(--accent-soft); font-size: 11px;
    }
    .user-audit { display: none; }
    .user-audit.show { display: flex; }
    .retrieving {
      display: none; align-self: flex-start; align-items: center; gap: 8px; min-height: 32px; padding: 5px 11px;
      border: 1px solid color-mix(in srgb, var(--iq) 40%, var(--border)); border-radius: 999px;
      color: var(--iq); background: var(--iq-soft); font-size: 11px;
    }
    .retrieving.show { display: inline-flex; }
    .retrieving-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--iq); animation: pulse 1s ease-in-out infinite; }
    .result-message { display: none; }
    .result-message.show { display: flex; }
    .result-message .bubble { width: 100%; padding: 0; overflow: hidden; }
    .audit-overview { padding: 20px; border-bottom: 1px solid var(--border); }
    .audit-eyebrow {
      margin-bottom: 8px; color: var(--iq); font-size: 10px; font-weight: 700;
      letter-spacing: .08em; text-transform: uppercase;
    }
    .audit-overview h2 { max-width: 32ch; margin: 0; font-size: 18px; line-height: 1.3; letter-spacing: -.02em; text-wrap: balance; }
    .result-summary { max-width: 68ch; margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; text-wrap: pretty; }
    .audit-metrics { display: flex; gap: 0; margin-top: 16px; border-top: 1px solid var(--border); }
    .audit-metric { min-width: 112px; padding: 12px 20px 0 0; }
    .audit-metric + .audit-metric { padding-left: 20px; border-left: 1px solid var(--border); }
    .audit-metric strong { display: block; color: var(--text); font-size: 18px; font-variant-numeric: tabular-nums; }
    .audit-metric span { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
    .key-findings { padding: 16px 20px 4px; }
    .key-findings-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
    .key-findings-head h3 { margin: 0; font-size: 13px; }
    .key-findings-head span { color: var(--muted); font-size: 10px; }
    .finding-list { display: grid; gap: 8px; }
    .finding {
      position: relative; padding: 12px 12px 12px 16px; border: 1px solid var(--border);
      border-radius: 8px; background: var(--surface-subtle);
    }
    .finding::before {
      position: absolute; inset: 8px auto 8px 0; width: 3px; border-radius: 0 3px 3px 0;
      background: var(--muted); content: "";
    }
    .finding.recover::before { background: var(--danger); }
    .finding.review::before, .finding.escalate::before { background: var(--warning); }
    .finding.approve::before { background: var(--success); }
    .finding-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    .finding-head h4 { margin: 0; font-size: 12px; line-height: 1.4; }
    .finding-claim { margin: 6px 0 0; color: var(--text); font-size: 11px; line-height: 1.55; }
    .finding-meta { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; color: var(--muted); font-size: 10px; }
    .finding-meta span { display: inline-flex; align-items: center; gap: 5px; }
    .finding-meta svg { width: 13px; height: 13px; }
    .confidence { font-variant-numeric: tabular-nums; }
    .reference { color: var(--iq); }
    .review-questions, .evidence-details { margin: 12px 20px 0; border-top: 1px solid var(--border); }
    .review-questions summary, .evidence-details summary {
      min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 12px;
      color: var(--text); cursor: pointer; font-size: 11px; font-weight: 600; list-style: none;
    }
    .review-questions summary::-webkit-details-marker, .evidence-details summary::-webkit-details-marker { display: none; }
    .review-questions summary span, .evidence-details summary span { color: var(--muted); font-size: 10px; font-weight: 400; }
    .review-questions summary:hover, .evidence-details summary:hover { color: var(--accent); }
    .review-questions ul { margin: 0 0 12px; padding-left: 18px; color: var(--muted); font-size: 10px; }
    .review-questions li + li { margin-top: 6px; }
    .evidence-list { display: grid; gap: 8px; padding-bottom: 12px; }
    .evidence {
      padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-subtle);
    }
    .evidence-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .evidence strong { font-size: 11px; }
    .evidence p { margin: 5px 0 0; color: var(--muted); font-size: 10px; }
    .evidence .source { color: var(--iq); font-family: var(--mono); overflow-wrap: anywhere; }
    .support {
      flex: none; padding: 1px 6px; border-radius: 999px; color: var(--muted); background: var(--surface); font-size: 9px; font-weight: 700; text-transform: uppercase;
    }
    .support.recover { color: var(--danger); background: var(--danger-soft); }
    .support.escalate, .support.review { color: var(--warning); background: var(--warning-soft); }
    .support.approve { color: var(--success); background: var(--success-soft); }
    .proof-banner {
      width: calc(100% - 40px); min-height: 44px; margin: 12px 20px 20px; padding: 10px; display: flex; align-items: center; gap: 8px;
      border: 1px solid color-mix(in srgb, var(--success) 35%, var(--border)); border-radius: 8px;
      color: var(--success); background: var(--success-soft); font-size: 11px; font-weight: 600;
    }
    button.proof-banner { cursor: pointer; transition: border-color .15s ease, background .15s ease; }
    button.proof-banner:hover { border-color: var(--success); background: color-mix(in srgb, var(--success) 16%, var(--surface)); }
    .side-stack { display: grid; gap: 16px; }
    .card { padding: 16px; }
    .card h2 { margin: 0 0 3px; font-size: 14px; }
    .card > p, .card-head p { margin: 0; color: var(--muted); font-size: 11px; }
    .card-head { margin-bottom: 14px; }
    .checks { display: grid; gap: 9px; margin-top: 14px; }
    .check { display: grid; grid-template-columns: 18px 1fr; gap: 8px; align-items: start; }
    .check-icon {
      width: 18px; height: 18px; display: grid; place-items: center; border: 1px solid var(--border);
      border-radius: 50%; color: var(--muted); background: var(--surface-subtle); font-size: 10px;
    }
    .check.ok .check-icon { color: #ffffff; border-color: var(--success); background: var(--success); }
    .check.fail .check-icon { color: #ffffff; border-color: var(--danger); background: var(--danger); }
    .check strong, .check span { display: block; }
    .check strong { font-size: 11px; }
    .check span { margin-top: 1px; color: var(--muted); font-size: 10px; overflow-wrap: anywhere; }
    .field { display: grid; gap: 5px; margin-top: 14px; }
    .field label { font-size: 11px; font-weight: 600; }
    select {
      width: 100%; min-height: 40px; padding: 0 10px; color: var(--text); background: var(--surface);
      border: 1px solid var(--border); border-radius: var(--radius-md);
    }
    .buttons { display: grid; gap: 8px; margin-top: 12px; }
    .btn {
      min-height: 44px; padding: 0 14px; border: 1px solid transparent; border-radius: var(--radius-md);
      cursor: pointer; font-weight: 600; transition: background 150ms, border-color 150ms, transform 80ms var(--ease);
    }
    .btn:active { transform: translateY(1px); }
    .btn:disabled { opacity: .5; cursor: not-allowed; transform: none; }
    .btn-primary { color: #ffffff; background: var(--accent); }
    .btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
    .btn-secondary { color: var(--text); border-color: var(--border); background: var(--surface); }
    .btn-secondary:hover:not(:disabled) { background: var(--surface-subtle); }
    .progress {
      height: 4px; margin-top: 12px; overflow: hidden; border-radius: 999px; background: var(--surface-subtle);
    }
    .progress span { display: block; width: 0; height: 100%; background: var(--accent); transition: width 250ms var(--ease); }
    .progress.running span { width: 72%; animation: progress-breathe 1.6s ease-in-out infinite alternate; }
    .progress.complete span { width: 100%; background: var(--success); }
    .progress.error span { width: 100%; background: var(--danger); }
    .run-message {
      min-height: 42px; margin-top: 10px; padding: 9px; border-radius: 8px;
      color: var(--muted); background: var(--surface-subtle); font-size: 10px; overflow-wrap: anywhere;
    }
    .presenter details { margin-top: 10px; }
    .presenter summary { min-height: 36px; display: flex; align-items: center; color: var(--accent); cursor: pointer; font-size: 11px; font-weight: 600; }
    .beats { margin: 4px 0 0; padding: 0; display: grid; gap: 12px; list-style: none; }
    .beats li { display: grid; grid-template-columns: 22px 1fr; gap: 8px; }
    .beat-number {
      width: 22px; height: 22px; display: grid; place-items: center; border-radius: 50%;
      color: var(--muted); background: var(--surface-subtle); font-size: 9px; font-weight: 700;
    }
    .beats strong { display: block; font-size: 10px; }
    .beats p { margin: 2px 0 0; color: var(--muted); font-size: 10px; line-height: 1.4; }
    .trace-layout { max-width: 900px; }
    .connection-layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(280px, .6fr); gap: 20px; }
    .pane-title { margin-bottom: 16px; }
    .pane-title h1 { margin: 0 0 4px; font-size: 20px; }
    .pane-title p { margin: 0; max-width: 760px; color: var(--muted); }
    .empty-state { padding: 48px 24px; color: var(--muted); text-align: center; }
    .empty-state .empty-icon {
      width: 44px; height: 44px; margin: 0 auto 12px; display: grid; place-items: center;
      border-radius: 12px; color: var(--iq); background: var(--iq-soft);
    }
    .empty-state h2 { margin: 0 0 5px; color: var(--text); font-size: 14px; }
    .empty-state p { margin: 0 auto; max-width: 520px; font-size: 11px; }
    .trace-list { display: grid; gap: 12px; padding: 16px; }
    .trace-step {
      overflow: hidden; border: 1px solid var(--border); border-radius: 10px;
      background: var(--surface); box-shadow: var(--shadow);
    }
    .trace-step.error { border-color: color-mix(in srgb, var(--danger) 55%, var(--border)); }
    .trace-step-head {
      min-height: 42px; padding: 10px 12px; display: flex; align-items: center; gap: 9px;
      border-bottom: 1px solid var(--border); background: var(--surface-subtle); font-size: 11px; font-weight: 700;
    }
    .trace-step-head svg { color: var(--iq); }
    .trace-step.error .trace-step-head svg { color: var(--danger); }
    .trace-step-body { padding: 12px; color: var(--muted); font-size: 11px; }
    .trace-step-body p { margin: 0; }
    .trace-step-body p + p { margin-top: 6px; }
    .trace-step-body code { color: var(--text); }
    .trace-value {
      margin: 0; max-height: 360px; overflow: auto; color: var(--muted);
      font: 10px/1.6 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .trace-highlight {
      padding: 1px 2px; border-radius: 3px; color: var(--text);
      background: color-mix(in srgb, var(--warning) 28%, transparent);
      box-shadow: inset 0 -1px 0 color-mix(in srgb, var(--warning) 65%, transparent);
    }
    .trace-citations { margin: 0; padding: 0; display: grid; gap: 8px; list-style: none; }
    .trace-citation {
      padding: 9px; border: 1px solid color-mix(in srgb, var(--iq) 28%, var(--border));
      border-radius: 8px; color: var(--text); background: var(--iq-soft); overflow-wrap: anywhere;
    }
    .trace-citation strong { display: block; font-size: 11px; }
    .trace-citation-meta { display: block; margin-top: 3px; color: var(--iq); font: 9px/1.45 var(--mono); }
    .trace-citation-detail { display: block; margin-top: 5px; color: var(--muted); font-size: 10px; }
    .trace-findings { margin: 0; padding: 0; display: grid; gap: 8px; list-style: none; }
    .trace-finding { padding: 10px; border-left: 3px solid var(--warning); background: var(--surface-subtle); }
    .trace-finding.recover { border-left-color: var(--danger); }
    .trace-finding strong { display: block; color: var(--text); font-size: 11px; }
    .trace-finding span { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
    .connection-steps { display: grid; gap: 12px; }
    .connection-step { padding: 16px; display: grid; grid-template-columns: 32px 1fr; gap: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    .connection-step > span {
      width: 32px; height: 32px; display: grid; place-items: center; border-radius: 9px;
      color: var(--accent); background: var(--accent-soft); font-weight: 700;
    }
    .connection-step strong { display: block; font-size: 12px; }
    .connection-step p { margin: 3px 0 0; color: var(--muted); font-size: 11px; }
    .code-card { margin-top: 16px; overflow: hidden; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    .code-head { padding: 9px 12px; border-bottom: 1px solid var(--border); background: var(--surface-subtle); font-size: 10px; font-weight: 600; }
    .code-card pre { margin: 0; padding: 14px; overflow: auto; color: var(--text); font-size: 10px; line-height: 1.65; }
    .environment { padding: 16px; }
    .environment dl { margin: 14px 0 0; display: grid; grid-template-columns: auto 1fr; gap: 8px 12px; font-size: 10px; }
    .environment dt { color: var(--faint); }
    .environment dd { margin: 0; color: var(--text); font-family: var(--mono); overflow-wrap: anywhere; }
    .boundary {
      margin-top: 16px; padding: 12px; border-left: 3px solid var(--iq); border-radius: 0 8px 8px 0;
      color: var(--muted); background: var(--iq-soft); font-size: 10px;
    }
    @keyframes pulse { 50% { opacity: .3; } }
    @keyframes progress-breathe { from { opacity: .55; transform: translateX(-8%); } to { opacity: 1; transform: translateX(18%); } }
    @media (max-width: 1080px) {
      .app { grid-template-columns: 240px minmax(0, 1fr); }
      .chat-grid, .connection-layout { grid-template-columns: 1fr; }
      .side-stack { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .presenter { grid-column: 1 / -1; }
    }
    @media (max-width: 820px) {
      .app { grid-template-columns: 1fr; }
      .anatomy { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
      .anatomy-intro, .equation, .anatomy-part > p { display: none; }
      .anatomy-parts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
      .anatomy-part { margin: 0; }
      .anatomy-part summary { grid-template-columns: 28px 1fr 8px; padding: 6px; }
      .anatomy-part .chevron { display: none; }
      .journey { grid-template-columns: 1fr; gap: 8px; }
      .journey li { padding: 8px 0; border-left: 0; border-top: 1px solid var(--border); }
      .journey li:first-child { border-top: 0; }
      .stage-top svg { display: none; }
    }
    @media (max-width: 640px) {
      .topbar { align-items: flex-start; flex-wrap: wrap; }
      .tabs { order: 3; width: 100%; }
      .tab { flex: 1; justify-content: center; }
      .status-pill { margin-left: auto; }
      .pane-wrap { padding: 16px; }
      .side-stack { grid-template-columns: 1fr; }
      .anatomy-parts { grid-template-columns: 1fr; }
      .messages { padding: 14px; }
      .message-row { max-width: 100%; }
      .audit-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .audit-metric { min-width: 0; padding-right: 8px; }
      .audit-metric + .audit-metric { padding-left: 8px; }
      .finding-head { display: grid; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="anatomy" aria-label="Anatomy of the Foundry agent">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">${ICONS.shield}</span>
        <div><strong>Pharmashield</strong><small>Foundry · Contract evidence</small></div>
      </div>
      <p class="section-label">Anatomy of an agent</p>
      <p class="anatomy-intro">A contract-policy expert assembled in Microsoft Foundry with an explicit model, instructions, business context, conversation memory, and approved knowledge tools.</p>
      <div class="anatomy-parts">${anatomyRows}</div>
      <div class="equation">
        <strong>Model + Instructions + Context + Memory + Tools</strong><br />
        = a grounded agent. The Trace proves the knowledge tool ran.
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <div class="agent-title"><strong>contract-policy-expert</strong><small>Microsoft Foundry · <span id="header-model">gpt-5.5</span> · read-only evidence expert</small></div>
        <div class="tabs" role="tablist" aria-label="Foundry Agent views">
          <button class="tab" role="tab" aria-selected="true" aria-controls="pane-chat" id="tab-chat" data-pane="chat">${ICONS.chat}<span>Chat</span></button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="pane-trace" id="tab-trace" data-pane="trace">${ICONS.trace}<span>Trace</span><span class="count" id="trace-count" hidden>0</span></button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="pane-connection" id="tab-connection" data-pane="connection">${ICONS.connection}<span>Connection</span></button>
        </div>
        <span class="status-pill" id="overall-status"><span class="status-dot"></span><span>Checking Azure</span></span>
      </header>

      <ol class="journey" aria-label="Build, Deliver, Evaluate, Optimize, Govern journey">${journeyRows}</ol>

      <section class="pane active" id="pane-chat" role="tabpanel" aria-labelledby="tab-chat">
        <div class="pane-wrap chat-grid">
          <section class="panel conversation" aria-label="Live Foundry audit conversation">
            <div class="conversation-head">
              <div><h1>Audit an invoice against enterprise contracts.</h1><p>The Aster Ridge invoice supplies the transaction context; Foundry IQ retrieves approved contract knowledge.</p></div>
              <span class="context-chip">${ICONS.context}<span>${HERO_INVOICE.id}</span></span>
            </div>
            <div class="messages" aria-live="polite">
              <div class="message-row">
                <span class="avatar" aria-hidden="true">${ICONS.shield}</span>
                <div class="bubble">
                  <p><strong>The Aster Ridge invoice is attached as business context.</strong> It contains four lines and a printed total of ${money(HERO_INVOICE.total)}.</p>
                  <div class="context-note">
                    <strong>Grounding boundary:</strong> rate, fee, discount, and packaging claims must come from approved contract knowledge retrieved through Foundry IQ.
                  </div>
                  <p class="meta-line">Context · ${HERO_INVOICE.supplier} · ${HERO_INVOICE.purchaseOrder}</p>
                </div>
              </div>
              <div class="message-row user user-audit" id="user-audit">
                <span class="avatar" aria-hidden="true">${ICONS.chat}</span>
                <div class="bubble"><p>${CANONICAL_AUDIT_PROMPT}</p><p class="meta-line">Live contract-grounded audit</p></div>
              </div>
              <div class="retrieving" id="retrieving"><span class="retrieving-dot"></span><span>Consulting Foundry IQ through knowledge_base_retrieve…</span></div>
              <div class="message-row result-message" id="result-message">
                <span class="avatar" aria-hidden="true">${ICONS.shield}</span>
                <div class="bubble" id="result-bubble"></div>
              </div>
            </div>
          </section>

          <aside class="side-stack" aria-label="Presenter controls">
            <section class="card">
              <div class="card-head"><h2>Live readiness</h2><p>Uses the current <code>az login</code>. Tokens remain in process memory and are never sent to the browser.</p></div>
              <div class="checks" id="checks"></div>
              <div class="field">
                <label for="project">Foundry project</label>
                <select id="project" disabled><option>Discovering projects…</option></select>
              </div>
              <div class="buttons"><button class="btn btn-secondary" id="refresh" type="button">Refresh readiness</button></div>
            </section>
            <section class="card">
              <div class="card-head"><h2>Run the story</h2><p>Sends the contract-audit question to the real hosted expert and waits for its response.</p></div>
              <button class="btn btn-primary" id="start" type="button" disabled>Run grounded audit</button>
              <div class="progress" id="progress" role="progressbar" aria-label="Hosted audit progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div>
              <div class="run-message" id="run-message" aria-live="polite">Waiting for readiness checks.</div>
            </section>
            <section class="card presenter">
              <div class="card-head"><h2>Presenter beats</h2><p>The Foundry contract-expert story, with the governed platform journey kept in view.</p></div>
              <details>
                <summary>Open talk track</summary>
                <ol class="beats">${beatRows}</ol>
              </details>
            </section>
          </aside>
        </div>
      </section>

      <section class="pane" id="pane-trace" role="tabpanel" aria-labelledby="tab-trace" hidden>
        <div class="pane-wrap">
          <div class="pane-title"><h1>Trace</h1><p>The live protocol sequence: the Foundry IQ call, query payload, retrieved contract text, and exact source references returned to the hosted expert.</p></div>
          <div class="trace-layout">
            <section class="panel" id="trace-content">
              <div class="empty-state">
                <span class="empty-icon" aria-hidden="true">${ICONS.trace}</span>
                <h2>Run the grounded audit first</h2>
                <p>Trace remains empty until the hosted response contains a real <code>knowledge_base_retrieve</code> function call. A failed call is shown but does not pass the proof gate.</p>
              </div>
            </section>
          </div>
        </div>
      </section>

      <section class="pane" id="pane-connection" role="tabpanel" aria-labelledby="tab-connection" hidden>
        <div class="pane-wrap">
          <div class="pane-title"><h1>Assemble a contract-grounded expert</h1><p>The model, enterprise knowledge, and agent instructions remain explicit so each component can evolve independently.</p></div>
          <div class="connection-layout">
            <section>
              <div class="connection-steps">
                <article class="connection-step"><span>1</span><div><strong>Choose the model</strong><p>This expert uses <code id="connection-model">gpt-5.5</code>. Keeping model choice explicit lets different agents use the right model for each job.</p></div></article>
                <article class="connection-step"><span>2</span><div><strong>Connect approved knowledge</strong><p>Add <code>contracts-kb</code> through Foundry IQ so contract claims come from retrieved enterprise sources.</p></div></article>
                <article class="connection-step"><span>3</span><div><strong>Assemble the evidence expert</strong><p>Combine the model, instructions, and <code>knowledge_base_retrieve</code>. The invoice enters as request context; the expert returns evidence, not payment decisions.</p></div></article>
              </div>
              <div class="code-card">
                <div class="code-head">Architecture sketch · explicit model + approved knowledge</div>
                <pre><code>model = "<span id="code-model">gpt-5.5</span>"

foundry_client = FoundryChatClient(
    project_endpoint=selected_project,
    model=model,
    credential=DefaultAzureCredential(),
)

contract_knowledge = foundry_iq(
    knowledge_base="contracts-kb",
    tool="knowledge_base_retrieve",
)

contract_policy_expert = Agent(
    client=foundry_client,
    instructions=contract_policy_instructions,
    tools=[contract_knowledge],
)</code></pre>
              </div>
            </section>
            <aside class="panel environment">
              <h2>Live environment</h2>
              <p>Resolved from Azure at runtime, not hardcoded into the repository.</p>
              <dl>
                <dt>Project</dt><dd id="env-project">Resolving…</dd>
                <dt>Resource group</dt><dd id="env-rg">Resolving…</dd>
                <dt>Agent</dt><dd>contract-policy-expert</dd>
                <dt>Model</dt><dd id="env-model">gpt-5.5</dd>
                <dt>Knowledge</dt><dd>Foundry IQ · contracts-kb</dd>
                <dt>Protocol</dt><dd>Hosted Responses · background</dd>
                <dt>Grounding gate</dt><dd>successful knowledge_base_retrieve required</dd>
              </dl>
              <div class="boundary"><strong>Waypoint handoff:</strong> the expert is intentionally read-only. The orchestrator combines evidence, and the recorder is the only agent allowed to write the governed run.</div>
            </aside>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const state = { current: null };
    const invoice = ${JSON.stringify(HERO_INVOICE)};
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

    async function request(path, options = {}) {
      const response = await fetch(path, { ...options, headers: {'Content-Type':'application/json', ...(options.headers || {})} });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || ('Request failed: ' + response.status));
      return payload;
    }

    async function refresh() {
      try {
        state.current = await request('/api/state');
        render(state.current);
      } catch (error) {
        $('run-message').textContent = error.message;
      }
    }

    function render(data) {
      const ready = data.preflight?.status === 'ready';
      const failed = data.preflight?.status === 'error';
      const running = data.job?.status === 'running' || data.job?.status === 'starting';
      const started = running || Boolean(data.result) || Boolean(data.job?.startedAt);

      const status = $('overall-status');
      status.className = 'status-pill ' + (ready ? 'ready' : failed ? 'error' : '');
      status.querySelector('span:last-child').textContent = ready ? 'Foundry ready' : failed ? 'Setup required' : 'Checking Azure';

      setPart('model', ready);
      setPart('instructions', true);
      setPart('context', true);
      setPart('memory', started);
      setPart('tools', ready);

      $('checks').innerHTML = (data.preflight?.checks || []).map((check) =>
        '<div class="check ' + (check.ok ? 'ok' : check.ok === false ? 'fail' : '') + '">' +
          '<span class="check-icon">' + (check.ok ? '✓' : check.ok === false ? '×' : '·') + '</span>' +
          '<div><strong>' + esc(check.label) + '</strong><span>' + esc(check.detail) + '</span></div>' +
        '</div>'
      ).join('') || '<div class="check"><span class="check-icon">·</span><div><strong>Starting</strong><span>Resolving Azure identity and the hosted agent.</span></div></div>';

      const select = $('project');
      const projects = data.preflight?.projects || [];
      const project = data.preflight?.project;
      const selectedId = project?.id || '';
      const endpointProject = project?.endpoint?.split('/').filter(Boolean).at(-1);
      const projectName =
        project?.projectName ||
        (project?.displayName && project.displayName !== 'Configured project' ? project.displayName : endpointProject) ||
        'Configured project';
      const resourceGroup =
        project?.resourceGroup ||
        project?.id?.match(/\\/resourceGroups\\/([^/]+)/i)?.[1] ||
        'Not discovered';
      const model = data.preflight?.model || 'gpt-5.5';
      const visibleProjects = projects.filter((project) => project.score > 0 || project.id === selectedId);
      if (visibleProjects.length) {
        select.innerHTML = visibleProjects.map((project) =>
          '<option value="' + esc(project.id) + '"' + (project.id === selectedId ? ' selected' : '') + '>' +
            esc(project.projectName + ' · ' + project.resourceGroup) +
          '</option>'
        ).join('');
      } else if (data.preflight?.project) {
        select.innerHTML = '<option value="">' + esc(projectName) + '</option>';
      } else {
        select.innerHTML = '<option value="">No ready Waypoint or Forge project</option>';
      }
      select.disabled = visibleProjects.length < 2 || running;

      $('env-project').textContent = project ? projectName : 'Not ready';
      $('env-rg').textContent = resourceGroup;
      $('env-model').textContent = model;
      $('header-model').textContent = model;
      $('anatomy-model').textContent = model + ' · Microsoft Foundry';
      $('connection-model').textContent = model;
      $('code-model').textContent = model;
      $('start').disabled = !ready || running;
      $('start').textContent = running ? 'Running against Foundry IQ…' : data.job?.status === 'completed' ? 'Run grounded audit again' : 'Run grounded audit';
      $('refresh').disabled = running;
      $('run-message').textContent = data.job?.message || (ready ? 'Ready. The presenter controls when the live question is sent.' : data.preflight?.message || 'Waiting for readiness checks.');
      $('user-audit').classList.toggle('show', started);
      $('retrieving').classList.toggle('show', running);

      const progress = $('progress');
      progress.className = 'progress ' + (running ? 'running' : data.job?.status === 'completed' ? 'complete' : data.job?.status === 'error' ? 'error' : '');
      const progressValue = running ? 72 : data.job?.status === 'completed' ? 100 : data.job?.status === 'error' ? 100 : 0;
      progress.setAttribute('aria-valuenow', String(progressValue));
      progress.setAttribute('aria-valuetext', running ? 'Hosted audit in progress' : data.job?.status === 'completed' ? 'Hosted audit completed' : data.job?.status === 'error' ? 'Hosted audit failed' : 'Not started');

      if (data.result) {
        renderResult(data.result);
      } else {
        clearResult();
      }
    }

    function setPart(name, on) {
      document.querySelector('[data-part="' + name + '"]')?.classList.toggle('on', Boolean(on));
    }

    function clearResult() {
      $('result-message').classList.remove('show');
      $('result-bubble').innerHTML = '';
      $('trace-count').hidden = true;
      $('trace-count').textContent = '0';
      $('trace-count').removeAttribute('aria-label');
      $('trace-content').innerHTML = '<div class="empty-state"><span class="empty-icon">${ICONS.trace}</span><h2>No live trace yet</h2><p>Run the hosted audit to inspect the real knowledge-base request and response.</p></div>';
    }

    function renderResult(result) {
      const evidence = Array.isArray(result.parsedEvidence?.evidence) ? result.parsedEvidence.evidence : [];
      const unsupported = Array.isArray(result.parsedEvidence?.unsupported) ? result.parsedEvidence.unsupported : [];
      const grounded = Boolean(result.grounded);
      const summary = result.parsedEvidence?.summary || result.outputText || 'Foundry returned no summary.';
      const allFindings = grounded ? keyFindings(evidence) : [];
      const findings = grounded ? primaryFindings(evidence) : [];
      const recoveryCount = allFindings.filter((item) => item.supports === 'recover').length;
      const reviewCount = allFindings.filter((item) => ['review', 'escalate', 'unknown'].includes(item.supports)).length;
      const referenceCount = collectTraceSources(result, retrievalCalls(result), evidence).length;
      $('result-message').classList.add('show');
      $('result-bubble').innerHTML =
        '<section class="audit-overview">' +
          '<div class="audit-eyebrow">Foundry audit at a glance</div>' +
          '<h2>' + esc(auditHeadline(findings)) + '</h2>' +
          '<p class="result-summary">' + esc(summary) + '</p>' +
          '<div class="audit-metrics">' +
            auditMetric(recoveryCount, recoveryCount === 1 ? 'recovery signal' : 'recovery signals') +
            auditMetric(reviewCount, reviewCount === 1 ? 'review area' : 'review areas') +
            auditMetric(referenceCount, referenceCount === 1 ? 'source reference' : 'source references') +
          '</div>' +
        '</section>' +
        (findings.length
          ? '<section class="key-findings"><div class="key-findings-head"><h3>What matters</h3><span>Grounded contract evidence</span></div>' +
              '<div class="finding-list">' + findings.map((item) => renderFinding(item, unsupported)).join('') + '</div></section>'
          : '<section class="key-findings"><p>No structured evidence array was returned.</p></section>') +
        (unsupported.length
          ? '<details class="review-questions"><summary>Questions the evidence could not resolve<span>' + unsupported.length + ' open</span></summary>' +
              '<ul>' + unsupported.map((item) => '<li>' + esc(item) + '</li>').join('') + '</ul></details>'
          : '') +
        (evidence.length
          ? '<details class="evidence-details"><summary>View all retrieved evidence<span>' + evidence.length + ' items</span></summary>' +
              '<div class="evidence-list">' + evidence.map((item) =>
              '<article class="evidence"><div class="evidence-head"><strong>' + esc(item.claim || 'Grounded claim') + '</strong>' +
              '<span class="support ' + supportTone(item.supports) + '">' + esc(supportLabel(item.supports)) + '</span></div>' +
              '<p>Confidence ' + esc(confidenceLabel(item.confidence)) + '</p>' +
              '<p class="source">' + esc(item.source_ref || 'No source_ref returned') + '</p></article>'
            ).join('') + '</div></details>'
          : '') +
        (grounded
          ? '<button class="proof-banner" type="button" data-open-trace="true">${ICONS.trace}<span>Grounding verified · Open the live retrieval trace</span></button>'
          : '<div class="proof-banner" style="color:var(--danger);background:var(--danger-soft);border-color:var(--danger)">' +
              (result.retrievalAttempted
                ? 'Retrieval failed or returned no usable evidence. Do not present this response as contract-grounded.'
                : 'Grounding not proven. No knowledge-base retrieval was returned.') +
            '</div>');

      document.querySelector('[data-open-trace]')?.addEventListener('click', () => activateTab('trace'));
      renderTrace(result, evidence);
    }

    function keyFindings(evidence) {
      const normalized = evidence.map((item, index) => ({
        ...item,
        supports: String(item.supports || '').toLowerCase(),
        category: evidenceCategory(item.claim, index),
      }));
      const seen = new Set();
      return normalized
        .sort((left, right) => supportRank(left.supports) - supportRank(right.supports) || Number(right.confidence || 0) - Number(left.confidence || 0))
        .filter((item) => {
          if (seen.has(item.category.id)) return false;
          seen.add(item.category.id);
          return true;
        })
        .map((item) => ({
          ...item,
          related: normalized.filter((candidate) => candidate.category.id === item.category.id),
        }))
        .slice(0, 4);
    }

    function primaryFindings(evidence) {
      const findings = keyFindings(evidence);
      const preferred = findings.filter((item) => ['rate', 'packaging'].includes(item.category.id));
      return [...preferred, ...findings.filter((item) => !preferred.includes(item))].slice(0, 2);
    }

    function evidenceCategory(claim, index) {
      const text = String(claim || '');
      if (/ALLER-20|L002|base rate|unit rate/i.test(text)) return { id: 'rate', title: 'Unit-rate discrepancy' };
      if (/blister|packaging surcharge|packaging charge/i.test(text)) return { id: 'packaging', title: 'Packaging authorization' };
      if (/batch release|administration fee|QA acceptance/i.test(text)) return { id: 'batch', title: 'Batch-release evidence' };
      if (/volume discount|3,000,000|threshold/i.test(text)) return { id: 'discount', title: 'Volume discount' };
      return { id: 'evidence-' + index, title: 'Contract evidence' };
    }

    function supportRank(value) {
      return ({ recover: 0, escalate: 1, review: 2, unknown: 3, approve: 4 })[String(value || '').toLowerCase()] ?? 5;
    }

    function supportTone(value) {
      const tone = String(value || '').toLowerCase();
      return ['recover', 'escalate', 'review', 'approve'].includes(tone) ? tone : '';
    }

    function supportLabel(value) {
      return ({
        recover: 'Potential recovery',
        escalate: 'Escalate',
        review: 'Needs review',
        approve: 'Contract supported',
        unknown: 'Not confirmed',
      })[String(value || '').toLowerCase()] || 'Evidence';
    }

    function confidenceLabel(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return 'Not reported';
      const percentage = number <= 1 ? number * 100 : number;
      return Math.round(percentage) + '%';
    }

    function auditHeadline(findings) {
      if (findings.length > 1) return 'Foundry found ' + findings.length + ' priority findings.';
      if (findings.length === 1) return 'Foundry found one priority finding.';
      return 'The audit completed without structured findings.';
    }

    function auditMetric(value, label) {
      return '<div class="audit-metric"><strong>' + esc(value) + '</strong><span>' + esc(label) + '</span></div>';
    }

    function renderFinding(item, unsupported) {
      return '<article class="finding ' + supportTone(item.supports) + '">' +
        '<div class="finding-head"><h4>' + esc(item.category.title) + '</h4>' +
          '<span class="support ' + supportTone(item.supports) + '">' + esc(supportLabel(item.supports)) + '</span></div>' +
        '<p class="finding-claim">' + esc(sellerClaim(item, unsupported)) + '</p>' +
        '<div class="finding-meta">' +
          '<span class="confidence">${ICONS.shield}<span>Confidence ' + esc(confidenceLabel(item.confidence)) + '</span></span>' +
          '<span class="reference">${ICONS.connection}<span>' + esc(item.source_ref || 'No source reference returned') + '</span></span>' +
        '</div></article>';
    }

    function sellerClaim(item, unsupported) {
      const claim = String(item.claim || '');
      const relatedClaims = (item.related || [item]).map((candidate) => candidate.claim || '').join(' ');
      const openQuestions = unsupported.join(' ');
      if (item.category.id === 'rate') {
        const line = invoice.lines.find((candidate) => candidate.id === 'L002');
        const contractRate = matchNumber(relatedClaims, /USD\\s+([\\d.]+)\\s+per released tablet/i);
        if (line && contractRate !== null) {
          const effectiveRate = line.amount / line.quantity;
          const contractAmount = line.quantity * contractRate;
          const difference = line.amount - contractAmount;
          return 'Invoice L002 lists ' + currency(line.unitPrice) + ' per tablet, while its ' + currency(line.amount) +
            ' line amount implies an effective ' + unitCurrency(effectiveRate) + ' per tablet. The retrieved contract rate is ' +
            currency(contractRate) + ', which prices the line at ' + currency(contractAmount) +
            ' — a potential ' + currency(difference) + ' recovery.';
        }
      }
      if (item.category.id === 'packaging') {
        const line = invoice.lines.find((candidate) => /blister packaging/i.test(candidate.description));
        if (line) {
          const missing = /executed PO|explicitly authorized|blister packaging/i.test(openQuestions);
          return 'The ' + currency(line.amount) + ' blister-packaging surcharge requires a purchase order or written change authorization.' +
            (missing ? ' The retrieved evidence did not verify that authorization.' : '');
        }
      }
      if (item.category.id === 'batch') {
        const line = invoice.lines.find((candidate) => /batch release/i.test(candidate.description));
        const contractFee = matchNumber(relatedClaims, /USD\\s+([\\d,]+).*?(?:per released batch|once per released batch)/i);
        if (line && contractFee !== null) {
          const missing = /QA release packet|sponsor receipt|released status/i.test(openQuestions);
          return 'The ' + currency(line.amount) + ' batch-release charge uses the retrieved ' + currency(contractFee) +
            ' per-batch fee for ' + line.quantity + ' batches.' +
            (missing ? ' Sponsor QA acceptance still needs to be confirmed.' : '');
        }
      }
      if (item.category.id === 'discount') {
        const discount = matchNumber(relatedClaims, /(\\d+(?:\\.\\d+)?)%\\s+discount/i);
        const threshold = matchNumber(relatedClaims, /above\\s+([\\d,]+)\\s+tablets/i);
        const volume = invoice.lines
          .filter((line) => /tablet production/i.test(line.description))
          .reduce((total, line) => total + line.quantity, 0);
        if (discount !== null && threshold !== null) {
          const unresolved = /threshold.*ALLER-10.*ALLER-20|combined or only per product/i.test(openQuestions);
          return 'The invoice includes ' + volume.toLocaleString('en-US') + ' tablets across both products. The contract provides a ' +
            discount + '% discount above ' + threshold.toLocaleString('en-US') + ' tablets.' +
            (unresolved ? ' The retrieved evidence did not resolve whether that threshold combines both products.' : '');
        }
      }
      return claim || 'Grounded claim';
    }

    function matchNumber(text, pattern) {
      const match = String(text || '').match(pattern);
      if (!match) return null;
      const number = Number(match[1].replace(/,/g, ''));
      return Number.isFinite(number) ? number : null;
    }

    function currency(value) {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value);
    }

    function unitCurrency(value) {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      }).format(value);
    }

    function retrievalCalls(result) {
      const calls = Array.isArray(result.toolCalls) ? result.toolCalls : [];
      const grouped = new Map();
      for (const call of calls) {
        const key = call.callId || call.name || String(grouped.size);
        const current = grouped.get(key) || { callId: key, name: '', arguments: '', output: '', error: '' };
        if (call.name) current.name = call.name;
        if (call.arguments) current.arguments = call.arguments;
        if (call.output) current.output = call.output;
        if (call.error) current.error = call.error;
        grouped.set(key, current);
      }
      return [...grouped.values()].filter((call) => call.name.toLowerCase().includes('knowledge_base_retrieve'));
    }

    function renderTrace(result, evidence) {
      const retrievals = retrievalCalls(result);
      const findings = result.grounded ? primaryFindings(evidence) : [];
      const sources = collectTraceSources(result, retrievals, evidence);
      $('trace-count').hidden = findings.length === 0;
      $('trace-count').textContent = findings.length + (findings.length === 1 ? ' finding' : ' findings');
      $('trace-count').setAttribute('aria-label', findings.length + (findings.length === 1 ? ' grounded finding' : ' grounded findings'));
      $('trace-content').innerHTML = retrievals.length
        ? '<div class="trace-list">' +
            retrievals.map((call, index) => renderRetrievalSteps(call, index, retrievals.length)).join('') +
            renderTraceFindings(findings, result.parsedEvidence?.unsupported || []) +
            renderCitationStep(sources) +
          '</div>'
        : '<div class="empty-state"><span class="empty-icon">${ICONS.trace}</span><h2>No verified retrieval call</h2><p>The response completed without a recognized knowledge_base_retrieve invocation.</p></div>';
    }

    function renderRetrievalSteps(call, index, total) {
      const output = call.output || call.error || 'No retrieval payload returned.';
      const failed = traceOutputFailed(call.output, call.error);
      const suffix = index ? ' · call ' + (index + 1) : '';
      return traceStep(
        'Calling Foundry IQ' + suffix,
        '<p><code>knowledge_base_retrieve</code></p><p>Knowledge base · <code>contracts-kb</code> · invocation ' + (index + 1) + ' of ' + total + '</p>',
        '${ICONS.connection}'
      ) +
      traceStep(
        'Query sent to the knowledge base',
        '<pre class="trace-value">' + esc(traceQuery(call.arguments)) + '</pre>',
        '${ICONS.chat}'
      ) +
      traceStep(
        failed ? 'knowledge_base_retrieve failed' : 'knowledge_base_retrieve returned',
        '<pre class="trace-value">' + highlightTraceText(output) + '</pre>',
        '${ICONS.context}',
        failed
      );
    }

    function renderTraceFindings(findings, unsupported) {
      if (!findings.length) return '';
      const body = '<ul class="trace-findings">' + findings.map((item) =>
        '<li class="trace-finding ' + supportTone(item.supports) + '"><strong>' + esc(item.category.title) + '</strong>' +
          '<span>' + esc(supportLabel(item.supports)) + ' · ' + esc(confidenceLabel(item.confidence)) + ' confidence</span>' +
          '<span>' + esc(sellerClaim(item, unsupported)) + '</span></li>'
      ).join('') + '</ul>';
      return traceStep('Grounded findings · ' + findings.length, body, '${ICONS.shield}');
    }

    function traceStep(title, body, icon, failed = false) {
      return '<article class="trace-step' + (failed ? ' error' : '') + '">' +
        '<div class="trace-step-head">' + icon + '<span>' + esc(title) + '</span></div>' +
        '<div class="trace-step-body">' + body + '</div>' +
      '</article>';
    }

    function traceQuery(rawArguments) {
      if (!rawArguments) return 'No query payload returned.';
      try {
        const parsed = JSON.parse(rawArguments);
        if (Array.isArray(parsed.queries)) return parsed.queries.join('\\n');
        if (typeof parsed.query === 'string') return parsed.query;
      } catch {}
      return rawArguments;
    }

    function traceOutputFailed(output, error) {
      if (error || !String(output || '').trim()) return true;
      const value = String(output).trim();
      if (/^(error|function failed|failed\\b)/i.test(value)) return true;
      try {
        const parsed = JSON.parse(value);
        return Boolean(parsed && typeof parsed === 'object' && (parsed.error || parsed.errors));
      } catch {
        return false;
      }
    }

    function highlightTraceText(value) {
      const clauses = /USD 0\\.42 per released tablet|6% volume discount|blister packaging[^\\n.]{0,180}|purchase order or written change authorization[^\\n.]{0,220}|USD 4,800[^\\n.]{0,120}/gi;
      return esc(value).replace(clauses, (match) => '<mark class="trace-highlight">' + match + '</mark>');
    }

    function collectTraceSources(result, retrievals, evidence) {
      const groundedIds = new Set();
      const values = [];
      if (result.grounded) {
        for (const citation of Array.isArray(result.citations) ? result.citations : []) {
          const label = citation.title || citation.filename || citation.url;
          if (label || citation.url) {
            values.push({
              id: citation.url || label,
              title: label || 'Foundry citation',
              detail: citation.url || '',
            });
          }
        }
      }
      for (const call of retrievals) {
        if (traceOutputFailed(call.output, call.error)) continue;
        const output = String(call.output || '');
        for (const match of output.matchAll(/\\[?ref_id:([A-Za-z0-9._-]+)/gi)) {
          groundedIds.add(match[1]);
        }
      }
      const labels = evidenceSourceLabels(evidence);
      for (const id of groundedIds) {
        const source = labels.get(id);
        values.push(source || {
          id,
          title: 'Retrieved contract source',
          detail: 'The knowledge base returned this reference without a document label.',
        });
      }
      return [...new Map(values.map((source) => [source.id, source])).values()];
    }

    function evidenceSourceLabels(evidence) {
      const labels = new Map();
      const add = (id, title, detail) => {
        const current = labels.get(id) || { id, title: title || 'Retrieved contract source', details: [] };
        if ((!current.title || current.title === 'Retrieved contract source') && title) current.title = title;
        if (detail && !current.details.includes(detail)) current.details.push(detail);
        current.detail = current.details.slice(0, 3).join(' · ');
        labels.set(id, current);
      };
      for (const item of evidence) {
        const source = String(item.source_ref || '');
        let matched = false;
        for (const match of source.matchAll(/(?:^|;\\s*)([^;\\[]+?)\\s*\\[ref_id:([^\\]]+)\\]\\s*(?:[—-]\\s*([^;]+))?/g)) {
          matched = true;
          add(match[2], match[1].trim(), String(match[3] || '').trim());
        }
        if (!matched) {
          for (const match of source.matchAll(/(?:^|;\\s*)([^;]+?)\\s*;\\s*(?:KB\\s+)?ref_id:([A-Za-z0-9._-]+)/gi)) {
            matched = true;
            const label = sourceLabel(match[1]);
            add(match[2], label.title, label.detail);
          }
        }
        if (!matched) {
          const legacy = source.match(/^ref_id:([A-Za-z0-9._-]+);\\s*([^,;]+)(?:[,;]\\s*(.*))?$/);
          if (legacy) add(legacy[1], legacy[2].trim(), String(legacy[3] || '').trim());
        }
      }
      return labels;
    }

    function sourceLabel(value) {
      const parts = String(value || '').split(',').map((part) => part.trim()).filter(Boolean);
      return {
        title: parts.shift() || 'Retrieved contract source',
        detail: parts.join(', '),
      };
    }

    function renderCitationStep(sources) {
      const body = sources.length
        ? '<ul class="trace-citations">' + sources.map((source) =>
            '<li class="trace-citation"><strong>' + esc(source.title) + '</strong>' +
              '<span class="trace-citation-meta">Foundry reference · ref_id:' + esc(source.id) + '</span>' +
              (source.detail ? '<span class="trace-citation-detail">' + esc(source.detail) + '</span>' : '') +
            '</li>'
          ).join('') + '</ul>'
        : '<p>No source references were returned. The retrieval call remains visible, but the presenter should not claim exact citations.</p>';
      const count = sources.length === 1 ? '1 source reference' : sources.length + ' source references';
      return traceStep('Citations · ' + count, body, '${ICONS.trace}');
    }

    function activateTab(name) {
      document.querySelectorAll('[role="tab"]').forEach((tab) => {
        const active = tab.dataset.pane === name;
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      document.querySelectorAll('[role="tabpanel"]').forEach((pane) => {
        const active = pane.id === 'pane-' + name;
        pane.classList.toggle('active', active);
        pane.hidden = !active;
      });
    }

    document.querySelectorAll('[role="tab"]').forEach((tab) => {
      tab.addEventListener('click', () => activateTab(tab.dataset.pane));
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        const tabs = [...document.querySelectorAll('[role="tab"]')];
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const next = tabs[(tabs.indexOf(tab) + direction + tabs.length) % tabs.length];
        activateTab(next.dataset.pane);
        next.focus();
      });
    });

    $('start').addEventListener('click', async () => {
      $('start').disabled = true;
      try { await request('/api/run', {method:'POST', body:'{}'}); } catch (error) { $('run-message').textContent = error.message; }
      await refresh();
    });
    $('refresh').addEventListener('click', async () => {
      $('refresh').disabled = true;
      try { await request('/api/preflight', {method:'POST', body:'{}'}); } catch (error) { $('run-message').textContent = error.message; }
      await refresh();
    });
    $('project').addEventListener('change', async (event) => {
      if (!event.target.value) return;
      try { await request('/api/project', {method:'POST', body:JSON.stringify({resourceId:event.target.value})}); } catch (error) { $('run-message').textContent = error.message; }
      await refresh();
    });

    activateTab('chat');
    const events = new EventSource('/events');
    events.onmessage = () => refresh();
    refresh();
  </script>
</body>
</html>`;
}

function icon(paths) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
}

function money(value) {
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
    }).format(value);
}
