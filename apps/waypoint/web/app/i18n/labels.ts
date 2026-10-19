import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

const DECISIONS = ["approve", "review", "recover", "escalate"] as const;
type Decision = (typeof DECISIONS)[number];

// Upstream agents occasionally emit the noun/past-tense form.
const DECISION_ALIASES: Record<string, Decision> = {
  recovery: "recover",
  approved: "approve",
};

const RUN_STATUSES = [
  "pending",
  "queued",
  "waiting",
  "created",
  "running",
  "in_progress",
  "active",
  "partial",
  "completed",
  "failed",
  "error",
] as const;
type RunStatus = (typeof RUN_STATUSES)[number];

const ACTIONS = [
  "recommend_recover",
  "draft_supplier_dispute",
  "request_legal_escalation",
  "request_quality_review",
] as const;
type Action = (typeof ACTIONS)[number];

const PLANES = ["foundryiq", "fabriciq", "workiq", "webiq"] as const;
type Plane = (typeof PLANES)[number];

// Keep in sync with `lib/integrations.ts`.
const INTEGRATION_KEYS = ["oracle-erp"] as const;
type IntegrationKey = (typeof INTEGRATION_KEYS)[number];

function includes<T extends string>(list: readonly T[], value: string): value is T {
  return (list as readonly string[]).includes(value);
}

/** Turn an unknown snake_case/kebab-case id into readable text. */
export function humanize(value: string): string {
  const text = value.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : value;
}

export function normalizeDecision(value: string | null | undefined): string {
  const key = (value ?? "").trim().toLowerCase();
  return DECISION_ALIASES[key] ?? key;
}

export function createLabels(t: TFunction<"common">) {
  return {
    /** Display label for an assurance decision; unknown values are humanized. */
    decision(value: string | null | undefined): string {
      const key = normalizeDecision(value);
      return includes(DECISIONS, key) ? t(`decision.${key}`) : humanize(value ?? "");
    },
    /** Display label for a run status; unknown values are humanized. */
    runStatus(value: string | null | undefined): string {
      const key = (value ?? "").trim().toLowerCase();
      return includes(RUN_STATUSES, key) ? t(`runStatus.${key as RunStatus}`) : humanize(value ?? "");
    },
    /** Display label for a proposed-action id (mirrors backend ActionType names). */
    action(value: string): string {
      return includes(ACTIONS, value) ? t(`action.${value as Action}`) : humanize(value);
    },
    planeScope(plane: string): string {
      return includes(PLANES, plane) ? t(`planeScope.${plane as Plane}`) : "";
    },
    /** Localized subtitle for a third-party integration; falls back to its English `scope`. */
    integrationScope(integration: { key: string; scope: string }): string {
      return includes(INTEGRATION_KEYS, integration.key)
        ? t(`integrationScope.${integration.key as IntegrationKey}`)
        : integration.scope;
    },
    /** Only a calibrated score is called "confidence". */
    score(ratio: number, calibrated: boolean): string {
      const value = Math.round(ratio * 100);
      return calibrated ? t("score.confidence", { value }) : t("score.evidenceScore", { value });
    },
  };
}

export type Labels = ReturnType<typeof createLabels>;

/** Translated labels for shared domain enums (decisions, run statuses, actions). */
export function useLabels(): Labels {
  const { t } = useTranslation("common");
  return useMemo(() => createLabels(t), [t]);
}
