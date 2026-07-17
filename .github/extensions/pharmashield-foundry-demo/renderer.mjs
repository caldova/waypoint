import { DEMO_BEATS, HERO_INVOICE } from "./demo-data.mjs";

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

const beatRows = DEMO_BEATS.map(
    (beat, index) => `
        <li data-beat="${beat.id}">
          <span class="step-index">${index + 1}</span>
          <div><strong>${beat.label}</strong><p>${beat.talkTrack}</p></div>
        </li>`,
).join("");

export function renderHtml() {
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pharmashield · Foundry live demo</title>
  <style>
    :root {
      --accent: var(--true-color-blue, #0969da);
      --accent-soft: var(--true-color-blue-muted, #ddf4ff);
      --success: #1a7f37;
      --warning: #9a6700;
      --danger: #cf222e;
      --surface: var(--background-color-default, #f6f8fa);
      --panel: var(--background-color-default, #ffffff);
      --panel-subtle: color-mix(in srgb, var(--text-color-default, #1f2328) 4%, var(--panel));
      --border: var(--border-color-default, #d0d7de);
      --text: var(--text-color-default, #1f2328);
      --muted: var(--text-color-muted, #59636e);
      --focus: var(--color-focus-outline, #0969da);
      --radius-sm: 6px;
      --radius-md: 8px;
      --radius-lg: 12px;
      --shadow: 0 1px 2px rgba(31, 35, 40, .05);
      --font: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      --mono: var(--font-mono, "SFMono-Regular", Consolas, monospace);
      --ease: cubic-bezier(.16, 1, .3, 1);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; }
    body {
      min-height: 100vh;
      background: var(--surface);
      color: var(--text);
      font: 14px/1.5 var(--font);
    }
    button, select { font: inherit; }
    button:focus-visible, select:focus-visible, [role="tab"]:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .shell { min-height: 100vh; display: grid; grid-template-columns: 280px minmax(0, 1fr); }
    aside {
      padding: 24px 20px;
      background: var(--panel);
      border-right: 1px solid var(--border);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }
    .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 32px; }
    .brand-mark {
      width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
      color: white; background: var(--accent);
    }
    .brand-mark svg { width: 20px; height: 20px; }
    .brand strong { display: block; font-size: 14px; }
    .brand span { color: var(--muted); font-size: 12px; }
    .eyebrow {
      color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .08em;
      text-transform: uppercase; margin: 0 0 12px;
    }
    .steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 16px; }
    .steps li { display: grid; grid-template-columns: 28px 1fr; gap: 12px; align-items: start; }
    .step-index {
      width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center;
      background: var(--panel-subtle); border: 1px solid var(--border); color: var(--muted);
      font: 600 12px/1 var(--font);
    }
    .steps strong { font-size: 13px; }
    .steps p { color: var(--muted); font-size: 12px; line-height: 1.45; margin: 4px 0 0; }
    .aside-note {
      margin-top: 32px; padding: 12px; border-radius: var(--radius-md);
      background: var(--panel-subtle); color: var(--muted); font-size: 12px;
    }
    main { min-width: 0; padding: 32px; }
    .content { max-width: 1120px; margin: 0 auto; }
    header { display: flex; gap: 24px; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
    h1 { font-size: clamp(24px, 3vw, 36px); line-height: 1.15; letter-spacing: -.025em; margin: 0 0 8px; }
    .lede { color: var(--muted); font-size: 15px; max-width: 720px; margin: 0; }
    .status-pill {
      display: inline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 4px 10px;
      border: 1px solid var(--border); border-radius: 999px; background: var(--panel);
      color: var(--muted); font-size: 12px; white-space: nowrap;
    }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warning); }
    .status-pill.ready .status-dot { background: var(--success); }
    .status-pill.error .status-dot { background: var(--danger); }
    .grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(280px, .85fr); gap: 24px; }
    .card {
      background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius-lg);
      padding: 24px; box-shadow: var(--shadow);
    }
    .card + .card { margin-top: 24px; }
    .card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
    .card h2 { font-size: 16px; margin: 0 0 4px; }
    .card-head p, .card > p { color: var(--muted); margin: 0; }
    .meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
    .meta div { padding: 12px; background: var(--panel-subtle); border-radius: var(--radius-md); }
    .meta span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 3px; }
    .meta strong { display: block; font-size: 13px; overflow-wrap: anywhere; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { text-align: left; color: var(--muted); font-size: 11px; font-weight: 600; padding: 8px; border-bottom: 1px solid var(--border); }
    td { padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
    tr:last-child td { border-bottom: 0; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    code, pre { font-family: var(--mono); }
    .run-panel { display: grid; gap: 16px; }
    .btn {
      border: 1px solid transparent; min-height: 44px; padding: 0 16px; border-radius: var(--radius-md);
      cursor: pointer; font-weight: 600; transition: background 150ms, transform 100ms var(--ease), opacity 150ms;
    }
    .btn:active { transform: translateY(1px); }
    .btn-primary { color: white; background: var(--accent); width: 100%; }
    .btn-primary:hover { background: color-mix(in srgb, var(--accent) 88%, black); }
    .btn-secondary { color: var(--text); background: var(--panel); border-color: var(--border); }
    .btn-secondary:hover { background: var(--panel-subtle); }
    .btn:disabled { cursor: not-allowed; opacity: .5; transform: none; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 12px; font-weight: 600; }
    select {
      width: 100%; min-height: 40px; padding: 0 10px; color: var(--text); background: var(--panel);
      border: 1px solid var(--border); border-radius: var(--radius-md);
    }
    .checks { display: grid; gap: 10px; }
    .check { display: grid; grid-template-columns: 18px 1fr; gap: 10px; align-items: start; }
    .check-icon {
      width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
      background: var(--panel-subtle); border: 1px solid var(--border); color: var(--muted);
      font-size: 11px; margin-top: 1px;
    }
    .check.ok .check-icon { color: white; background: var(--success); border-color: var(--success); }
    .check.fail .check-icon { color: white; background: var(--danger); border-color: var(--danger); }
    .check strong { display: block; font-size: 12px; }
    .check span { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; overflow-wrap: anywhere; }
    .progress {
      height: 4px; overflow: hidden; border-radius: 999px; background: var(--panel-subtle);
    }
    .progress span {
      display: block; width: 0; height: 100%; background: var(--accent);
      transition: width 300ms var(--ease);
    }
    .progress.running span { width: 72%; animation: breathe 1.6s ease-in-out infinite alternate; }
    .progress.complete span { width: 100%; background: var(--success); }
    .progress.error span { width: 100%; background: var(--danger); }
    @keyframes breathe { from { opacity: .55; transform: translateX(-8%); } to { opacity: 1; transform: translateX(18%); } }
    .message {
      padding: 12px; border-radius: var(--radius-md); background: var(--panel-subtle);
      color: var(--muted); font-size: 12px; min-height: 44px;
    }
    .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
    .tab {
      min-height: 44px; padding: 0 12px; border: 0; border-bottom: 2px solid transparent;
      background: transparent; color: var(--muted); cursor: pointer;
    }
    .tab[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
    .pane[hidden] { display: none; }
    .evidence-list, .trace-list { display: grid; gap: 12px; }
    .evidence, .trace-item {
      padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-md);
      background: var(--panel);
    }
    .evidence strong, .trace-item strong { display: block; margin-bottom: 4px; }
    .evidence p, .trace-item p { color: var(--muted); margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .source { margin-top: 8px; color: var(--accent); font: 11px/1.45 var(--mono); }
    .empty { padding: 32px 16px; text-align: center; color: var(--muted); }
    .error-box { color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, var(--panel)); border: 1px solid color-mix(in srgb, var(--danger) 30%, var(--border)); }
    .live-proof {
      display: none; margin-bottom: 16px; padding: 12px; border-radius: var(--radius-md);
      border: 1px solid color-mix(in srgb, var(--success) 35%, var(--border));
      background: color-mix(in srgb, var(--success) 8%, var(--panel)); color: var(--success); font-weight: 600;
    }
    .live-proof.show { display: block; }
    pre.raw {
      white-space: pre-wrap; overflow-wrap: anywhere; padding: 14px; margin: 0;
      background: var(--panel-subtle); border-radius: var(--radius-md); color: var(--muted); font-size: 11px;
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; }
      aside { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
      .steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main { padding: 24px 16px; }
      .grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 600px) {
      header { display: grid; }
      .steps, .meta { grid-template-columns: 1fr; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>
        </span>
        <div><strong>Pharmashield</strong><span>Foundry-only runbook</span></div>
      </div>
      <p class="eyebrow">Presenter beats</p>
      <ol class="steps">${beatRows}</ol>
      <div class="aside-note">
        No Ollama, local model, or Waypoint web UI. This surface calls the hosted Foundry agent directly with your Azure identity.
      </div>
    </aside>
    <main>
      <div class="content">
        <header>
          <div>
            <p class="eyebrow">Live invoice assurance</p>
            <h1>From invoice to defensible evidence</h1>
            <p class="lede">The original Pharmashield Aster Ridge story, simplified to one production path: a hosted agent grounded on real contracts through Foundry IQ.</p>
          </div>
          <span class="status-pill" id="overall-status"><span class="status-dot"></span><span>Checking readiness</span></span>
        </header>
        <div class="grid">
          <div>
            <section class="card">
              <div class="card-head">
                <div><h2>Hero invoice</h2><p>The same four-line Aster Ridge invoice used by the canonical Pharmashield Foundry story.</p></div>
                <strong class="num">${money(HERO_INVOICE.total)}</strong>
              </div>
              <div class="meta">
                <div><span>Supplier</span><strong>${HERO_INVOICE.supplier}</strong></div>
                <div><span>Invoice</span><strong>${HERO_INVOICE.id}</strong></div>
                <div><span>Purchase order</span><strong>${HERO_INVOICE.purchaseOrder}</strong></div>
              </div>
              <div style="overflow-x:auto">
                <table>
                  <thead><tr><th>Line</th><th>Description</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Amount</th></tr></thead>
                  <tbody>${invoiceRows}</tbody>
                </table>
              </div>
            </section>
            <section class="card">
              <div class="tabs" role="tablist" aria-label="Demo output">
                <button class="tab" role="tab" aria-selected="true" data-pane="evidence">Grounded evidence</button>
                <button class="tab" role="tab" aria-selected="false" data-pane="trace">Live trace</button>
                <button class="tab" role="tab" aria-selected="false" data-pane="raw">Raw response</button>
              </div>
              <div class="live-proof" id="live-proof">Live grounding confirmed: the hosted response contains a real knowledge_base_retrieve tool call.</div>
              <div class="pane" id="pane-evidence"><div class="empty">Run the live audit to populate grounded contract evidence.</div></div>
              <div class="pane" id="pane-trace" hidden><div class="empty">The trace remains empty until Foundry invokes its knowledge-base tool.</div></div>
              <div class="pane" id="pane-raw" hidden><pre class="raw">No hosted response yet.</pre></div>
            </section>
          </div>
          <div>
            <section class="card run-panel">
              <div><h2>Live readiness</h2><p>Uses your current <code>az login</code>; no secrets are stored in the repo or browser.</p></div>
              <div class="checks" id="checks"></div>
              <div class="field">
                <label for="project">Foundry project</label>
                <select id="project" disabled><option>Discovering projects…</option></select>
              </div>
              <button class="btn btn-secondary" id="refresh" type="button">Refresh readiness</button>
            </section>
            <section class="card run-panel">
              <div><h2>Run the story</h2><p>The button sends the invoice to <code>contract-policy-expert</code> in background mode and polls until it reaches a terminal state.</p></div>
              <button class="btn btn-primary" id="start" type="button" disabled>Start live Foundry audit</button>
              <div class="progress" id="progress"><span></span></div>
              <div class="message" id="run-message">Waiting for readiness checks.</div>
            </section>
          </div>
        </div>
      </div>
    </main>
  </div>
  <script>
    const state = { current: null };
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
      const status = $('overall-status');
      status.className = 'status-pill ' + (ready ? 'ready' : failed ? 'error' : '');
      status.querySelector('span:last-child').textContent = ready ? 'Ready for Foundry' : failed ? 'Setup required' : 'Checking readiness';

      $('checks').innerHTML = (data.preflight?.checks || []).map((check) =>
        '<div class="check ' + (check.ok ? 'ok' : check.ok === false ? 'fail' : '') + '">' +
          '<span class="check-icon">' + (check.ok ? '✓' : check.ok === false ? '×' : '·') + '</span>' +
          '<div><strong>' + esc(check.label) + '</strong><span>' + esc(check.detail) + '</span></div>' +
        '</div>'
      ).join('') || '<div class="check"><span class="check-icon">·</span><div><strong>Starting</strong><span>Resolving Azure and Foundry configuration.</span></div></div>';

      const select = $('project');
      const projects = data.preflight?.projects || [];
      const selectedId = data.preflight?.project?.id || '';
      select.innerHTML = projects.map((project) =>
        '<option value="' + esc(project.id) + '"' + (project.id === selectedId ? ' selected' : '') + '>' +
          esc(project.projectName + ' · ' + project.resourceGroup + ' · ' + project.location) +
        '</option>'
      ).join('') || '<option value="">No visible Foundry projects</option>';
      select.disabled = projects.length < 2 || data.job?.status === 'running';

      const running = data.job?.status === 'running' || data.job?.status === 'starting';
      $('start').disabled = !ready || running;
      $('refresh').disabled = running;
      $('run-message').textContent = data.job?.message || (ready ? 'Ready. Keep this panel visible and click once when you reach the live beat.' : data.preflight?.message || 'Waiting for readiness checks.');
      const progress = $('progress');
      progress.className = 'progress ' + (running ? 'running' : data.job?.status === 'completed' ? 'complete' : data.job?.status === 'error' ? 'error' : '');

      if (data.result) renderResult(data.result);
    }

    function renderResult(result) {
      $('live-proof').classList.toggle('show', Boolean(result.grounded));
      const evidence = result.parsedEvidence?.evidence;
      $('pane-evidence').innerHTML = Array.isArray(evidence) && evidence.length
        ? '<div class="evidence-list">' + evidence.map((item) =>
            '<article class="evidence"><strong>' + esc(item.claim || 'Grounded claim') + '</strong>' +
            '<p>Supports: ' + esc(item.supports || 'unknown') + ' · Confidence: ' + esc(item.confidence ?? '—') + '</p>' +
            '<div class="source">' + esc(item.source_ref || 'No source_ref returned') + '</div></article>'
          ).join('') + '</div>'
        : '<div class="message ' + (result.grounded ? '' : 'error-box') + '">' +
            esc(result.grounded ? (result.outputText || 'Foundry returned no structured evidence array.') : 'The hosted response did not prove a knowledge_base_retrieve call. Do not present this as grounded.') +
          '</div>';
      $('pane-trace').innerHTML = result.toolCalls?.length
        ? '<div class="trace-list">' + result.toolCalls.map((call) =>
            '<article class="trace-item"><strong>' + esc(call.name || call.type || 'Tool call') + '</strong>' +
            '<p>' + esc(call.arguments || call.output || call.error || 'No trace payload returned.') + '</p></article>'
          ).join('') + '</div>'
        : '<div class="empty">No MCP or tool-call items were present in the hosted response.</div>';
      $('pane-raw').innerHTML = '<pre class="raw">' + esc(result.outputText || JSON.stringify(result, null, 2)) + '</pre>';
    }

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
      try { await request('/api/project', {method:'POST', body:JSON.stringify({resourceId:event.target.value})}); } catch (error) { $('run-message').textContent = error.message; }
      await refresh();
    });
    document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((item) => item.setAttribute('aria-selected', String(item === tab)));
      document.querySelectorAll('.pane').forEach((pane) => { pane.hidden = pane.id !== 'pane-' + tab.dataset.pane; });
    }));
    const events = new EventSource('/events');
    events.onmessage = () => refresh();
    refresh();
  </script>
</body>
</html>`;
}

function money(value) {
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
    }).format(value);
}
