// Reads the contract-policy-analyst quality.json written by the eval pipeline and turns it into the story page's
// view model. The page never computes evidence itself: every figure is either copied from the file or derived here
// with a named formula, and a missing field stays `null` ("not measured"), never zero.
// Data contract: apps/waypoint/docs/contract-policy-analyst-story.md#data-contract

export const REAL_URL = "/quality/contract-policy-analyst.quality.json";
export const FIXTURE_URL = "/quality/fixtures/contract-policy-analyst.fixture.json";

export interface RubricDimension {
  label?: string;
  mean_score: number | null;
}

export interface RetrievalSummary {
  responses_with_tool_call_rate?: number | null;
  tool_calls_mean?: number | null;
  tool_call_latency_ms_p50?: number | null;
  tool_failures_reported?: number | null;
  audit_complete_rate?: number | null;
  citations_grounded_rate?: number | null;
  /** Only present when real MCP dispatch variants are captured; model function args carry the query alone. */
  query_variants_mean?: number | null;
}

export interface SplitSummary {
  unique_cases?: number;
  runs?: number;
  responses?: number;
  mean_score?: number;
  pass_rate?: number;
  latency_ms?: { p50?: number; p95?: number; mean?: number };
  tokens_mean?: { input_tokens?: number; output_tokens?: number; reasoning_tokens?: number };
  cost_usd_per_1k_lines?: number;
  /** Critical-failure counts by category; `{}` means measured with none, absent means not measured. */
  critical_failures?: Record<string, number>;
  rubric_dimensions?: Record<string, RubricDimension>;
  retrieval?: RetrievalSummary;
}

export interface ArmRecord {
  agent_version?: string;
  model: string;
  description?: string;
  optimizer_job?: string;
  instructions_word_count?: number;
  results: Record<string, SplitSummary>;
}

export interface Comparison {
  a: string;
  b: string;
  split: string;
  mean_difference?: number;
  ci95?: [number, number];
  paired_sign_flip_p?: number;
}

export interface AnalystQualityFile {
  agent: string;
  generated_at?: string;
  fixture?: boolean;
  evaluation_scope?: { capability?: string; tools?: string; statement?: string };
  grader?: { path?: string; version?: string; pass_threshold?: number };
  benchmark?: {
    path?: string;
    splits?: Record<string, { rows?: number; source_families?: number }>;
    selection_policy?: string;
  };
  headline_split?: string;
  /** Splits that are regression evidence only (e.g. exposed-source `study-heldout`); never the headline. */
  regression_splits?: string[];
  rft_job?: { id?: string; base_model?: string; train_rows?: number; status?: string } | null;
  arms: Record<string, ArmRecord>;
  comparisons?: Comparison[];
  caveats?: string[];
}

/**
 * The pipeline runs the Build and Optimize rungs on two frontier models ("tracks"); the Train rung is always the
 * RFT-tuned MAI-2. `?track=` picks which frontier pair the ladder reads; the evidence tables show every arm.
 */
export const TRACKS = ["astra62", "astra"] as const;
export type TrackId = (typeof TRACKS)[number];
export const DEFAULT_TRACK: TrackId = "astra62";
export const RFT_ARM = "mai2-rft";
/** The untuned MAI-2 arm, shown beside the Train rung so the RFT gain is visible. */
export const BEFORE_RFT_ARM = "mai2-base";
/** Column order for the evidence tables; arms the file doesn't report are skipped. */
export const ARM_ORDER = [
  "baseline-astra",
  "baseline-astra62",
  "optimized-astra",
  "optimized-astra62",
  BEFORE_RFT_ARM,
  RFT_ARM,
] as const;

const RUNG_DEFS = [
  { id: "baseline", stage: "build" },
  { id: "optimized", stage: "optimize" },
  { id: "rft", stage: "train" },
] as const;
export type RungId = (typeof RUNG_DEFS)[number]["id"];
export type RungStage = (typeof RUNG_DEFS)[number]["stage"];

