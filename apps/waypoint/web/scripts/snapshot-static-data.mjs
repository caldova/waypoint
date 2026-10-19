#!/usr/bin/env node
/**
 * Capture a scrubbed snapshot of the live Waypoint API for the static copy.
 *
 *   WAYPOINT_API_URL=https://<api-host> WAYPOINT_API_TOKEN=<bearer token> \
 *     npm run snapshot:static
 *
 * Auth: WAYPOINT_API_TOKEN (a signed-in user's API access token) or
 * WAYPOINT_API_KEY (reader x-api-key, when the API has key auth enabled).
 *
 * Writes static-data/snapshot.json and static-data/pdfs/<invoice>.pdf, then
 * prints what it scrubbed. Review the report and the diff before pushing:
 * the repository is public.
 *
 * Scrubbing:
 *   - Email addresses outside synthetic domains (*.example, *.test, ...) become
 *     sample Caldova identities.
 *   - Literal replacements from scripts/static-scrub.local.json, or the file in
 *     WAYPOINT_SCRUB_FILE ("replace": {...}). Gitignored: it names the people
 *     being scrubbed. See scripts/static-scrub.example.json.
 *   - Azure subscription/tenant ids, resource host names, and signed URL
 *     query strings are neutralized.
 */

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(webDir, "static-data");
const pdfDir = join(outDir, "pdfs");
const scrubConfigPath =
  process.env.WAYPOINT_SCRUB_FILE ?? join(webDir, "scripts", "static-scrub.local.json");

const apiUrl = (process.env.WAYPOINT_API_URL ?? "").replace(/\/+$/, "");
const token = process.env.WAYPOINT_API_TOKEN?.replace(/^Bearer\s+/i, "");
const apiKey = process.env.WAYPOINT_API_KEY;

if (!apiUrl || (!token && !apiKey)) {
  console.error("Set WAYPOINT_API_URL and WAYPOINT_API_TOKEN (or WAYPOINT_API_KEY). See docs/static-clone.md.");
  process.exit(1);
}

const headers = token ? { Authorization: `Bearer ${token}` } : { "x-api-key": apiKey };

// Synthetic, non-personal, or machine identities that look like email addresses:
// corpus domains (*.example), Teams chat/thread ids, and app identities (*.local).
const SAFE_EMAIL_DOMAIN =
  /(^|\.)(example|test|invalid|localhost|local)$|^example\.(com|org|net)$|^(unq\.gbl\.spaces|thread\.v2|thread\.skype|thread\.tacv2)$/i;
const SAMPLE_PEOPLE = [
  "avery.chen",
  "jordan.patel",
  "riley.okafor",
  "morgan.silva",
  "casey.nguyen",
  "taylor.brooks",
  "quinn.rivera",
  "drew.kim",
  "sam.ortega",
  "jamie.larsen",
];
const SAMPLE_DOMAIN = "caldova.com";
const STATIC_USER_EMAIL = "analyst@caldova.com";

const responses = {};
const report = { emails: new Map(), literals: new Map(), azure: new Map() };

await main();

