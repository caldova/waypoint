/**
 * Contract-policy expert MAI RFT payoff: eval results for the baseline,
 * optimized, and tuned MAI agent, the model swap, and an interactive cost
 * estimate. Web version of the RFT Cost Quality canvas.
 */

import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  HiOutlineArrowRight,
  HiOutlineArrowsRightLeft,
  HiOutlineChevronDown,
} from "react-icons/hi2";
import {
  RFT_PAYOFF,
  stageMean,
  type CostOption,
  type CostOptionId,
  type PayoffStage,
  type PayoffStageId,
} from "../data/rftPayoff";
import { useFormat, type Formatters } from "../i18n/format";

const STAGE_STYLES: Record<PayoffStageId, { bar: string }> = {
  baseline: { bar: "bg-amber-500" },
  optimized: { bar: "bg-emerald-600" },
  tuned: { bar: "bg-blue-700" },
};

const RUN_COUNT = RFT_PAYOFF.stages[0].passes.length;

type PriceInputs = Record<CostOptionId, { input: string; output: string }>;

function defaultPrices(): PriceInputs {
  const prices = {} as PriceInputs;
  for (const option of RFT_PAYOFF.cost.options) {
    prices[option.id] = {
      input: String(option.inputPricePerMillion),
      output: String(option.outputPricePerMillion),
    };
  }
  return prices;
}

function parsePrice(value: string): number {
  const price = Number(value);
  return Number.isFinite(price) && price > 0 ? price : 0;
}

function estimateCost(option: CostOption, requests: number, prices: { input: string; output: string }) {
  const scale = requests / RFT_PAYOFF.cost.observedRequests;
  const inputTokens = Math.round(option.inputTokens * scale);
  const outputTokens = Math.round(option.outputTokens * scale);
  const inputPrice = parsePrice(prices.input);
  const outputPrice = parsePrice(prices.output);
  return {
    inputTokens,
    outputTokens,
    inputPrice,
    outputPrice,
    cost: (inputTokens * inputPrice + outputTokens * outputPrice) / 1_000_000,
  };
}

/** 61.7% for fractional means, 100% (not 100.0%) for whole ones. */
function meanLabel(fmt: Formatters, ratio: number): string {
  return fmt.percent(ratio, Number.isInteger(Math.round(ratio * 1000) / 10) ? 0 : 1);
}

function shortId(id: string, keep = 9): string {
  return id.length > keep + 1 ? `${id.slice(0, keep)}…` : id;
}

function money(fmt: Formatters, value: number): string {
  return fmt.currency(value, "USD", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function stageById(id: PayoffStageId): PayoffStage {
  return RFT_PAYOFF.stages.find((stage) => stage.id === id) as PayoffStage;
}

export function RftPayoffPanel() {
  const { t } = useTranslation("quality");
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <header className="border-b border-slate-100 p-5 lg:p-6">
        <p className="type-label text-blue-700">{t("rftPayoff.eyebrow")}</p>
        <h2 id={titleId} className="mt-1 text-xl font-semibold tracking-tight text-slate-950">
          {t("rftPayoff.title")}
        </h2>
        <p className="mt-2 max-w-[80ch] text-sm leading-6 text-slate-600">
          {t("rftPayoff.intro", {
            agent: RFT_PAYOFF.agent,
            runs: RUN_COUNT,
            rows: RFT_PAYOFF.rowsPerRun,
          })}
        </p>
        <p className="mt-2 break-words font-mono text-xs text-slate-500">
          {t("rftPayoff.evalSetup", {
            dataset: RFT_PAYOFF.dataset.name,
            datasetVersion: RFT_PAYOFF.dataset.version,
            rubric: RFT_PAYOFF.rubric.name,
            rubricVersion: RFT_PAYOFF.rubric.version,
          })}
        </p>
      </header>
      <div className="space-y-6 p-5 lg:p-6">
        <StageRow />
        <ModelSwap />
        <CostEstimator />
        <ComparisonTable />
        <FinalResults />
      </div>
    </section>
  );
}

function StageRow() {
  const { t } = useTranslation("quality");
  return (
    <div
      role="group"
      aria-label={t("rftPayoff.stages.ariaLabel")}
      className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)]"
    >
      <StageCard stage={stageById("baseline")} />
      <StageConnector label={t("rftPayoff.stages.toOptimized")} />
      <StageCard stage={stageById("optimized")} />
      <StageConnector label={t("rftPayoff.stages.toTuned")} />
      <StageCard stage={stageById("tuned")} />
    </div>
  );
}