export function rungArms(track: TrackId): Record<RungId, string> {
  return { baseline: `baseline-${track}`, optimized: `optimized-${track}`, rft: RFT_ARM };
}

export function parseTrack(value: string | null | undefined): TrackId | null {
  return (TRACKS as readonly string[]).includes(value ?? "") ? (value as TrackId) : null;
}

export interface ArmView {
  arm: string;
  model: string;
  description: string | null;
  passRate: number | null;
  meanScore: number | null;
  cases: number | null;
  runs: number | null;
  costPer1k: number | null;
  latencyP50: number | null;
  latencyP95: number | null;
  dimensions: Record<string, RubricDimension>;
  retrieval: RetrievalSummary | null;
  /** Total critical failures across categories; null when the split didn't measure them. */
  criticalFailures: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  reasoningTokens: number | null;
}

export interface RungView extends ArmView {
  id: RungId;
  stage: RungStage;
}

export interface StoryView {
  agent: string;
  fixture: boolean;
  /** The split every figure on the page reads: the headline, or a regression split when one was requested. */
  split: string;
  headlineSplit: string;
  /** True when `split` is a regression split rather than the headline. */
  regressionView: boolean;
  /** The headline first, then each regression split that every rung reports. */
  splits: { id: string; role: "headline" | "regression" }[];
  sourceFamilies: number | null;
  generatedAt: string | null;
  track: TrackId;
  tracks: { id: TrackId; model: string }[];
  rungs: RungView[];
  beforeRft: ArmView | null;
  arms: ArmView[];
  dimensions: { id: string; label: string }[];
  comparisons: Comparison[];
  graderVersion: string | null;
  passThreshold: number | null;
  benchmarkRows: number | null;
  rftTrainRows: number | null;
  rftBaseModel: string | null;
  caveats: string[];
  scope: string | null;
}

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/** Throws with a readable message when the file can't drive the page; anything optional may be absent. */
export function parseQualityFile(raw: unknown): AnalystQualityFile {
  if (!raw || typeof raw !== "object") throw new Error("quality file is not a JSON object");
  const file = raw as Partial<AnalystQualityFile>;
  if (typeof file.agent !== "string") throw new Error("quality file has no agent");
  if (!file.arms || typeof file.arms !== "object") throw new Error("quality file has no arms");
  const arms = file.arms as Record<string, unknown>;
  if (!isArm(arms[RFT_ARM])) throw new Error(`quality file is missing arm "${RFT_ARM}"`);
  if (availableTracks(file as AnalystQualityFile).length === 0) {
    throw new Error(`quality file has no complete track (${TRACKS.map((t) => `baseline-${t} + optimized-${t}`).join(" or ")})`);
  }
  return file as AnalystQualityFile;
}

function isArm(value: unknown): value is ArmRecord {
  const arm = value as Partial<ArmRecord> | undefined;
  return !!arm && typeof arm.model === "string" && !!arm.results && typeof arm.results === "object";
}

/** Tracks whose baseline and optimized arms are both in the file. */
export function availableTracks(file: AnalystQualityFile): TrackId[] {
  return TRACKS.filter((t) => isArm(file.arms[`baseline-${t}`]) && isArm(file.arms[`optimized-${t}`]));
}

function reportedByRungs(file: AnalystQualityFile, track: TrackId, split: string): boolean {
  return Object.values(rungArms(track)).every((arm) => split in file.arms[arm].results);
}

/** `headline_split` when set, else the first split all three rungs report that isn't a regression split. */
export function headlineSplit(file: AnalystQualityFile, track: TrackId = availableTracks(file)[0]): string {
  if (file.headline_split) return file.headline_split;
  const regression = new Set(file.regression_splits ?? []);
  const first = Object.keys(file.arms[rungArms(track).baseline].results).find(
    (split) => !regression.has(split) && reportedByRungs(file, track, split),
  );
  if (!first) throw new Error("no headline split is reported by every rung");
  return first;
}

