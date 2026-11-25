import { useCallback, useEffect, useMemo, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  HiOutlineChevronLeft,
  HiOutlineChevronRight,
  HiOutlineCircleStack,
  HiOutlineInformationCircle,
} from "react-icons/hi2";
import type { MetaFunction } from "react-router";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";
import {
  FIXTURE_URL,
  REAL_URL,
  STEPS,
  applyStepAction,
  buildStory,
  comparisonFor,
  costRatio,
  parseQualityFile,
  parseStep,
  parseTrack,
  pointsDelta,
  revealed,
  rungById,
  savingsPct,
  stepKeyAction,
  withinNoise,
  type ArmView,
  type KeyTarget,
  type RetrievalSummary,
  type RungView,
  type StepId,
  type StoryView,
  type TrackId,
} from "../../lib/analystQuality";
import { AppHeader } from "../components/AppHeader";
import { RequireAuth } from "../components/RequireAuth";
import { useFormat, type Formatters } from "../i18n/format";
import { pageMeta } from "../i18n/meta";

export const meta: MetaFunction = ({ location }) => pageMeta(location, "qualityStory");

const RETRIEVAL_METRICS = [
  { id: "responses_with_tool_call_rate", kind: "ratio" },
  { id: "tool_calls_mean", kind: "count" },
  { id: "tool_call_latency_ms_p50", kind: "ms" },
  { id: "tool_failures_reported", kind: "count" },
  { id: "audit_complete_rate", kind: "ratio" },
  { id: "citations_grounded_rate", kind: "ratio" },
  { id: "query_variants_mean", kind: "count" },
] as const satisfies ReadonlyArray<{ id: keyof RetrievalSummary; kind: "ratio" | "count" | "ms" }>;

type QualityFile = ReturnType<typeof parseQualityFile>;

/** Real pipeline output first; the labelled fixture only when no real file is deployed. */
async function loadFile(signal: AbortSignal): Promise<QualityFile> {
  const real = await fetch(REAL_URL, { signal });
  const response = real.ok ? real : await fetch(FIXTURE_URL, { signal });
  if (!response.ok) throw new Error(`${response.url} returned ${response.status}`);
  return parseQualityFile(await response.json());
}

function keyTarget(event: KeyboardEvent | ReactKeyboardEvent): KeyTarget {
  const el = event.target as HTMLElement | null;
  if (!el) return "page";
  if (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) return "editable";
  return el.closest("button, a") ? "control" : "page";
}

