#!/usr/bin/env node
/**
 * Verify every locale's resource files match English (the source of truth):
 * same keys, the plural forms each language needs, no empty strings, and the
 * same {{interpolation}} variables and <tag> placeholders.
 *
 * Usage: npm run i18n:check
 */

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_LOCALE = "en";
const PLURAL_SUFFIXES = ["zero", "one", "two", "few", "many", "other"];
const localesDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../app/i18n/locales",
);

const errors = [];

function flatten(value, prefix, out, file) {
  for (const [key, child] of Object.entries(value)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (typeof child === "string") {
      out.set(fullKey, child);
    } else if (child && typeof child === "object" && !Array.isArray(child)) {
      flatten(child, fullKey, out, file);
    } else {
      errors.push(`${file}: "${fullKey}" must be a string or object`);
    }
  }
  return out;
}

function load(locale, file) {
  const fullPath = path.join(localesDir, locale, file);
  try {
    return flatten(JSON.parse(readFileSync(fullPath, "utf8")), "", new Map(), `${locale}/${file}`);
  } catch (error) {
    errors.push(`${locale}/${file}: ${error.message}`);
    return new Map();
  }
}

function pluralBase(key, keys) {
  const match = key.match(new RegExp(`^(.*)_(${PLURAL_SUFFIXES.join("|")})$`));
  return match && keys.has(`${match[1]}_other`) ? match[1] : null;
}

function placeholders(text) {
  const vars = [...text.matchAll(/{{\s*-?\s*([\w.]+)[^}]*}}/g)].map((m) => `{{${m[1]}}}`);
  const tags = [...text.matchAll(/<\/?(\w+)\s*\/?>/g)].map((m) => `<${m[1]}>`);
  return [...vars, ...tags].sort().join(" ");
}

const locales = readdirSync(localesDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name);
const sourceFiles = readdirSync(path.join(localesDir, SOURCE_LOCALE)).filter((f) => f.endsWith(".json"));

for (const file of sourceFiles) {
  const source = load(SOURCE_LOCALE, file);
  for (const [key, text] of source) {
    if (!text.trim()) errors.push(`${SOURCE_LOCALE}/${file}: "${key}" is empty`);
  }

  // Split the English keys into plain keys and plural groups.
  const plain = new Map();
  const plurals = new Map();
  for (const [key, text] of source) {
    const base = pluralBase(key, source);
    if (base) {
      if (key === `${base}_other`) plurals.set(base, text);
    } else {
      plain.set(key, text);
    }
  }

  for (const locale of locales.filter((l) => l !== SOURCE_LOCALE)) {
    const label = `${locale}/${file}`;
    const target = load(locale, file);
    const categories = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
    const expected = new Map(plain);
    for (const [base, text] of plurals) {
      for (const category of categories) expected.set(`${base}_${category}`, text);
    }

    for (const [key, sourceText] of expected) {
      const text = target.get(key);
      if (text === undefined) {
        errors.push(`${label}: missing "${key}"`);
      } else if (!text.trim()) {
        errors.push(`${label}: "${key}" is empty`);
      } else if (placeholders(text) !== placeholders(sourceText)) {
        errors.push(
          `${label}: "${key}" placeholders differ (en: ${placeholders(sourceText) || "none"}; ${locale}: ${placeholders(text) || "none"})`,
        );
      }
    }
    for (const key of target.keys()) {
      if (!expected.has(key)) errors.push(`${label}: unexpected key "${key}" (not in ${SOURCE_LOCALE})`);
    }
  }
}

for (const locale of locales.filter((l) => l !== SOURCE_LOCALE)) {
  for (const file of readdirSync(path.join(localesDir, locale)).filter((f) => f.endsWith(".json"))) {
    if (!sourceFiles.includes(file)) errors.push(`${locale}/${file}: no matching ${SOURCE_LOCALE}/${file}`);
  }
}

if (errors.length) {
  console.error(`i18n check failed with ${errors.length} problem(s):`);
  for (const error of errors) console.error(`  - ${error}`);
  process.exit(1);
}
console.log(`i18n check passed: ${locales.join(", ")} × ${sourceFiles.length} namespaces.`);
