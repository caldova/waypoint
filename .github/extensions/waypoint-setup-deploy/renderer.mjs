// renderer.mjs — static iframe HTML/JS for the waypoint-setup-deploy canvas.
// Pure server-rendered strings; no client build step. Talks back to the
// extension's own loopback HTTP endpoints only (never to the host bridge).
export function renderHtml() {
    return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Waypoint guided setup + deploy</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 24px;
    background: var(--background-color-default, #ffffff);
    color: var(--text-color-default, #1f2328);
    font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
    font-size: var(--text-body-medium, 14px);
    line-height: var(--leading-body-medium, 20px);
  }
  h1 {
    font-size: var(--text-title-large, 22px);
    font-weight: var(--font-weight-semibold, 600);
    margin: 0 0 4px;
  }
  p.sub { color: var(--text-color-muted, #656d76); margin: 0 0 20px; }
  section {
    border: 1px solid var(--border-color-default, #d0d7de);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
  }
  h2 { font-size: var(--text-title-medium, 16px); margin: 0 0 12px; }
  label { display: block; font-weight: 600; margin: 10px 0 4px; }
  input[type="text"] {
    width: 100%;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border-color-default, #d0d7de);
    background: var(--background-color-default, #fff);
    color: var(--text-color-default, #1f2328);
    font-family: var(--font-mono, monospace);
    font-size: var(--text-body-medium, 13px);
  }
  button {
    margin-top: 12px;
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid var(--border-color-default, #d0d7de);
    background: var(--true-color-blue, #0969da);
    color: var(--color-white, #fff);
    font-weight: 600;
    cursor: pointer;
  }
  button.secondary { background: transparent; color: var(--text-color-default, #1f2328); }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .check-list { list-style: none; margin: 8px 0 0; padding: 0; }
  .check-list li {
    display: flex; gap: 8px; padding: 6px 0;
    border-bottom: 1px solid var(--border-color-default, #eaeef2);
  }
  .badge {
    display: inline-block; min-width: 44px; text-align: center;
    border-radius: 4px; padding: 1px 6px; font-weight: 700; font-size: 11px;
  }
  .badge.pass { background: var(--true-color-green-muted, #dafbe1); color: var(--true-color-green, #1a7f37); }
  .badge.warn { background: var(--true-color-yellow-muted, #fff8c5); color: #9a6700; }
  .badge.fail { background: var(--true-color-red-muted, #ffebe9); color: var(--true-color-red, #cf222e); }
  .remediation { color: var(--text-color-muted, #656d76); font-size: 12px; margin-top: 2px; }
  .confirm-row { display: flex; align-items: center; gap: 6px; margin-top: 10px; }
  a { color: var(--true-color-blue, #0969da); }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; }
  .muted { color: var(--text-color-muted, #656d76); }
</style>
</head>
<body>
  <h1>Waypoint guided setup + deploy</h1>
  <p class="sub">Preflight your Azure/GitHub access, then bootstrap OIDC and dispatch the one-click deploy — nothing mutates without your explicit confirmation below.</p>

  <section>
    <h2>1. Configuration</h2>
    <div id="config-view"></div>
  </section>

  <section>
    <h2>2. Admin preflight</h2>
    <div class="row">
      <button id="btn-preflight">Run preflight checks</button>
      <span id="preflight-status" class="muted"></span>
    </div>
    <ul class="check-list" id="preflight-checks"></ul>
  </section>

  <section>
    <h2>3. Bootstrap (Azure OIDC + repo config)</h2>
    <p class="muted">Runs the existing idempotent <code>oidc.sh</code> and sets repo variables/secrets. Safe to re-run.</p>
    <div class="confirm-row">
      <input type="checkbox" id="confirm-bootstrap" />
      <label style="margin:0" for="confirm-bootstrap">I confirm I want to bootstrap OIDC + repo config now</label>
    </div>
    <button id="btn-bootstrap" disabled>Bootstrap</button>
    <pre id="bootstrap-output" class="muted"></pre>
  </section>

  <section>
    <h2>4. Deploy</h2>
    <p class="muted">Dispatches <code>deploy.yml</code> with the derived, deterministic names below.</p>
    <div class="confirm-row">
      <input type="checkbox" id="confirm-deploy" />
      <label style="margin:0" for="confirm-deploy">I confirm I want to dispatch the deploy workflow now</label>
    </div>
    <button id="btn-deploy" disabled>Deploy</button>
    <div id="deploy-output"></div>
  </section>

  <section>
    <h2>5. Status &amp; links</h2>
    <div class="row">
      <button id="btn-refresh" class="secondary">Refresh status</button>
      <span id="refresh-status" class="muted"></span>
    </div>
    <div id="links-output"></div>
  </section>

<script>
async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

function badge(status) {
  return '<span class="badge ' + status + '">' + status.toUpperCase() + '</span>';
}

function renderConfig(state) {
  const c = state.config || {};
  const n = state.names || {};
  document.getElementById('config-view').innerHTML =
    '<div class="row"><strong>Subscription:</strong> <code>' + (c.subscriptionId || '') + '</code></div>' +
    '<div class="row"><strong>Tenant:</strong> <code>' + (c.tenantId || '') + '</code></div>' +
    '<div class="row"><strong>Region:</strong> <code>' + (c.region || '') + '</code></div>' +
    '<div class="row"><strong>Repo:</strong> <code>' + (c.targetRepo || '') + '</code></div>' +
    '<p class="muted">Derived env: <code>' + (n.azd_env_name || '') + '</code> &middot; RG: <code>' + (n.app_resource_group || '') + '</code> &middot; State RG: <code>' + (n.state_resource_group || '') + '</code></p>';
}

function renderPreflight(state) {
  const p = state.preflight;
  const statusEl = document.getElementById('preflight-status');
  const list = document.getElementById('preflight-checks');
  if (!p) { statusEl.textContent = 'Not run yet.'; list.innerHTML = ''; return; }
  statusEl.innerHTML = 'Overall: ' + badge(p.overall);
  list.innerHTML = (p.checks || []).map(function (check) {
    return '<li>' + badge(check.status) + '<div><strong>' + check.label + '</strong><div>' + check.detail + '</div>' +
      (check.remediation ? '<div class="remediation">' + check.remediation + '</div>' : '') + '</div></li>';
  }).join('');
}

function renderBootstrap(state) {
  const b = state.bootstrap;
  document.getElementById('bootstrap-output').textContent = b ? (b.ok ? 'Bootstrap succeeded.\\n' + (b.stdout || '') : 'Bootstrap failed.\\n' + (b.stderr || '')) : '';
}

function renderDeploy(state) {
  const d = state.deploy;
  const el = document.getElementById('deploy-output');
  if (!d) { el.innerHTML = ''; return; }
  if (!d.dispatched) { el.innerHTML = '<p class="muted">Dispatch failed: ' + (d.error || 'unknown error') + '</p>'; return; }
  if (!d.run_found) { el.innerHTML = '<p class="muted">Dispatched. Run pending discovery — click Refresh.</p>'; return; }
  el.innerHTML = '<p>Run <a href="' + d.url + '" target="_blank" rel="noopener">#' + d.run_id + '</a> &middot; status: ' + (d.status || 'unknown') + (d.conclusion ? ' (' + d.conclusion + ')' : '') + '</p>';
}

function renderLinks(state) {
  const l = state.links;
  const el = document.getElementById('links-output');
  if (!l || !l.ok) { el.innerHTML = '<p class="muted">No links recorded yet.</p>'; return; }
  el.innerHTML =
    (l.app_url ? '<p>App: <a href="' + l.app_url + '" target="_blank" rel="noopener">' + l.app_url + '</a></p>' : '') +
    (l.api_url ? '<p>API: <a href="' + l.api_url + '" target="_blank" rel="noopener">' + l.api_url + '</a></p>' : '') +
    (!l.app_url && !l.api_url ? '<p class="muted">Deploy has not recorded app/API links yet.</p>' : '');
}

function render(state) {
  renderConfig(state);
  renderPreflight(state);
  renderBootstrap(state);
  renderDeploy(state);
  renderLinks(state);
}

async function refreshState() {
  const state = await api('/api/state');
  render(state);
  return state;
}

document.getElementById('confirm-bootstrap').addEventListener('change', function (e) {
  document.getElementById('btn-bootstrap').disabled = !e.target.checked;
});
document.getElementById('confirm-deploy').addEventListener('change', function (e) {
  document.getElementById('btn-deploy').disabled = !e.target.checked;
});

document.getElementById('btn-preflight').addEventListener('click', async function () {
  this.disabled = true;
  document.getElementById('preflight-status').textContent = 'Running...';
  try { render(await api('/api/preflight', { method: 'POST' })); }
  catch (err) { document.getElementById('preflight-status').textContent = 'Error: ' + err.message; }
  finally { this.disabled = false; }
});

document.getElementById('btn-bootstrap').addEventListener('click', async function () {
  this.disabled = true;
  try { render(await api('/api/bootstrap', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) })); }
  catch (err) { document.getElementById('bootstrap-output').textContent = 'Error: ' + err.message; }
  finally { this.disabled = false; }
});

document.getElementById('btn-deploy').addEventListener('click', async function () {
  this.disabled = true;
  try { render(await api('/api/deploy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) })); }
  catch (err) { document.getElementById('deploy-output').innerHTML = '<p class="muted">Error: ' + err.message + '</p>'; }
  finally { this.disabled = false; }
});

document.getElementById('btn-refresh').addEventListener('click', async function () {
  this.disabled = true;
  document.getElementById('refresh-status').textContent = 'Refreshing...';
  try { render(await api('/api/refresh', { method: 'POST' })); document.getElementById('refresh-status').textContent = ''; }
  catch (err) { document.getElementById('refresh-status').textContent = 'Error: ' + err.message; }
  finally { this.disabled = false; }
});

refreshState().catch(function (err) { console.error(err); });
</script>
</body>
</html>`;
}