export default function QualityStory() {
  const { t } = useTranslation("qualityStory");
  const [params, setParams] = useSearchParams();
  const [file, setFile] = useState<QualityFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const step = parseStep(params.get("step"));
  const requestedTrack = parseTrack(params.get("track"));
  const requestedSplit = params.get("split");
  const story = useMemo(
    () => (file ? buildStory(file, requestedTrack, requestedSplit) : null),
    [file, requestedTrack, requestedSplit],
  );

  const goTo = useCallback(
    (next: number) => {
      const updated = new URLSearchParams(params);
      updated.set("step", STEPS[next]);
      setParams(updated, { replace: true, preventScrollReset: true });
    },
    [params, setParams],
  );

  const setTrack = (track: TrackId) => {
    const updated = new URLSearchParams(params);
    updated.set("track", track);
    setParams(updated, { replace: true, preventScrollReset: true });
  };

  const setSplit = (split: string, headline: boolean) => {
    const updated = new URLSearchParams(params);
    if (headline) updated.delete("split");
    else updated.set("split", split);
    setParams(updated, { replace: true, preventScrollReset: true });
  };

  useEffect(() => {
    const controller = new AbortController();
    loadFile(controller.signal).then(setFile, (reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const action = stepKeyAction(event.key, keyTarget(event));
      if (!action) return;
      event.preventDefault();
      goTo(applyStepAction(action, step));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goTo, step]);

  return (
    <RequireAuth>
      <div className="min-h-screen bg-slate-50 text-slate-950">
        <AppHeader />
        <main id="main-content" className="mx-auto max-w-[1200px] px-3 py-6 2xl:px-4">
          <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{t("title")}</h1>
              <p className="mt-1 max-w-[80ch] text-sm leading-6 text-slate-600">{t("subtitle")}</p>
            </div>
            <div className="flex flex-col items-end gap-2">
            {story && story.splits.length > 1 ? (
              <div role="group" aria-label={t("split.label")} className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-sm">
                {story.splits.map((split) => (
                  <button
                    key={split.id}
                    type="button"
                    aria-pressed={split.id === story.split}
                    onClick={() => setSplit(split.id, split.role === "headline")}
                    className={`rounded-md px-3 py-1 ${split.id === story.split ? "bg-white font-semibold text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-950"}`}
                  >
                    {t(`split.${split.role}`, { split: split.id })}
                  </button>
                ))}
              </div>
            ) : null}
            {story && story.tracks.length > 1 ? (
              <div role="group" aria-label={t("track.label")} className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-sm">
                {story.tracks.map((track) => (
                  <button
                    key={track.id}
                    type="button"
                    aria-pressed={track.id === story.track}
                    onClick={() => setTrack(track.id)}
                    className={`rounded-md px-3 py-1 ${track.id === story.track ? "bg-white font-semibold text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-950"}`}
                  >
                    {track.model}
                  </button>
                ))}
              </div>
            ) : null}
            </div>
          </header>
          {story?.regressionView ? (
            <p
              role="status"
              className="mb-5 flex items-start gap-2 rounded-lg border border-slate-300 bg-slate-100 px-4 py-3 text-sm text-slate-800"
            >
              <HiOutlineInformationCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              {t("split.regressionBanner", { split: story.split, headline: story.headlineSplit })}
            </p>
          ) : null}
          {story?.fixture ? (
            <p
              role="status"
              className="mb-5 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
            >
              <HiOutlineInformationCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              {t("fixtureBanner")}
            </p>
          ) : null}
          {error ? (
            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="font-semibold">{t("error.title")}</h2>
              <p className="mt-1 text-sm text-slate-600">{t("error.hint")}</p>
              <p className="mt-2 font-mono text-xs text-slate-500">{error}</p>
            </section>
          ) : null}
          {!story && !error ? (
            <p className="text-sm text-slate-500" role="status">
              {t("loading")}
            </p>
          ) : null}
          {story ? (
            <>
              <Orient />
              <Ladder story={story} step={step} />
              {revealed(step, "payoff") ? <Payoff story={story} /> : null}
              {revealed(step, "evidence") ? <Evidence story={story} /> : null}
              <StepNav step={step} onStep={goTo} />
            </>
          ) : null}
        </main>
      </div>
    </RequireAuth>
  );
}

function Orient() {
  const { t } = useTranslation("qualityStory");
  return (
    <section className="grid gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[1fr_320px] md:items-center">
      <p className="max-w-[70ch] text-base leading-7 text-slate-700">{t("orient.problem")}</p>
      <div className="flex gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4">
        <img src="/iq/foundry-iq.png" alt="" className="h-10 w-10 shrink-0 rounded-md bg-white object-contain p-1" />
        <div>
          <p className="text-sm font-semibold text-blue-950">{t("orient.toolTitle")}</p>
          <p className="text-xs text-blue-800">{t("orient.toolDetail")}</p>
          <p className="mt-2 text-xs leading-5 text-blue-900">{t("orient.toolNote")}</p>
        </div>
      </div>
    </section>
  );
}

const pct = (fmt: Formatters, value: number | null) => (value === null ? "—" : fmt.percent(value, 0));
const usd = (fmt: Formatters, value: number | null) =>
  value === null ? "—" : fmt.currency(value, "USD", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const seconds = (fmt: Formatters, ms: number | null) =>
  ms === null ? "—" : `${fmt.number(ms / 1000, { maximumFractionDigits: 1 })} s`;

function Ladder({ story, step }: { story: StoryView; step: number }) {
  return (
    <section className="mt-5 space-y-3">
      {story.rungs.map((rung) => (
        <Rung key={rung.id} story={story} rung={rung} shown={revealed(step, rung.id as StepId)} />
      ))}
    </section>
  );
}

function Rung({ story, rung, shown }: { story: StoryView; rung: RungView; shown: boolean }) {
  const { t } = useTranslation("qualityStory");
  const fmt = useFormat();
  const baseline = rungById(story, "baseline");
  const before = rung.id === "rft" ? story.beforeRft : null;
  const gain =
    rung.id === "optimized"
      ? pointsDelta(baseline, rung)
      : before
        ? pointsDelta(before, rung)
        : null;
  const gainLabel =
    gain === null || gain <= 0
      ? null
      : rung.id === "optimized"
        ? t("rung.vsStarter", { points: Math.round(gain) })
        : t("rung.vsUntuned", { points: Math.round(gain), model: before?.model ?? "" });

  return (
    <article
      className={`grid gap-4 rounded-xl border bg-white p-5 shadow-sm transition-opacity duration-500 md:grid-cols-[220px_1fr_340px] md:items-center ${
        shown ? "border-slate-200" : "border-dashed border-slate-300"
      }`}
      aria-hidden={!shown}
    >
      <div>
        <h2 className="text-lg font-semibold text-slate-950">{t(`stage.${rung.stage}.title`)}</h2>
        <p className="text-xs text-slate-500">{t(`stage.${rung.stage}.detail`, { model: rung.model })}</p>
      </div>
      {shown ? (
        <>
          <div>
            <Bar value={rung.passRate} marker={before?.passRate ?? null} />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
              {before && before.passRate !== null ? (
                <span>{t("rung.beforeRft", { model: before.model, value: pct(fmt, before.passRate) })}</span>
              ) : null}
              {gainLabel ? <span className="font-medium text-emerald-700">{gainLabel}</span> : null}
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-3 text-right">
            <Stat value={pct(fmt, rung.passRate)} label={t("rung.passRate")} strong />
            <Stat value={usd(fmt, rung.costPer1k)} label={t("rung.costPer1k")} />
            <Stat value={seconds(fmt, rung.latencyP50)} label={t("rung.latency")} />
          </dl>
        </>
      ) : (
        <p className="text-sm text-slate-400 md:col-span-2">{t("rung.placeholder")}</p>
      )}
    </article>
  );
}

function Bar({ value, marker }: { value: number | null; marker: number | null }) {
  const width = `${Math.round((value ?? 0) * 100)}%`;
  return (
    <div className="relative h-4 w-full overflow-hidden rounded-full bg-slate-100">
      <div className="h-full rounded-full bg-blue-600 transition-[width] duration-700" style={{ width }} />
      {marker !== null ? (
        <div
          className="absolute top-0 h-full w-0.5 bg-slate-500"
          style={{ left: `${Math.round(marker * 100)}%` }}
          aria-hidden="true"
        />
      ) : null}
    </div>
  );
}

function Stat({ value, label, strong = false }: { value: string; label: string; strong?: boolean }) {
  return (
    <div>
      <dd className={`font-mono tabular-nums ${strong ? "text-2xl font-semibold" : "text-lg"} text-slate-950`}>
        {value}
      </dd>
      <dt className="text-xs text-slate-500">{label}</dt>
    </div>
  );
}

function Payoff({ story }: { story: StoryView }) {
  const { t } = useTranslation("qualityStory");
  const fmt = useFormat();
  const baseline = rungById(story, "baseline");
  const optimized = rungById(story, "optimized");
  const tuned = rungById(story, "rft");
  const ratio = costRatio(optimized, tuned);
  const saved = savingsPct(baseline, tuned);
  const noise = withinNoise(comparisonFor(story, "optimized", "mai2-rft"));
  const delta = pointsDelta(optimized, tuned);
  const maxCost = Math.max(...story.rungs.map((r) => r.costPer1k ?? 0), 0.0001);
  const maxLatency = Math.max(...story.rungs.map((r) => r.latencyP50 ?? 0), 1);

  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t("payoff.title")}</h2>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-base font-medium text-emerald-800">
        {ratio !== null && ratio > 1 ? (
          <p>{t("payoff.cheaper", { ratio: fmt.number(ratio, { maximumFractionDigits: 0 }) })}</p>
        ) : null}
        {saved !== null && saved > 0 ? <p>{t("payoff.savings", { value: fmt.percent(saved, 0) })}</p> : null}
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {noise === true
          ? t("payoff.matches")
          : delta !== null
            ? t("payoff.delta", { points: fmt.number(delta, { maximumFractionDigits: 1, signDisplay: "always" }) })
            : null}
      </p>
      <div className="mt-5 grid gap-6 md:grid-cols-2">
        <BarGroup
          title={t("payoff.cost")}
          rows={story.rungs.map((r) => ({ rung: r, value: r.costPer1k, label: usd(fmt, r.costPer1k), max: maxCost }))}
        />
        <BarGroup
          title={t("payoff.latency")}
          rows={story.rungs.map((r) => ({
            rung: r,
            value: r.latencyP50,
            label: seconds(fmt, r.latencyP50),
            max: maxLatency,
          }))}
        />
      </div>
    </section>
  );
}

function BarGroup({
  title,
  rows,
}: {
  title: string;
  rows: { rung: RungView; value: number | null; label: string; max: number }[];
}) {
  const { t } = useTranslation("qualityStory");
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
      <ul className="mt-3 space-y-3">
        {rows.map(({ rung, value, label, max }) => (
          <li key={rung.id} className="grid grid-cols-[96px_1fr_80px] items-center gap-3 text-sm">
            <span className="text-slate-600">{t(`stage.${rung.stage}.title`)}</span>
            <span className="h-3 overflow-hidden rounded-full bg-slate-100">
              <span
                className="block h-full rounded-full bg-blue-500"
                style={{ width: `${Math.max(2, Math.round(((value ?? 0) / max) * 100))}%` }}
              />
            </span>
            <span className="text-right font-mono tabular-nums text-slate-900">{label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Evidence({ story }: { story: StoryView }) {
  const { t } = useTranslation("qualityStory");
  const fmt = useFormat();
  const arms: ArmView[] = story.arms;
  const generated = story.generatedAt ? fmt.dateTime(story.generatedAt, { dateStyle: "medium" }) : null;
  const header = (
    <tr>
      <th className="px-4 py-2 font-semibold" />
      {arms.map((arm) => (
        <th key={arm.arm} className="px-4 py-2 text-right font-semibold">
          <span className="block">{arm.model}</span>
          <span className="block text-xs font-normal text-slate-500">{arm.arm}</span>
        </th>
      ))}
    </tr>
  );

  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">{t("evidence.title")}</h2>
        <p className="flex items-center gap-1 text-xs text-slate-500">
          <HiOutlineCircleStack className="h-4 w-4" aria-hidden="true" />
          {t("evidence.lineage", {
            split: story.split,
            cases: story.benchmarkRows ?? story.rungs[0].cases ?? "—",
            grader: story.graderVersion ?? "—",
            threshold: story.passThreshold ?? "—",
          })}
          {story.sourceFamilies !== null ? ` · ${t("evidence.families", { n: story.sourceFamilies })}` : null}
          {generated ? ` · ${t("evidence.generated", { date: generated })}` : null}
        </p>
      </div>
      <div className="mt-4 grid gap-6">
        <div className="overflow-x-auto">
          <h3 className="text-sm font-semibold text-slate-700">{t("evidence.rubric")}</h3>
          <table className="mt-2 min-w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs text-slate-600">{header}</thead>
            <tbody className="divide-y divide-slate-100">
              {story.dimensions.map((dim) => (
                <tr key={dim.id}>
                  <td className="px-4 py-2 text-slate-700">{dim.label}</td>
                  {arms.map((arm) => {
                    const score = arm.dimensions[dim.id]?.mean_score;
                    return (
                      <td key={arm.arm} className="px-4 py-2 text-right font-mono tabular-nums">
                        {typeof score !== "number" ? t("evidence.notMeasured") : fmt.number(score, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="overflow-x-auto">
          <h3 className="text-sm font-semibold text-slate-700">{t("evidence.retrieval")}</h3>
          <table className="mt-2 min-w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs text-slate-600">{header}</thead>
            <tbody className="divide-y divide-slate-100">
              {RETRIEVAL_METRICS.map((metric) => (
                <tr key={metric.id}>
                  <td className="px-4 py-2 text-slate-700">{t(`evidence.metrics.${metric.id}`)}</td>
                  {arms.map((arm) => {
                    const value = arm.retrieval?.[metric.id];
                    return (
                      <td key={arm.arm} className="px-4 py-2 text-right font-mono tabular-nums">
                        {typeof value !== "number"
                          ? t("evidence.notMeasured")
                          : metric.kind === "ratio"
                            ? fmt.percent(value, 0)
                            : metric.kind === "ms"
                              ? t("evidence.ms", { value: fmt.number(value, { maximumFractionDigits: 0 }) })
                              : fmt.number(value, { maximumFractionDigits: 1 })}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {story.caveats.length > 0 ? (
        <div className="mt-5 rounded-lg bg-slate-50 p-4">
          <h3 className="text-sm font-semibold text-slate-700">{t("evidence.caveats")}</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-slate-600">
            {story.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function StepNav({ step, onStep }: { step: number; onStep: (step: number) => void }) {
  const { t } = useTranslation("qualityStory");
  return (
    <nav aria-label={t("nav.label")} className="mt-6 flex items-center justify-center gap-3">
      <button
        type="button"
        onClick={() => onStep(applyStepAction("prev", step))}
        disabled={step === 0}
        className="rounded-md p-2 text-slate-600 hover:bg-slate-200 disabled:opacity-30"
        aria-label={t("nav.previous")}
      >
        <HiOutlineChevronLeft className="h-5 w-5" aria-hidden="true" />
      </button>
      <ol className="flex items-center gap-2">
        {STEPS.map((id, index) => (
          <li key={id}>
            <button
              type="button"
              onClick={() => onStep(index)}
              aria-current={index === step ? "step" : undefined}
              aria-label={t("nav.step", { n: index + 1, name: t(`steps.${id}`) })}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                index === step ? "bg-blue-600 text-white" : index < step ? "bg-blue-100 text-blue-800" : "bg-slate-200 text-slate-600"
              }`}
            >
              {t(`steps.${id}`)}
            </button>
          </li>
        ))}
      </ol>
      <button
        type="button"
        onClick={() => onStep(applyStepAction("next", step))}
        disabled={step === STEPS.length - 1}
        className="rounded-md p-2 text-slate-600 hover:bg-slate-200 disabled:opacity-30"
        aria-label={t("nav.next")}
      >
        <HiOutlineChevronRight className="h-5 w-5" aria-hidden="true" />
      </button>
    </nav>
  );
}