/** Regression splits every rung reports, in file order; the headline split is never one of them. */
export function regressionSplits(file: AnalystQualityFile, track: TrackId, headline: string): string[] {
  return (file.regression_splits ?? []).filter((s) => s !== headline && reportedByRungs(file, track, s));
}

function armView(arm: string, record: ArmRecord, split: string): ArmView {
  const s = record.results[split] ?? {};
  return {
    arm,
    model: record.model,
    description: record.description ?? null,
    passRate: num(s.pass_rate),
    meanScore: num(s.mean_score),
    cases: num(s.unique_cases),
    runs: num(s.runs),
    costPer1k: num(s.cost_usd_per_1k_lines),
    latencyP50: num(s.latency_ms?.p50),
    latencyP95: num(s.latency_ms?.p95),
    dimensions: s.rubric_dimensions ?? {},
    retrieval: s.retrieval ?? null,
    criticalFailures: criticalFailureTotal(s.critical_failures),
    inputTokens: num(s.tokens_mean?.input_tokens),
    outputTokens: num(s.tokens_mean?.output_tokens),
    reasoningTokens: num(s.tokens_mean?.reasoning_tokens),
  };
}

/** Sum of per-category counts; `{}` is a measured zero, a missing or malformed map is not measured. */
export function criticalFailureTotal(failures: unknown): number | null {
  if (!failures || typeof failures !== "object" || Array.isArray(failures)) return null;
  const counts = Object.values(failures as Record<string, unknown>);
  if (!counts.every((c) => num(c) !== null)) return null;
  return counts.reduce<number>((sum, c) => sum + (c as number), 0);
}

/**
 * Builds the view for `requested` when that track is complete, else the default (or first complete) track.
 * `requestedSplit` only takes effect for a declared regression split; anything else reads the headline.
 */
export function buildStory(
  file: AnalystQualityFile,
  requested?: TrackId | null,
  requestedSplit?: string | null,
): StoryView {
  const available = availableTracks(file);
  const track =
    requested && available.includes(requested)
      ? requested
      : available.includes(DEFAULT_TRACK)
        ? DEFAULT_TRACK
        : available[0];
  const headline = headlineSplit(file, track);
  const regression = regressionSplits(file, track, headline);
  const split = requestedSplit && regression.includes(requestedSplit) ? requestedSplit : headline;
  const armIds = rungArms(track);
  const rungs = RUNG_DEFS.map((r) => ({
    ...armView(armIds[r.id], file.arms[armIds[r.id]], split),
    id: r.id,
    stage: r.stage,
  }));
  const before = file.arms[BEFORE_RFT_ARM];
  const beforeRft = isArm(before) ? armView(BEFORE_RFT_ARM, before, split) : null;
  const arms = ARM_ORDER.filter((id) => isArm(file.arms[id])).map((id) => armView(id, file.arms[id], split));

  const dimensions = new Map<string, string>();
  for (const view of arms) {
    for (const [id, dim] of Object.entries(view.dimensions)) {
      if (!dimensions.has(id)) dimensions.set(id, dim.label ?? id);
    }
  }

  return {
    agent: file.agent,
    fixture: file.fixture === true,
    split,
    headlineSplit: headline,
    regressionView: split !== headline,
    splits: [
      { id: headline, role: "headline" as const },
      ...regression.map((id) => ({ id, role: "regression" as const })),
    ],
    sourceFamilies: num(file.benchmark?.splits?.[split]?.source_families),
    generatedAt: file.generated_at ?? null,
    track,
    tracks: available.map((id) => ({ id, model: file.arms[`baseline-${id}`].model })),
    rungs,
    beforeRft,
    arms,
    dimensions: [...dimensions].map(([id, label]) => ({ id, label })),
    comparisons: (file.comparisons ?? []).filter((c) => c.split === split),
    graderVersion: file.grader?.version ?? null,
    passThreshold: num(file.grader?.pass_threshold),
    benchmarkRows: num(file.benchmark?.splits?.[split]?.rows),
    rftTrainRows: num(file.rft_job?.train_rows),
    rftBaseModel: file.rft_job?.base_model ?? null,
    caveats: file.caveats ?? [],
    scope: file.evaluation_scope?.statement ?? null,
  };
}