async function main() {
  console.log(`Capturing ${apiUrl} ...`);

  const decisions = await capture("/api/invoice-decisions");
  const runs = await capture("/api/runs");
  if (!Array.isArray(decisions) || !Array.isArray(runs)) {
    throw new Error("Unexpected response shape from /api/invoice-decisions or /api/runs.");
  }

  rmSync(pdfDir, { recursive: true, force: true });
  mkdirSync(pdfDir, { recursive: true });

  const pdfs = [];
  const caseIds = new Set(
    [...runs.map((run) => run.case_id), ...decisions.map((decision) => decision.agent_case_id)].filter(Boolean),
  );

  await mapLimit(decisions, 4, async (decision) => {
    const id = decision.invoice_id;
    await capture(`/api/invoices/${enc(id)}`);
    const assurance = await capture(`/api/invoices/${enc(id)}/assurance`, { optional: true });
    for (const view of assurance?.cases ?? []) {
      if (view?.case?.id) caseIds.add(view.case.id);
    }
    const cases = await capture(`/api/cases?invoice_id=${enc(id)}`, { optional: true });
    for (const item of cases ?? []) {
      if (item?.id) caseIds.add(item.id);
    }
    if (await capturePdf(id)) pdfs.push(id);
  });

  await mapLimit([...caseIds], 4, async (caseId) => {
    await capture(`/api/cases/${enc(caseId)}`, { optional: true });
    await capture(`/api/cases/${enc(caseId)}/recommendations`, { optional: true });
    await capture(`/api/cases/${enc(caseId)}/drafts`, { optional: true });
  });

  const contractIds = new Set();
  const policyIds = new Set();
  collectDocumentIds(responses, contractIds, policyIds);
  await mapLimit([...contractIds], 4, (id) =>
    capture(`/api/contract-documents/${enc(id)}?include_content=true`, { optional: true }),
  );
  await mapLimit([...policyIds], 4, (id) =>
    capture(`/api/policies/${enc(id)}?include_content=true`, { optional: true }),
  );

  const scrubbed = scrub(responses);
  const snapshot = {
    schema_version: 1,
    captured_at: new Date().toISOString(),
    responses: sortKeys(scrubbed),
    pdfs: pdfs.sort(),
  };

  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, "snapshot.json"), `${JSON.stringify(snapshot, null, 1)}\n`);

  console.log(
    `\nWrote static-data/snapshot.json: ${Object.keys(responses).length} responses, ` +
      `${decisions.length} invoices, ${runs.length} runs, ${caseIds.size} cases, ` +
      `${contractIds.size} contracts, ${policyIds.size} policies, ${pdfs.length} PDFs.`,
  );
  printReport(scrubbed);
}

// ---------------------------------------------------------------------------
// Capture
// ---------------------------------------------------------------------------

async function capture(path, { optional = false } = {}) {
  const response = await fetch(`${apiUrl}${path}`, { headers });
  if (!response.ok) {
    if (optional && (response.status === 404 || response.status === 409)) {
      return null;
    }
    if (response.status === 401 || response.status === 403) {
      throw new Error(`${path} returned ${response.status}. Is the token expired?`);
    }
    throw new Error(`${path} returned ${response.status} ${response.statusText}`);
  }
  const body = await response.json();
  responses[responseKey(path)] = body;
  return body;
}

async function capturePdf(invoiceId) {
  const response = await fetch(`${apiUrl}/api/invoices/${enc(invoiceId)}/pdf`, { headers });
  if (!response.ok) {
    return false;
  }
  writeFileSync(join(pdfDir, `${invoiceId}.pdf`), Buffer.from(await response.arrayBuffer()));
  return true;
}

/** Must match `responseKey` in lib/staticApi.ts. */
function responseKey(pathWithQuery) {
  const url = new URL(pathWithQuery, "http://snapshot.local");
  const path = url.pathname
    .split("/")
    .map((segment) => decodeURIComponent(segment))
    .join("/");
  const entries = [...url.searchParams.entries()]
    .filter(([key]) => key !== "include_content")
    .sort(([a], [b]) => a.localeCompare(b));
  const query = new URLSearchParams(entries).toString();
  return query ? `${path}?${query}` : path;
}

function collectDocumentIds(value, contractIds, policyIds) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectDocumentIds(item, contractIds, policyIds));
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    const target = /^contract_document_ids?$/.test(key)
      ? contractIds
      : /^policy_ids?$/.test(key)
        ? policyIds
        : null;
    if (target) {
      for (const id of Array.isArray(item) ? item : [item]) {
        if (typeof id === "string" && id) target.add(id);
      }
    } else {
      collectDocumentIds(item, contractIds, policyIds);
    }
  }
}

// ---------------------------------------------------------------------------
// Scrubbing
// ---------------------------------------------------------------------------

