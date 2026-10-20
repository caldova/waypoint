/**
 * Part 1 of the quality story: Foundry Agent Optimizer changes the agent's
 * assets (prompt and tool descriptions) while the model stays fixed. Web
 * version of the Optimizer Diff canvas.
 */

import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { HiOutlineChevronDown } from "react-icons/hi2";
import {
  changedHunks,
  countTerm,
  diffStats,
  lineDiff,
  splitLines,
  type DiffRow,
} from "../../lib/lineDiff";
import review from "../data/optimizerReview.json";
import { useFormat } from "../i18n/format";

interface ToolSpec {
  type?: string;
  function?: {
    name?: string;
    description?: string;
    parameters?: { properties?: Record<string, unknown>; required?: string[] };
  };
}

interface Candidate {
  name: string;
  avg_score: number;
  candidate_id: string;
}

const KEYWORD_GROUPS = [
  { id: "shape", terms: ["expert_evidence", "invoice_id", "schema", "json"] },
  { id: "citations", terms: ["source_ref", "classification", "confidence", "claim", "supports"] },
  { id: "gaps", terms: ["unsupported", "gap", "missing", "conflict"] },
  { id: "retrieval", terms: ["knowledge_base", "retrieve", "contract", "policy", "rate-card"] },
  {
    id: "boundary",
    terms: ["read-only", "do not approve", "do not reconcile", "writeback", "recovery"],
  },
] as const;

const { job, baseline, candidate } = review;
const leaderboard = [...(review.leaderboard as Candidate[])].sort(
  (a, b) => b.avg_score - a.avg_score,
);
const scoreLift = candidate.avgScore - baseline.avgScore;

function score3(value: number) {
  return value.toFixed(3);
}

export function OptimizerPanel() {
  const { t } = useTranslation("quality");
  const titleId = useId();
  const evaluator = job.evaluators[0];
  return (
    <section
      aria-labelledby={titleId}
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <header className="border-b border-slate-100 p-5 lg:p-6">
        <h2 id={titleId} className="text-xl font-semibold tracking-tight text-slate-950">
          {t("optimizerReview.title", { model: job.evalModel })}
        </h2>
        <p className="mt-2 max-w-[80ch] text-sm leading-6 text-slate-600">
          {t("optimizerReview.intro", {
            agent: job.agentName,
            version: job.agentVersion,
            optimizationModel: job.optimizationModel,
            evalModel: job.evalModel,
            candidate: candidate.name,
          })}
        </p>
        <p className="mt-2 break-words font-mono text-xs text-slate-500">
          {t("optimizerReview.setup", {
            job: job.id,
            rubric: evaluator.name,
            rubricVersion: evaluator.version,
          })}
        </p>
      </header>
      <div className="space-y-6 p-5 lg:p-6">
        <ResultStrip />
        <div className="grid gap-4 xl:grid-cols-2">
          <WhatChanged />
          <ChangedAssets />
        </div>
        <Leaderboard />
        <PromptChanges />
        <ToolChanges />
      </div>
    </section>
  );
}

