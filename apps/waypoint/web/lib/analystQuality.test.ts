import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  applyStepAction,
  buildStory,
  costRatio,
  criticalFailureTotal,
  headlineSplit,
  parseQualityFile,
  parseStep,
  parseTrack,
  pointsDelta,
  rungById,
  savingsPct,
  stepKeyAction,
  withinNoise,
  type AnalystQualityFile,
} from "./analystQuality.ts";

const fixture = JSON.parse(
  readFileSync(new URL("../public/quality/fixtures/contract-policy-analyst.fixture.json", import.meta.url), "utf8"),
) as AnalystQualityFile;

const minimal = (results: Record<string, object>): AnalystQualityFile => ({
  agent: "contract-policy-analyst",
  arms: {
    "baseline-astra62": { model: "a", results },
    "optimized-astra62": { model: "a", results },
    "mai2-rft": { model: "m", results },
  },
});

test("the committed fixture is labelled and drives every rung", () => {
  const story = buildStory(parseQualityFile(fixture));
  assert.equal(story.fixture, true);
  assert.equal(story.split, "final-test-v2");
  assert.equal(story.regressionView, false);
  assert.deepEqual(story.splits, [
    { id: "final-test-v2", role: "headline" },
    { id: "study-heldout", role: "regression" },
  ]);
  assert.deepEqual(story.rungs.map((r) => r.arm), ["baseline-astra62", "optimized-astra62", "mai2-rft"]);
  assert.equal(story.beforeRft?.arm, "mai2-base");
  assert.equal(story.arms.length, 6);
  assert.equal(story.dimensions.length, 6);
});

test("the track parameter switches the frontier pair and falls back when incomplete", () => {
  assert.equal(buildStory(fixture, "astra").rungs[0].arm, "baseline-astra");
  assert.equal(buildStory(minimal({ x: {} }), "astra").track, "astra62");
  assert.equal(parseTrack("bogus"), null);
});

test("parseQualityFile rejects files missing the RFT arm or a complete track", () => {
  const noRft = minimal({ x: {} }) as unknown as { arms: Record<string, unknown> };
  delete noRft.arms["mai2-rft"];
  assert.throws(() => parseQualityFile(noRft), /mai2-rft/);
  const noTrack = minimal({ x: {} }) as unknown as { arms: Record<string, unknown> };
  delete noTrack.arms["optimized-astra62"];
  assert.throws(() => parseQualityFile(noTrack), /complete track/);
});

test("headline split prefers the declared split and never falls back to a regression split", () => {
  assert.equal(headlineSplit({ ...minimal({ x: {} }), headline_split: "optimizer-validation" }), "optimizer-validation");
  const exposed = { ...minimal({ "study-heldout": {}, fresh: {} }), regression_splits: ["study-heldout"] };
  assert.equal(headlineSplit(exposed), "fresh");
  assert.throws(() => headlineSplit({ ...minimal({ "study-heldout": {} }), regression_splits: ["study-heldout"] }));
});

test("the split parameter only opens a declared regression view; the headline stays the default", () => {
  const regression = buildStory(fixture, null, "study-heldout");
  assert.equal(regression.regressionView, true);
  assert.equal(regression.headlineSplit, "final-test-v2");
  assert.equal(regression.benchmarkRows, 120);
  assert.ok(regression.comparisons.every((c) => c.split === "study-heldout"));
  assert.equal(buildStory(fixture, null, "optimizer-validation").split, "final-test-v2");
});

test("missing measurements stay null instead of zero", () => {
  assert.equal(criticalFailureTotal({}), 0);
  assert.equal(criticalFailureTotal({ unsafe_disposition: 2, fabricated_citation: 1 }), 3);
  assert.equal(criticalFailureTotal(undefined), null);
  assert.equal(criticalFailureTotal({ x: null }), null);
  const story = buildStory(minimal({ "study-heldout": { pass_rate: 0.5 } }));
  const tuned = rungById(story, "rft");
  assert.equal(tuned.costPer1k, null);
  assert.equal(tuned.latencyP50, null);
  assert.equal(tuned.retrieval, null);
  assert.equal(costRatio(rungById(story, "optimized"), tuned), null);
  assert.equal(story.beforeRft, null);
});

test("cost and quality deltas use the named formulas", () => {
  const from = { costPer1k: 30, passRate: 0.8 } as Parameters<typeof costRatio>[0];
  const to = { costPer1k: 1, passRate: 0.85 } as Parameters<typeof costRatio>[0];
  assert.equal(costRatio(from, to), 30);
  assert.ok(Math.abs((savingsPct(from, to) ?? 0) - 29 / 30) < 1e-9);
  assert.ok(Math.abs((pointsDelta(from, to) ?? 0) - 5) < 1e-9);
});

test("a paired interval that spans zero reads as within noise", () => {
  assert.equal(withinNoise({ a: "x", b: "y", split: "s", ci95: [-0.02, 0.03] }), true);
  assert.equal(withinNoise({ a: "x", b: "y", split: "s", ci95: [0.01, 0.03] }), false);
  assert.equal(withinNoise(null), null);
});

test("presenter steps accept names and indexes and ignore text fields", () => {
  assert.equal(parseStep("payoff"), 4);
  assert.equal(parseStep("99"), 5);
  assert.equal(parseStep("nope"), 0);
  assert.equal(stepKeyAction("PageDown", "control"), "next");
  assert.equal(stepKeyAction(" ", "control"), null);
  assert.equal(stepKeyAction("ArrowRight", "editable"), null);
  assert.equal(applyStepAction("prev", 0), 0);
  assert.equal(applyStepAction("last", 1), 5);
});
