#!/usr/bin/env node
/**
 * Copy the contract-policy-analyst quality.json written by the eval pipeline
 * into public/ so the story page (/quality/contract-policy-analyst) can load it.
 *
 * Refuses fixture files and files missing a story rung, so illustrative data
 * can never be published as results.
 *
 * Usage: npm run quality:sync [-- <path-to-quality.json>]
 */

import { copyFileSync, existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webDir, "../../..");
const source = path.resolve(
  process.argv[2] ??
    path.join(repoRoot, "modules/optimization/evidence/contract-policy-analyst/quality.json"),
);
const target = path.join(webDir, "public/quality/contract-policy-analyst.quality.json");

function fail(message) {
  console.error(`quality:sync: ${message}`);
  process.exit(1);
}

if (!existsSync(source)) fail(`no pipeline output at ${source}`);
let data;
try {
  data = JSON.parse(readFileSync(source, "utf8"));
} catch (error) {
  fail(`${source} is not valid JSON (${error.message})`);
}
if (data.fixture === true) fail(`${source} is marked "fixture": true; only real results can be published`);
if (data.agent !== "contract-policy-analyst") fail(`expected agent "contract-policy-analyst", got "${data.agent}"`);
for (const arm of ["mai2-rft"]) {
  if (!data.arms?.[arm]?.results) fail(`missing arm "${arm}"`);
}
const tracks = ["astra62", "astra"].filter(
  (t) => data.arms?.[`baseline-${t}`]?.results && data.arms?.[`optimized-${t}`]?.results,
);
if (tracks.length === 0) fail('needs a complete track: "baseline-astra62" + "optimized-astra62" or the "astra" pair');
if (data.headline_split && (data.regression_splits ?? []).includes(data.headline_split)) {
  fail(`headline_split "${data.headline_split}" is listed in regression_splits; exposed-source evidence can't be the headline`);
}

copyFileSync(source, target);
console.log(`quality:sync: ${path.relative(repoRoot, source)} -> ${path.relative(repoRoot, target)}`);