function StageCard({ stage }: { stage: PayoffStage }) {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const style = STAGE_STYLES[stage.id];
  const rows = RFT_PAYOFF.rowsPerRun;
  const passed = stage.passes.reduce((sum, value) => sum + value, 0);
  return (
    <article className="flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${style.bar}`} aria-hidden="true" />
          {t(`rftPayoff.stages.${stage.id}.label`)}
        </h3>
        <span className="font-mono text-xs text-slate-500">
          {t("rftPayoff.stages.agentVersion", { version: stage.agentVersion })}
        </span>
      </div>
      <p className="mt-2 font-mono text-3xl font-semibold tabular-nums text-slate-950">
        {meanLabel(fmt, stageMean(stage))}
      </p>
      <p className="text-xs text-slate-600">
        {t("rftPayoff.stages.passed", { passed, total: stage.passes.length * rows })}
      </p>
      <div
        role="img"
        aria-label={t("rftPayoff.stages.runsAria", {
          runs: stage.passes.map((value) => `${value}/${rows}`).join(", "),
        })}
        className="mt-3 flex items-end gap-1.5"
      >
        {stage.passes.map((value, index) => (
          <div key={index} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-10 w-full items-end overflow-hidden rounded-sm bg-slate-100">
              <div
                className={`w-full rounded-sm ${style.bar}`}
                style={{ height: `${(value / rows) * 100}%` }}
              />
            </div>
            <span className="text-xs tabular-nums text-slate-500">{value}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 flex-1 text-xs leading-5 text-slate-600">
        {t(`rftPayoff.stages.${stage.id}.detail`, { candidate: RFT_PAYOFF.optimizer.candidate })}
      </p>
      <div className="mt-3 space-y-0.5 border-t border-slate-100 pt-2 font-mono text-xs text-slate-600">
        <p className="truncate" title={stage.model}>
          {stage.model}
        </p>
        <p className="truncate text-slate-500" title={stage.evalId}>
          {stage.evalId}
        </p>
      </div>
    </article>
  );
}

function StageConnector({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-1 lg:w-24 lg:flex-col lg:px-1 lg:py-0">
      <HiOutlineArrowRight className="h-5 w-5 rotate-90 text-slate-400 lg:rotate-0" aria-hidden="true" />
      <span className="text-xs font-medium text-slate-600 lg:text-center">{label}</span>
    </div>
  );
}

function ModelSwap() {
  const { t } = useTranslation("quality");
  const { optimizer, rft } = RFT_PAYOFF;
  return (
    <div
      role="group"
      aria-label={t("rftPayoff.swap.ariaLabel")}
      className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-stretch"
    >
      <SwapCard
        label={t("rftPayoff.swap.optimizedLabel")}
        model={stageById("optimized").model}
        detail={t("rftPayoff.swap.optimizedDetail", {
          candidate: optimizer.candidate,
          job: optimizer.jobId,
        })}
      />
      <div className="flex items-center justify-center gap-2 py-1 md:w-24 md:flex-col md:py-0">
        <HiOutlineArrowsRightLeft className="h-5 w-5 rotate-90 text-blue-700 md:rotate-0" aria-hidden="true" />
        <span className="text-xs font-medium text-slate-600 md:text-center">
          {t("rftPayoff.swap.swapOnly")}
        </span>
      </div>
      <SwapCard
        highlight
        label={t("rftPayoff.swap.tunedLabel")}
        model={rft.deployment}
        detail={t("rftPayoff.swap.tunedDetail")}
        footnote={rft.fineTunedModel}
      />
    </div>
  );
}

function SwapCard({
  label,
  model,
  detail,
  footnote,
  highlight = false,
}: {
  label: string;
  model: string;
  detail: string;
  footnote?: string;
  highlight?: boolean;
}) {
  const { t } = useTranslation("quality");
  return (
    <article
      className={[
        "min-w-0 rounded-lg border p-4",
        highlight ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white",
      ].join(" ")}
    >
      <p className="type-label">{label}</p>
      <h3 className="mt-1 text-base font-semibold text-slate-950">{t("rftPayoff.swap.agentName")}</h3>
      <code
        className="mt-2 inline-block max-w-full truncate rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs font-semibold text-slate-800"
        title={model}
      >
        {model}
      </code>
      <p className="mt-2 break-words text-xs leading-5 text-slate-600">{detail}</p>
      {footnote ? (
        <p className="mt-2 truncate border-t border-blue-100 pt-2 font-mono text-xs text-slate-600" title={footnote}>
          {footnote}
        </p>
      ) : null}
    </article>
  );
}

function CostEstimator() {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const titleId = useId();
  const sliderId = useId();
  const { cost } = RFT_PAYOFF;
  const [requests, setRequests] = useState<number>(cost.minRequests);
  const [prices, setPrices] = useState<PriceInputs>(defaultPrices);

  const estimates = cost.options.map((option) => ({
    option,
    estimate: estimateCost(option, requests, prices[option.id]),
  }));
  const astra = estimates.find(({ option }) => option.id === "optimized")!.estimate;
  const tuned = estimates.find(({ option }) => option.id === "tuned")!.estimate;
  const hasPrices = estimates.some(
    ({ estimate }) => estimate.inputPrice > 0 || estimate.outputPrice > 0,
  );
  const delta = astra.cost - tuned.cost;
  const requestsLabel = fmt.number(requests);

  let summary: string;
  let summaryTone: string;
  if (!hasPrices) {
    const extra = tuned.outputTokens - astra.outputTokens;
    summary = t("rftPayoff.cost.noPrices", {
      tokens: fmt.number(extra),
      percent: fmt.percent(astra.outputTokens ? extra / astra.outputTokens : 0, 1),
    });
    summaryTone = "border-slate-200 bg-slate-50 text-slate-800";
  } else if (delta >= 0) {
    summary = t("rftPayoff.cost.savings", {
      requests: requestsLabel,
      amount: money(fmt, delta),
      percent: fmt.percent(astra.cost > 0 ? delta / astra.cost : 0, 1),
    });
    summaryTone = "border-emerald-200 bg-emerald-50 text-emerald-900";
  } else {
    summary = t("rftPayoff.cost.higher", { requests: requestsLabel, amount: money(fmt, -delta) });
    summaryTone = "border-amber-200 bg-amber-50 text-amber-900";
  }

  return (
    <section aria-labelledby={titleId} className="rounded-lg border border-slate-200 p-4 lg:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={titleId} className="text-base font-semibold text-slate-950">
          {t("rftPayoff.cost.title")}
        </h3>
        <label htmlFor={sliderId} className="font-mono text-sm font-semibold tabular-nums text-slate-700">
          {t("rftPayoff.cost.volume", { requests: requestsLabel })}
        </label>
      </div>
      <input
        id={sliderId}
        type="range"
        min={cost.minRequests}
        max={cost.maxRequests}
        step={cost.step}
        value={requests}
        onChange={(event) => setRequests(Number(event.target.value))}
        aria-valuetext={t("rftPayoff.cost.volume", { requests: requestsLabel })}
        className="mt-3 h-2 w-full cursor-pointer accent-blue-700"
      />
      <div className="mt-1 flex justify-between text-xs text-slate-500">
        <span>{fmt.number(cost.minRequests, { notation: "compact" })}</span>
        <span>{fmt.number(cost.maxRequests, { notation: "compact" })}</span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {estimates.map(({ option, estimate }) => (
          <CostCard
            key={option.id}
            option={option}
            total={estimate}
            prices={prices[option.id]}
            onPriceChange={(kind, value) =>
              setPrices((current) => ({
                ...current,
                [option.id]: { ...current[option.id], [kind]: value },
              }))
            }
          />
        ))}
      </div>

      <p aria-live="polite" className={`mt-4 rounded-lg border px-3 py-2 text-sm font-semibold ${summaryTone}`}>
        {summary}
      </p>
      <p className="mt-3 text-xs leading-5 text-slate-600">{t("rftPayoff.cost.pricesNote")}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{t("rftPayoff.cost.basis")}</p>
    </section>
  );
}

function CostCard({
  option,
  total,
  prices,
  onPriceChange,
}: {
  option: CostOption;
  total: ReturnType<typeof estimateCost>;
  prices: { input: string; output: string };
  onPriceChange: (kind: "input" | "output", value: string) => void;
}) {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const { cost } = RFT_PAYOFF;
  const highlight = option.id === "tuned";
  const perUnit = estimateCost(option, cost.unitSize, prices).cost;
  return (
    <article
      className={[
        "min-w-0 rounded-lg border p-4",
        highlight ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-slate-950">
            {t(`rftPayoff.cost.options.${option.id}`)}
          </h4>
          <p className="truncate font-mono text-xs text-slate-600" title={option.model}>
            {option.model}
          </p>
        </div>
        <p className="text-xs text-slate-600 sm:text-right">
          {t("rftPayoff.cost.perUnit", {
            amount: money(fmt, perUnit),
            unit: fmt.number(cost.unitSize),
          })}
        </p>
      </div>
      <p className="mt-3 font-mono text-3xl font-semibold tabular-nums text-slate-950">
        {money(fmt, total.cost)}
      </p>
      <p className="mt-1 text-xs text-slate-600">
        {t("rftPayoff.cost.perRequest", {
          input: fmt.number(Math.round(option.inputTokens / cost.observedRequests)),
          output: fmt.number(Math.round(option.outputTokens / cost.observedRequests)),
        })}
      </p>
      <p className="text-xs text-slate-600">
        {t("rftPayoff.cost.totals", {
          input: fmt.number(total.inputTokens),
          output: fmt.number(total.outputTokens),
        })}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <PriceField
          label={t("rftPayoff.cost.inputPrice")}
          value={prices.input}
          onChange={(value) => onPriceChange("input", value)}
        />
        <PriceField
          label={t("rftPayoff.cost.outputPrice")}
          value={prices.output}
          onChange={(value) => onPriceChange("output", value)}
        />
      </div>
    </article>
  );
}

function PriceField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="type-label">
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        step={0.01}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-sm tabular-nums text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      />
    </div>
  );
}

type TableCell = string | { text: string; mono: true };

type TableRowId =
  | "mean"
  | "spread"
  | "optimizer"
  | "evals"
  | "behavior"
  | "model"
  | "rftJob"
  | "fineTuned"
  | "deployment"
  | "costEvidence";

interface TableRow {
  id: TableRowId;
  area: string;
  cells: [TableCell, TableCell, TableCell];
  takeaway: string;
}

function useComparisonRows(): TableRow[] {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const { optimizer, rft, cost, rowsPerRun: rows } = RFT_PAYOFF;
  const stages = (["baseline", "optimized", "tuned"] as const).map(stageById);
  const na = t("rftPayoff.table.notApplicable");
  const mono = (text: string): TableCell => ({ text, mono: true });
  const score = (value: number) =>
    fmt.number(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  const spread = (stage: PayoffStage) => {
    const min = Math.min(...stage.passes);
    const max = Math.max(...stage.passes);
    return min === max
      ? t("rftPayoff.table.rows.spread.every", { passed: min, rows })
      : t("rftPayoff.table.rows.spread.range", { min, max, rows });
  };
  const tokensPerRequest = (id: CostOptionId) => {
    const option = cost.options.find((item) => item.id === id) as CostOption;
    return t("rftPayoff.table.rows.costEvidence.cell", {
      input: fmt.number(Math.round(option.inputTokens / cost.observedRequests)),
      output: fmt.number(Math.round(option.outputTokens / cost.observedRequests)),
    });
  };
  const three = (make: (stage: PayoffStage) => TableCell) =>
    stages.map(make) as [TableCell, TableCell, TableCell];
  const row = (id: TableRowId, cells: [TableCell, TableCell, TableCell]): TableRow => ({
    id,
    area: t(`rftPayoff.table.rows.${id}.area`),
    cells,
    takeaway: t(`rftPayoff.table.rows.${id}.takeaway`),
  });

  return [
    row(
      "mean",
      three((stage) =>
        t("rftPayoff.table.rows.mean.cell", {
          mean: meanLabel(fmt, stageMean(stage)),
          runs: stage.passes.length,
          rows,
        }),
      ),
    ),
    row("spread", three(spread)),
    row("optimizer", [
      t("rftPayoff.table.rows.optimizer.baseline", { score: score(optimizer.baselineScore) }),
      t("rftPayoff.table.rows.optimizer.optimized", {
        candidate: optimizer.candidate,
        score: score(optimizer.candidateScore),
      }),
      t("rftPayoff.table.rows.optimizer.tuned"),
    ]),
    row(
      "evals",
      three((stage) =>
        t("rftPayoff.table.rows.evals.cell", {
          version: stage.agentVersion,
          evalId: shortId(stage.evalId),
        }),
      ),
    ),
    row("behavior", [
      t("rftPayoff.table.rows.behavior.baseline"),
      t("rftPayoff.table.rows.behavior.optimized", { candidate: optimizer.candidate }),
      t("rftPayoff.table.rows.behavior.tuned"),
    ]),
    row("model", [
      mono(stages[0].model),
      mono(stages[1].model),
      t("rftPayoff.table.rows.model.tuned"),
    ]),
    row("rftJob", [na, na, mono(rft.jobId)]),
    row("fineTuned", [na, na, mono(rft.fineTunedModel)]),
    row("deployment", [na, na, mono(rft.deployment)]),
    row("costEvidence", [
      t("rftPayoff.table.rows.costEvidence.baseline"),
      tokensPerRequest("optimized"),
      tokensPerRequest("tuned"),
    ]),
  ];
}

function ComparisonTable() {
  const { t } = useTranslation("quality");
  const rows = useComparisonRows();
  const columns = ["baseline", "optimized", "tuned"] as const;
  return (
    <details className="group rounded-lg border border-slate-200">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-4 text-sm font-semibold text-slate-900 hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
        {t("rftPayoff.table.summary")}
        <HiOutlineChevronDown
          className="h-4 w-4 text-slate-500 transition group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="overflow-x-auto border-t border-slate-100">
        <table className="w-full min-w-[760px] table-fixed text-left text-sm">
          <thead className="border-b border-slate-200 type-label">
            <tr>
              <th scope="col" className="w-[16%] px-4 py-3 font-semibold">
                {t("rftPayoff.table.columns.area")}
              </th>
              {columns.map((column) => (
                <th key={column} scope="col" className="px-4 py-3 font-semibold">
                  {t(`rftPayoff.table.columns.${column}`)}
                </th>
              ))}
              <th scope="col" className="w-[26%] px-4 py-3 font-semibold">
                {t("rftPayoff.table.columns.takeaway")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={row.id} className="align-top">
                <th scope="row" className="px-4 py-3 font-semibold text-slate-900">
                  {row.area}
                </th>
                {row.cells.map((cell, index) =>
                  typeof cell === "string" ? (
                    <td key={index} className="px-4 py-3 text-slate-700">
                      {cell}
                    </td>
                  ) : (
                    <td key={index} className="px-4 py-3">
                      <span className="block truncate font-mono text-xs text-slate-700" title={cell.text}>
                        {cell.text}
                      </span>
                    </td>
                  ),
                )}
                <td className="px-4 py-3 text-slate-600">{row.takeaway}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function FinalResults() {
  const { t } = useTranslation("quality");
  const { optimizer, rft, rowsPerRun } = RFT_PAYOFF;
  const optimized = stageById("optimized");
  const tuned = stageById("tuned");
  const passedLabel = (stage: PayoffStage) =>
    `${stage.passes.reduce((sum, value) => sum + value, 0)}/${stage.passes.length * rowsPerRun}`;
  const items: Array<[string, string]> = [
    [t("rftPayoff.results.optimizer"), optimizer.jobId],
    [t("rftPayoff.results.candidate"), `${optimizer.candidate} / ${optimizer.candidateId}`],
    [t("rftPayoff.results.foundryEval"), optimized.evalId],
    [t("rftPayoff.results.evalRuns"), t("rftPayoff.results.evalRunsValue", { runs: RUN_COUNT })],
    [t("rftPayoff.results.rftJob"), rft.jobId],
    [t("rftPayoff.results.rftDeployment"), rft.deployment],
  ];
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 lg:p-5">
      <h3 className="text-base font-semibold text-blue-950">{t("rftPayoff.results.title")}</h3>
      <p className="mt-1 max-w-[90ch] text-sm leading-6 text-blue-900">
        {t("rftPayoff.results.body", {
          candidate: optimizer.candidate,
          optimized: passedLabel(optimized),
          tuned: passedLabel(tuned),
        })}
      </p>
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
        {items.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="font-semibold text-blue-950">{label}</dt>
            <dd className="truncate font-mono text-blue-900" title={value}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