function scrub(value) {
  const literals = loadLiteralReplacements();
  const emailMap = new Map();
  const nextPerson = () => {
    const name = SAMPLE_PEOPLE[emailMap.size % SAMPLE_PEOPLE.length];
    const suffix = emailMap.size >= SAMPLE_PEOPLE.length ? Math.floor(emailMap.size / SAMPLE_PEOPLE.length) + 1 : "";
    return `${name}${suffix}@${SAMPLE_DOMAIN}`;
  };

  const scrubString = (input) => {
    let text = input;
    for (const [from, to] of literals) {
      if (text.includes(from)) {
        text = text.split(from).join(to);
        count(report.literals, from);
      }
    }
    text = text.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, (email) => {
      const domain = email.split("@")[1].toLowerCase();
      if (SAFE_EMAIL_DOMAIN.test(domain) || email.toLowerCase() === STATIC_USER_EMAIL) {
        return email;
      }
      const key = email.toLowerCase();
      if (!emailMap.has(key)) emailMap.set(key, nextPerson());
      count(report.emails, `${key} -> ${emailMap.get(key)}`);
      return emailMap.get(key);
    });
    text = text.replace(
      /\/(subscriptions|tenants)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
      (match, kind) => {
        count(report.azure, `${kind} id`);
        return `/${kind}/00000000-0000-0000-0000-000000000000`;
      },
    );
    text = text.replace(
      /\b[a-z0-9-]+\.(services\.ai\.azure\.com|cognitiveservices\.azure\.com|openai\.azure\.com|search\.windows\.net|azurecontainerapps\.io|blob\.core\.windows\.net|dfs\.core\.windows\.net|vault\.azure\.net)\b/gi,
      (match, suffix) => {
        count(report.azure, `*.${suffix}`);
        return `caldova.${suffix}`;
      },
    );
    text = text.replace(
      /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(@onelake\.)/gi,
      (match, guid, rest) => {
        count(report.azure, "onelake workspace id");
        return `00000000-0000-0000-0000-000000000000${rest}`;
      },
    );
    // 1:1 Teams chat ids are built from the two members' Entra object ids.
    text = text.replace(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=(@|%40)unq\.gbl\.spaces)/gi,
      () => {
        count(report.azure, "Teams 1:1 chat member ids");
        return "00000000-0000-0000-0000-000000000000_00000000-0000-0000-0000-000000000000";
      },
    );
    text = text.replace(/(https?:\/\/[^\s"']+?)\?[^\s"']*\bsig=[^\s"']*/gi, (match, url) => {
      count(report.azure, "signed URL query");
      return url;
    });
    return text;
  };

  const walk = (item) => {
    if (typeof item === "string") return scrubString(item);
    if (Array.isArray(item)) return item.map(walk);
    if (item && typeof item === "object") {
      return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, walk(child)]));
    }
    return item;
  };
  return walk(value);
}

function loadLiteralReplacements() {
  if (!existsSync(scrubConfigPath)) {
    return [];
  }
  const config = JSON.parse(readFileSync(scrubConfigPath, "utf8"));
  // Longest first so "Jane Doe" wins over "Jane".
  return Object.entries(config.replace ?? {}).sort(([a], [b]) => b.length - a.length);
}

function printReport(scrubbed) {
  const section = (title, map) => {
    console.log(`\n${title}:`);
    if (map.size === 0) {
      console.log("  (none)");
      return;
    }
    for (const [key, n] of [...map.entries()].sort()) console.log(`  ${key}  (${n})`);
  };
  section("Emails replaced", report.emails);
  section("Literal replacements (scrub file)", report.literals);
  section("Azure identifiers neutralized", report.azure);

  // Person-like names left in the data, for a manual check before pushing.
  const names = new Map();
  const visit = (item) => {
    if (typeof item === "string") {
      for (const match of item.matchAll(/\b([A-Z][a-z]{2,})\s([A-Z][a-z]{2,})\b/g)) {
        count(names, match[0]);
      }
    } else if (Array.isArray(item)) item.forEach(visit);
    else if (item && typeof item === "object") Object.values(item).forEach(visit);
  };
  visit(scrubbed);
  const top = [...names.entries()].sort((a, b) => b[1] - a[1]).slice(0, 60);
  console.log("\nCapitalized word pairs still in the data (check for real people; add to scripts/static-scrub.local.json):");
  console.log(`  ${top.map(([name, n]) => `${name} (${n})`).join(", ")}`);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function enc(value) {
  return encodeURIComponent(value);
}

function count(map, key) {
  map.set(key, (map.get(key) ?? 0) + 1);
}

function sortKeys(object) {
  return Object.fromEntries(Object.entries(object).sort(([a], [b]) => a.localeCompare(b)));
}

async function mapLimit(items, limit, fn) {
  let index = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (index < items.length) {
      const item = items[index++];
      await fn(item);
    }
  });
  await Promise.all(workers);
}
