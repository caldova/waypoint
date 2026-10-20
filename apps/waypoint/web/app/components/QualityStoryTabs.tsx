/**
 * Quality story tabs: Part 1 (Foundry Agent Optimizer) and Part 2 (RFT), one
 * at a time. The selected part lives in the URL hash (`#rft`) so it can be
 * linked to and survives a language switch; hash-only changes don't reload
 * route data.
 */

import { useId, useRef, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";
import { RFT_PAYOFF, defaultCostReduction, stageMean, type PayoffStage } from "../data/rftPayoff";
import review from "../data/optimizerReview.json";
import { useFormat } from "../i18n/format";
import { OptimizerPanel } from "./OptimizerPanel";
import { RftPayoffPanel } from "./RftPayoffPanel";

const PARTS = ["optimizer", "rft"] as const;
type PartId = (typeof PARTS)[number];

function partFromHash(hash: string): PartId {
  return hash === "#rft" ? "rft" : "optimizer";
}

export function QualityStoryTabs() {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const location = useLocation();
  const navigate = useNavigate();
  const baseId = useId();
  const tabRefs = useRef<Partial<Record<PartId, HTMLButtonElement | null>>>({});
  const active = partFromHash(location.hash);

  const tuned = RFT_PAYOFF.stages.find((stage) => stage.id === "tuned") as PayoffStage;
  const tunedMean = stageMean(tuned);
  const metrics: Record<PartId, string> = {
    optimizer: t("qualityTabs.optimizer.metric", {
      before: review.baseline.avgScore.toFixed(3),
      after: review.candidate.avgScore.toFixed(3),
    }),
    rft: t("qualityTabs.rft.metric", {
      pass: fmt.percent(tunedMean, Number.isInteger(tunedMean * 100) ? 0 : 1),
      savings: fmt.percent(defaultCostReduction(), 1),
    }),
  };

  const select = (part: PartId, focus = false) => {
    if (part !== active) {
      navigate(
        { search: location.search, hash: part === "optimizer" ? "" : `#${part}` },
        { replace: true, preventScrollReset: true },
      );
    }
    if (focus) {
      tabRefs.current[part]?.focus();
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = PARTS.indexOf(active);
    const next =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? PARTS[(index + 1) % PARTS.length]
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? PARTS[(index - 1 + PARTS.length) % PARTS.length]
          : event.key === "Home"
            ? PARTS[0]
            : event.key === "End"
              ? PARTS[PARTS.length - 1]
              : null;
    if (next) {
      event.preventDefault();
      select(next, true);
    }
  };

  return (
    <section className="mt-6" aria-label={t("qualityTabs.ariaLabel")}>
      <div role="tablist" aria-label={t("qualityTabs.ariaLabel")} className="grid gap-2 sm:grid-cols-2">
        {PARTS.map((part) => {
          const selected = part === active;
          return (
            <button
              key={part}
              ref={(node) => {
                tabRefs.current[part] = node;
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${part}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${part}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(part)}
              onKeyDown={onKeyDown}
              className={[
                "flex min-w-0 flex-col items-start gap-0.5 rounded-xl border px-4 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2",
                selected
                  ? "border-blue-300 bg-blue-50 shadow-sm ring-1 ring-blue-200"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50",
              ].join(" ")}
            >
              <span className={`type-label ${selected ? "text-blue-700" : ""}`}>
                {t(`qualityTabs.${part}.step`)}
              </span>
              <span className="text-base font-semibold text-slate-950">
                {t(`qualityTabs.${part}.title`)}
              </span>
              <span className="text-sm text-slate-600">{t(`qualityTabs.${part}.subtitle`)}</span>
              <span className="mt-1 font-mono text-sm font-semibold tabular-nums text-slate-900">
                {metrics[part]}
              </span>
            </button>
          );
        })}
      </div>
      {PARTS.map((part) => (
        <div
          key={part}
          role="tabpanel"
          id={`${baseId}-panel-${part}`}
          aria-labelledby={`${baseId}-tab-${part}`}
          hidden={part !== active}
          className="mt-3"
        >
          {part === active ? part === "optimizer" ? <OptimizerPanel /> : <RftPayoffPanel /> : null}
        </div>
      ))}
    </section>
  );
}