function ResultStrip() {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const tiles = [
    {
      dot: "bg-blue-700",
      label: t("optimizerReview.strip.score"),
      value: `${score3(baseline.avgScore)} → ${score3(candidate.avgScore)}`,
      detail: t("optimizerReview.strip.scoreDetail", { candidate: candidate.name }),
    },
    {
      dot: "bg-emerald-600",
      label: t("optimizerReview.strip.lift"),
      value: `+${score3(scoreLift)} (+${fmt.percent(scoreLift / baseline.avgScore, 1)})`,
      detail: t("optimizerReview.strip.liftDetail"),
    },
    {
      dot: "bg-slate-500",
      label: t("optimizerReview.strip.model"),
      value: candidate.model,
      detail: t("optimizerReview.strip.modelDetail"),
    },
    {
      dot: "bg-violet-600",
      label: t("optimizerReview.strip.status"),
      value: job.status === "succeeded" ? t("optimizerReview.strip.succeeded") : job.status,
      detail: t("optimizerReview.strip.statusDetail", { candidates: leaderboard.length }),
    },
  ];
  return (
    <div>
      <div
        role="group"
        aria-label={t("optimizerReview.strip.ariaLabel")}
        className="grid grid-cols-2 gap-3 lg:grid-cols-4"
      >
        {tiles.map((tile) => (
          <div key={tile.label} className="min-w-0 rounded-lg border border-slate-200 p-3">
            <p className="flex items-center gap-2 type-label">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${tile.dot}`} aria-hidden="true" />
              {tile.label}
            </p>
            <p className="mt-1 break-words font-mono text-base font-semibold tabular-nums text-slate-950 lg:text-lg">
              {tile.value}
            </p>
            <p className="text-xs text-slate-600">{tile.detail}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 max-w-[100ch] text-xs leading-5 text-slate-600">
        {t("optimizerReview.strip.help")}
      </p>
    </div>
  );
}

function ReviewList({
  title,
  detail,
  rows,
}: {
  title: string;
  detail?: string;
  rows: Array<{ label: string; text: string }>;
}) {
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
        {detail ? <p className="text-xs text-slate-600">{detail}</p> : null}
      </div>
      <dl className="mt-3 divide-y divide-slate-100">
        {rows.map((row) => (
          <div key={row.label} className="grid gap-1 py-2 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
            <dt className="text-sm font-semibold text-slate-900">{row.label}</dt>
            <dd className="text-sm leading-6 text-slate-700">{row.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function WhatChanged() {
  const { t } = useTranslation("quality");
  return (
    <ReviewList
      title={t("optimizerReview.summary.title")}
      rows={[
        {
          label: t("optimizerReview.summary.output.label"),
          text: t("optimizerReview.summary.output.text"),
        },
        {
          label: t("optimizerReview.summary.evidence.label"),
          text: t("optimizerReview.summary.evidence.text", { field: "retrieved_context" }),
        },
        {
          label: t("optimizerReview.summary.gaps.label"),
          text: t("optimizerReview.summary.gaps.text"),
        },
        {
          label: t("optimizerReview.summary.boundary.label"),
          text: t("optimizerReview.summary.boundary.text", {
            decision: "decision",
            action: "recommended_finance_action",
          }),
        },
      ]}
    />
  );
}

function ChangedAssets() {
  const { t } = useTranslation("quality");
  return (
    <ReviewList
      title={t("optimizerReview.assets.title")}
      detail={t("optimizerReview.assets.detail", { candidate: candidate.name })}
      rows={[
        {
          label: t("optimizerReview.assets.prompt.label"),
          text: t("optimizerReview.assets.prompt.text"),
        },
        {
          label: t("optimizerReview.assets.tool.label"),
          text: t("optimizerReview.assets.tool.text", { field: "query" }),
        },
        {
          label: t("optimizerReview.assets.unchanged.label"),
          text: t("optimizerReview.assets.unchanged.text"),
        },
      ]}
    />
  );
}

function Leaderboard() {
  const { t } = useTranslation("quality");
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="flex flex-wrap items-baseline justify-between gap-2 p-4">
        <h3 className="text-base font-semibold text-slate-950">
          {t("optimizerReview.leaderboard.title")}
        </h3>
        <p className="text-xs text-slate-600">
          {t("optimizerReview.leaderboard.detail", { candidates: leaderboard.length })}
        </p>
      </div>
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="border-b border-slate-200 type-label">
            <tr>
              <th scope="col" className="w-12 px-3 py-2 font-semibold sm:w-14 sm:px-4">
                {t("optimizerReview.leaderboard.columns.rank")}
              </th>
              <th scope="col" className="px-3 py-2 font-semibold sm:px-4">
                {t("optimizerReview.leaderboard.columns.candidate")}
              </th>
              <th scope="col" className="w-[42%] px-3 py-2 font-semibold sm:px-4">
                {t("optimizerReview.leaderboard.columns.score")}
              </th>
              <th scope="col" className="hidden w-28 px-4 py-2 font-semibold sm:table-cell">
                {t("optimizerReview.leaderboard.columns.status")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {leaderboard.map((entry, index) => {
              const isWinner = entry.candidate_id === job.bestCandidateId;
              const isBaseline = entry.candidate_id === job.baselineCandidateId;
              return (
                <tr key={entry.candidate_id} className={isWinner ? "bg-emerald-50" : undefined}>
                  <td className="px-3 py-2 font-mono tabular-nums text-slate-700 sm:px-4">{index + 1}</td>
                  <td className="px-3 py-2 sm:px-4">
                    <p className="font-semibold text-slate-950">{entry.name}</p>
                    <p className="truncate font-mono text-xs text-slate-500" title={entry.candidate_id}>
                      {entry.candidate_id}
                    </p>
                  </td>
                  <td className="px-3 py-2 sm:px-4">
                    <div className="flex items-center gap-3">
                      <span className="w-14 shrink-0 font-mono tabular-nums text-slate-900">
                        {entry.avg_score.toFixed(4)}
                      </span>
                      <span className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                        <span
                          className={[
                            "block h-full rounded-full",
                            isWinner ? "bg-emerald-600" : isBaseline ? "bg-amber-500" : "bg-slate-400",
                          ].join(" ")}
                          style={{ width: `${Math.min(100, entry.avg_score * 100)}%` }}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="hidden px-4 py-2 sm:table-cell">
                    <span
                      className={[
                        "rounded-full border px-2 py-0.5 text-xs font-semibold",
                        isWinner
                          ? "border-emerald-200 bg-white text-emerald-800"
                          : isBaseline
                            ? "border-amber-200 bg-amber-50 text-amber-800"
                            : "border-slate-200 bg-slate-50 text-slate-700",
                      ].join(" ")}
                    >
                      {isWinner
                        ? t("optimizerReview.leaderboard.winner")
                        : isBaseline
                          ? t("optimizerReview.leaderboard.baseline")
                          : t("optimizerReview.leaderboard.candidate")}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PromptChanges() {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const before = baseline.instructions;
  const after = candidate.instructions;
  const beforeLines = splitLines(before).length;
  const afterLines = splitLines(after).length;
  const signed = (value: number) => fmt.number(value, { signDisplay: "always" });
  const emphasis = KEYWORD_GROUPS.map((group) => {
    const count = (text: string) => group.terms.reduce((sum, term) => sum + countTerm(text, term), 0);
    const beforeCount = count(before);
    const afterCount = count(after);
    return { group, beforeCount, afterCount, delta: afterCount - beforeCount };
  });

  return (
    <div className="rounded-lg border border-slate-200">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-slate-950">{t("optimizerReview.prompt.title")}</h3>
          <p className="mt-1 text-sm text-slate-600">{t("optimizerReview.prompt.detail")}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono font-semibold text-slate-800">
            {t("optimizerReview.prompt.chars", { delta: signed(after.length - before.length) })}
          </span>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono font-semibold text-slate-800">
            {t("optimizerReview.prompt.size", { before: beforeLines, after: afterLines })}
          </span>
        </div>
      </div>

      <EmphasisList rows={emphasis} />
      <div className="hidden overflow-x-auto border-t border-slate-100 md:block">
        <table className="w-full min-w-[720px] text-left text-sm">
          <caption className="px-4 pt-3 text-left">
            <span className="text-sm font-semibold text-slate-900">
              {t("optimizerReview.emphasis.caption")}
            </span>
            <span className="ml-2 text-xs text-slate-600">{t("optimizerReview.emphasis.detail")}</span>
          </caption>
          <thead className="border-b border-slate-200 type-label">
            <tr>
              <th scope="col" className="w-[22%] px-4 py-2 font-semibold">
                {t("optimizerReview.emphasis.columns.behavior")}
              </th>
              <th scope="col" className="w-20 px-4 py-2 text-right font-semibold">
                {t("optimizerReview.emphasis.columns.baseline")}
              </th>
              <th scope="col" className="w-28 px-4 py-2 text-right font-semibold">
                {candidate.name}
              </th>
              <th scope="col" className="w-20 px-4 py-2 text-right font-semibold">
                {t("optimizerReview.emphasis.columns.delta")}
              </th>
              <th scope="col" className="px-4 py-2 font-semibold">
                {t("optimizerReview.emphasis.columns.meaning")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {emphasis.map(({ group, beforeCount, afterCount, delta }) => (
              <tr key={group.id} className="align-top">
                <th scope="row" className="px-4 py-2 font-semibold text-slate-900">
                  {t(`optimizerReview.emphasis.groups.${group.id}.label`)}
                </th>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-slate-700">{beforeCount}</td>
                <td className="px-4 py-2 text-right font-mono tabular-nums text-slate-900">{afterCount}</td>
                <td
                  className={[
                    "px-4 py-2 text-right font-mono font-semibold tabular-nums",
                    delta > 0 ? "text-emerald-700" : delta < 0 ? "text-rose-700" : "text-slate-600",
                  ].join(" ")}
                >
                  {signed(delta)}
                </td>
                <td className="px-4 py-2 text-xs leading-5 text-slate-700">
                  {t(`optimizerReview.emphasis.groups.${group.id}.meaning`)}{" "}
                  <span className="text-slate-600">
                    {t(`optimizerReview.emphasis.groups.${group.id}.business`)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-slate-100 p-4">
        <DiffDetails summary={t("optimizerReview.diff.promptSummary")} before={before} after={after} />
      </div>
    </div>
  );
}

type EmphasisRow = {
  group: (typeof KEYWORD_GROUPS)[number];
  beforeCount: number;
  afterCount: number;
  delta: number;
};

function EmphasisList({ rows }: { rows: EmphasisRow[] }) {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  return (
    <div className="border-t border-slate-100 p-4 md:hidden">
      <p className="text-sm font-semibold text-slate-900">{t("optimizerReview.emphasis.caption")}</p>
      <p className="text-xs text-slate-600">{t("optimizerReview.emphasis.detail")}</p>
      <ul className="mt-3 divide-y divide-slate-100">
        {rows.map(({ group, beforeCount, afterCount, delta }) => (
          <li key={group.id} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm font-semibold text-slate-900">
                {t(`optimizerReview.emphasis.groups.${group.id}.label`)}
              </p>
              <p className="shrink-0 font-mono text-sm tabular-nums text-slate-700">
                {beforeCount} → {afterCount}{" "}
                <span className={delta > 0 ? "font-semibold text-emerald-700" : "text-slate-600"}>
                  ({fmt.number(delta, { signDisplay: "always" })})
                </span>
              </p>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-700">
              {t(`optimizerReview.emphasis.groups.${group.id}.meaning`)}{" "}
              <span className="text-slate-600">
                {t(`optimizerReview.emphasis.groups.${group.id}.business`)}
              </span>
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ToolChanges() {
  const { t } = useTranslation("quality");
  const beforeTools = baseline.tools as ToolSpec[];
  const afterTools = candidate.tools as ToolSpec[];
  const names = [
    ...new Set([...beforeTools, ...afterTools].map((tool) => tool.function?.name ?? "tool")),
  ];
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <h3 className="text-base font-semibold text-slate-950">{t("optimizerReview.tool.title")}</h3>
      <p className="mt-1 text-sm text-slate-600">
        {t("optimizerReview.tool.detail", { candidate: candidate.name })}
      </p>
      <div className="mt-4 space-y-4">
        {names.map((name) => (
          <ToolCard
            key={name}
            name={name}
            before={beforeTools.find((tool) => tool.function?.name === name) ?? {}}
            after={afterTools.find((tool) => tool.function?.name === name) ?? {}}
          />
        ))}
      </div>
    </div>
  );
}

function ToolCard({ name, before, after }: { name: string; before: ToolSpec; after: ToolSpec }) {
  const { t } = useTranslation("quality");
  const none = t("optimizerReview.tool.none");
  const list = (items: string[]) => (items.length ? items.join(", ") : none);
  const beforeFn = before.function ?? {};
  const afterFn = after.function ?? {};
  const beforeDescription = String(beforeFn.description ?? "").trim();
  const afterDescription = String(afterFn.description ?? "").trim();
  const beforeProps = Object.keys(beforeFn.parameters?.properties ?? {});
  const afterProps = Object.keys(afterFn.parameters?.properties ?? {});
  const beforeRequired = beforeFn.parameters?.required ?? [];
  const afterRequired = afterFn.parameters?.required ?? [];
  const sameInputs =
    beforeProps.length === afterProps.length && beforeProps.every((prop, i) => prop === afterProps[i]);
  const addedRequired = afterRequired.filter((field) => !beforeRequired.includes(field));
  const removedRequired = beforeRequired.filter((field) => !afterRequired.includes(field));

  const rows = [
    { label: t("optimizerReview.tool.rows.tool"), text: t("optimizerReview.tool.toolValue", { name }) },
    {
      label: t("optimizerReview.tool.rows.input"),
      text: sameInputs
        ? t("optimizerReview.tool.inputUnchanged", { fields: list(beforeProps) })
        : t("optimizerReview.tool.inputChanged", { before: list(beforeProps), after: list(afterProps) }),
    },
    {
      label: t("optimizerReview.tool.rows.contract"),
      text: addedRequired.length
        ? t("optimizerReview.tool.nowRequired", { fields: addedRequired.join(", ") })
        : removedRequired.length
          ? t("optimizerReview.tool.noLongerRequired", { fields: removedRequired.join(", ") })
          : t("optimizerReview.tool.requiredUnchanged", { fields: list(afterRequired) }),
    },
    {
      label: t("optimizerReview.tool.rows.behavior"),
      text:
        beforeDescription === afterDescription
          ? t("optimizerReview.tool.behaviorUnchanged")
          : t("optimizerReview.tool.behaviorChanged"),
    },
  ];

  return (
    <article className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <h4 className="break-all font-mono text-sm font-semibold text-slate-950">{name}</h4>
      <dl className="mt-3 divide-y divide-slate-200">
        {rows.map((row) => (
          <div key={row.label} className="grid gap-1 py-2 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-3">
            <dt className="text-sm font-semibold text-slate-900">{row.label}</dt>
            <dd className="break-words text-sm leading-6 text-slate-700">{row.text}</dd>
          </div>
        ))}
      </dl>
      <Disclosure summary={t("optimizerReview.tool.descriptions")} className="mt-3">
        <div className="grid gap-3 p-3 lg:grid-cols-2">
          <section className="min-w-0 rounded-md border border-slate-200 bg-white p-3">
            <h5 className="type-label">{t("optimizerReview.tool.baseline")}</h5>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">
              {beforeDescription || t("optimizerReview.tool.noDescription")}
            </p>
          </section>
          <section className="min-w-0 rounded-md border border-emerald-200 bg-white p-3">
            <h5 className="type-label">{candidate.name}</h5>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-slate-700">
              {afterDescription || t("optimizerReview.tool.noDescription")}
            </p>
          </section>
        </div>
      </Disclosure>
      <DiffDetails
        className="mt-3"
        summary={t("optimizerReview.diff.toolSummary")}
        before={JSON.stringify(before, null, 2)}
        after={JSON.stringify(after, null, 2)}
      />
    </article>
  );
}

function Disclosure({
  summary,
  meta,
  className = "",
  children,
}: {
  summary: string;
  meta?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <details className={`group rounded-md border border-slate-200 bg-white ${className}`}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 text-sm font-semibold text-slate-900 hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          {summary}
          {meta ? <span className="ml-2 text-xs font-normal text-slate-600">{meta}</span> : null}
        </span>
        <HiOutlineChevronDown
          className="h-4 w-4 shrink-0 text-slate-500 transition group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="border-t border-slate-100">{children}</div>
    </details>
  );
}

function DiffDetails({
  summary,
  before,
  after,
  className = "",
}: {
  summary: string;
  before: string;
  after: string;
  className?: string;
}) {
  const { t } = useTranslation("quality");
  const { hunks, stats } = useMemo(() => {
    const rows = lineDiff(before, after);
    return { hunks: changedHunks(rows), stats: diffStats(rows) };
  }, [before, after]);

  if (hunks.length === 0) {
    return (
      <p className={`text-sm text-slate-600 ${className}`}>
        {summary} · {t("optimizerReview.diff.noChanges")}
      </p>
    );
  }

  return (
    <Disclosure
      className={className}
      summary={summary}
      meta={t("optimizerReview.diff.stats", {
        added: stats.added,
        removed: stats.removed,
        count: hunks.length,
      })}
    >
      <div className="max-h-[36rem] space-y-3 overflow-y-auto p-3">
        <p className="text-xs text-slate-600">
          {t("optimizerReview.diff.legend", { candidate: candidate.name })}
        </p>
        {hunks.map((hunk, index) => (
          <section key={index}>
            <h5 className="type-label">{t("optimizerReview.diff.hunk", { number: index + 1 })}</h5>
            <div className="mt-1 overflow-hidden rounded-md border border-slate-200 font-mono text-xs leading-5">
              {hunk.map((row, rowIndex) => (
                <DiffLine key={rowIndex} row={row} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </Disclosure>
  );
}

const DIFF_ROW_STYLES: Record<DiffRow["kind"], { row: string; sign: string }> = {
  added: { row: "bg-emerald-50 text-emerald-950", sign: "+" },
  removed: { row: "bg-rose-50 text-rose-950", sign: "−" },
  same: { row: "bg-white text-slate-700", sign: " " },
};

function DiffLine({ row }: { row: DiffRow }) {
  const style = DIFF_ROW_STYLES[row.kind];
  return (
    <div className={`grid grid-cols-[2.5rem_2.5rem_1.25rem_minmax(0,1fr)] ${style.row}`}>
      <span className="select-none pr-1 text-right text-slate-500">{row.beforeLine ?? ""}</span>
      <span className="select-none pr-1 text-right text-slate-500">{row.afterLine ?? ""}</span>
      <span className="select-none text-center font-semibold">{style.sign}</span>
      <span className="whitespace-pre-wrap break-words pr-2">{row.text || " "}</span>
    </div>
  );
}