export function rungById(story: StoryView, id: RungId): RungView {
  const found = story.rungs.find((r) => r.id === id);
  if (!found) throw new Error(`unknown rung ${id}`);
  return found;
}

/** How many times cheaper `to` is than `from` (e.g. 40 → "40× lower cost"); null if either is unmeasured. */
export function costRatio(from: ArmView, to: ArmView): number | null {
  if (from.costPer1k === null || to.costPer1k === null || to.costPer1k <= 0) return null;
  return from.costPer1k / to.costPer1k;
}

/** Percent saved per review moving from `from` to `to` (1 − to/from); null if either is unmeasured. */
export function savingsPct(from: ArmView, to: ArmView): number | null {
  if (from.costPer1k === null || to.costPer1k === null || from.costPer1k <= 0) return null;
  return 1 - to.costPer1k / from.costPer1k;
}

/** Pass-rate change in percentage points between two arms; null if either is unmeasured. */
export function pointsDelta(from: ArmView, to: ArmView): number | null {
  if (from.passRate === null || to.passRate === null) return null;
  return (to.passRate - from.passRate) * 100;
}

/** The paired comparison for two arms on the headline split, if the pipeline computed it. */
export function comparisonFor(story: StoryView, a: string, b: string): Comparison | null {
  return story.comparisons.find((c) => c.a === a && c.b === b) ?? null;
}

/** "Matches" rather than "beats" when the paired 95% interval includes zero. */
export function withinNoise(c: Comparison | null): boolean | null {
  if (!c?.ci95) return null;
  return c.ci95[0] <= 0 && c.ci95[1] >= 0;
}

/* ---------- presenter steps (borrowed from the Alaska agent-improvements page) ---------- */

export const STEPS = ["orient", "baseline", "optimized", "rft", "payoff", "evidence"] as const;
export type StepId = (typeof STEPS)[number];
export const LAST_STEP = STEPS.length - 1;

export function clampStep(step: number): number {
  return Math.min(Math.max(Math.trunc(step), 0), LAST_STEP);
}

/** `?step=` accepts an index or a step name; anything else is the first step. */
export function parseStep(value: string | null | undefined): number {
  if (value == null || value.trim() === "") return 0;
  const named = (STEPS as readonly string[]).indexOf(value.trim());
  if (named >= 0) return named;
  const n = Number(value);
  return Number.isFinite(n) ? clampStep(n) : 0;
}

export function stepIndex(id: StepId): number {
  return STEPS.indexOf(id);
}

export function revealed(step: number, id: StepId): boolean {
  return step >= stepIndex(id);
}

export type KeyTarget = "page" | "control" | "editable";
export type StepAction = "next" | "prev" | "first" | "last";

/** Presenter keys: clickers send PageDown/PageUp or arrows. Nothing fires in text fields; Space only on the page. */
export function stepKeyAction(key: string, target: KeyTarget): StepAction | null {
  if (target === "editable") return null;
  if (key === " ") return target === "page" ? "next" : null;
  if (key === "ArrowRight" || key === "PageDown") return "next";
  if (key === "ArrowLeft" || key === "PageUp") return "prev";
  if (key === "Home") return "first";
  if (key === "End") return "last";
  return null;
}

export function applyStepAction(action: StepAction, step: number): number {
  if (action === "next") return clampStep(step + 1);
  if (action === "prev") return clampStep(step - 1);
  return action === "first" ? 0 : LAST_STEP;
}
