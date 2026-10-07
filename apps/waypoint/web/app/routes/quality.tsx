import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { IconType } from "react-icons";
import {
  HiOutlineArrowTrendingDown,
  HiOutlineArrowTrendingUp,
  HiOutlineArrowTopRightOnSquare,
  HiOutlineBeaker,
  HiOutlineBolt,
  HiOutlineCheckCircle,
  HiOutlineClock,
  HiOutlineCodeBracketSquare,
  HiOutlineExclamationTriangle,
  HiOutlineLockClosed,
  HiOutlineQueueList,
  HiOutlineShieldCheck,
} from "react-icons/hi2";
import type { MetaFunction } from "react-router";
import { useOutletContext } from "react-router";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { fetchDrilldownConfig, type DrilldownConfig } from "../../lib/waypointConfig";
import { AppHeader } from "../components/AppHeader";
import { RequireAuth } from "../components/RequireAuth";
import { useFormat, type Formatters } from "../i18n/format";
import { pageMeta } from "../i18n/meta";

export const meta: MetaFunction = ({ matches }) => pageMeta(matches, "quality");

type EvidenceState = "current" | "reference-only" | "stale";
type OperationAvailability = "available" | "guarded" | "blocked";
type OperationStage = "run" | "inspect" | "measure" | "improve" | "release";

interface StateDefinition {
  state: EvidenceState;
  label: string;
  description: string;
}

interface EvidenceCheck {
  name: string;
  state: EvidenceState;
  detail: string;
}

interface Operation {
  id: string;
  label: string;
  stage: OperationStage;
  purpose: string;
  availability: OperationAvailability;
  execution: "bounded" | "no-wait" | "protected";
  prerequisites: string[];
}

interface QualityManifest {
  schemaVersion: string;
  manifestId: string;
  evidenceState: EvidenceState;
  reviewedAt: string;
  staleAfter: string;
  source: {
    repository: string;
    workflow: string;
    kind: string;
  };
  stateDefinitions: StateDefinition[];
  checks: EvidenceCheck[];
  lineage: {
    agent: string;
    environment: string;
    dataset: {
      name: string;
      version: string;
      samplesPerRun: number;
    };
    evaluator: {
      name: string;
      version: string;
    };
    baseline: {
      state: EvidenceState;
      agentVersion: string;
      model: string;
      evaluationId: string;
      aggregatePassRate: number;
      runs: number;
    };
    optimizer: {
      state: EvidenceState;
      jobId: string;
      status: string;
      baselineCandidateId: string;
      baselineScore: number;
      acceptedCandidateId: string;
      acceptedScore: number;
      strategy: string;
    };
    rft: {
      state: EvidenceState;
      jobId: string;
      model: string;
      deployment: string;
      evaluationId: string;
      aggregatePassRate: number;
      estimatedCostReduction: number;
    };
  };
  operations: Operation[];
}

interface QualityOutletContext {
  qualityOperations: {
    repositoryUrl: string;
    workflowFile: string;
    rftEnvironment: string;
  };
}

const MANIFEST_URL = "/quality/evidence-manifest.v1.json";

const OPERATION_STAGES = [
  {
    id: "run",
    step: 1,
    titleKey: "stages.run.title",
    detailKey: "stages.run.detail",
  },
  {
    id: "inspect",
    step: 2,
    titleKey: "stages.inspect.title",
    detailKey: "stages.inspect.detail",
  },
  {
    id: "measure",
    step: 3,
    titleKey: "stages.measure.title",
    detailKey: "stages.measure.detail",
  },
  {
    id: "improve",
    step: 4,
    titleKey: "stages.improve.title",
    detailKey: "stages.improve.detail",
  },
  {
    id: "release",
    step: 5,
    titleKey: "stages.release.title",
    detailKey: "stages.release.detail",
  },
] as const satisfies ReadonlyArray<{
  id: OperationStage;
  step: number;
  titleKey: string;
  detailKey: string;
}>;

/** UI copy for each evidence state (the manifest's own labels stay as evidence data). */
const EVIDENCE_STATE_KEYS = {
  current: {
    labelKey: "evidenceState.current.label",
    descriptionKey: "evidenceState.current.description",
  },
  "reference-only": {
    labelKey: "evidenceState.referenceOnly.label",
    descriptionKey: "evidenceState.referenceOnly.description",
  },
  stale: {
    labelKey: "evidenceState.stale.label",
    descriptionKey: "evidenceState.stale.description",
  },
} as const satisfies Record<EvidenceState, unknown>;

/** The manifest request answered with an error status (message is translated at render). */
class ManifestStatusError extends Error {
  constructor(readonly status: number) {
    super(`Evidence manifest returned ${status}`);
  }
}

type LoadFailure = { status: number } | { message: string | null };

function safeHttpsUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString().replace(/\/$/, "") : null;
  } catch {
    return null;
  }
}

function formatPercent(value: number, fmt: Formatters): string {
  return fmt.percent(value, 1);
}

function formatScore(value: number, fmt: Formatters): string {
  return fmt.number(value, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function formatDate(value: string, fmt: Formatters, t: TFunction<["quality", "common"]>): string {
  return fmt.dateTime(value, { dateStyle: "medium", timeStyle: "short" }) ?? t("common:unknown");
}

function effectiveState(manifest: QualityManifest): EvidenceState {
  if (manifest.evidenceState !== "current") return manifest.evidenceState;
  const staleAt = new Date(manifest.staleAfter).getTime();
  return Number.isFinite(staleAt) && staleAt < Date.now() ? "stale" : "current";
}

export default function Quality() {
  const { t } = useTranslation("quality");
  const { qualityOperations } = useOutletContext<QualityOutletContext>();
  const [manifest, setManifest] = useState<QualityManifest | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownConfig | null>(null);
  const [error, setError] = useState<LoadFailure | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetch(MANIFEST_URL, { signal: controller.signal }).then(async (response) => {
        if (!response.ok) {
          throw new ManifestStatusError(response.status);
        }
        return (await response.json()) as QualityManifest;
      }),
      fetchDrilldownConfig(),
    ]).then(
      ([evidence, config]) => {
        setManifest(evidence);
        setDrilldown(config);
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof ManifestStatusError
              ? { status: reason.status }
              : { message: reason instanceof Error ? reason.message : null },
          );
        }
      },
    );
    return () => controller.abort();
  }, []);

  const errorMessage = !error
    ? null
    : "status" in error
      ? t("errors.manifestStatus", { status: error.status })
      : (error.message ?? t("errors.unavailable"));

  const repositoryUrl = safeHttpsUrl(qualityOperations.repositoryUrl);
  const workflowUrl = repositoryUrl
    ? `${repositoryUrl}/actions/workflows/${encodeURIComponent(qualityOperations.workflowFile)}`
    : null;
  const foundryUrl = useMemo(
    () => safeHttpsUrl(drilldown?.foundry_project_url || drilldown?.foundry_endpoint || ""),
    [drilldown],
  );

  return (
    <RequireAuth>
      <div className="min-h-screen bg-slate-50 text-slate-950">
        <AppHeader />
        <main id="main-content" className="mx-auto max-w-[1500px] px-3 py-4 2xl:px-4">
          {errorMessage ? <QualityError message={errorMessage} /> : null}
          {!manifest && !errorMessage ? <QualitySkeleton /> : null}
          {manifest ? (
            <>
              <Hero
                manifest={manifest}
                workflowUrl={workflowUrl}
                foundryUrl={foundryUrl}
              />
              <GovernanceStrip environment={qualityOperations.rftEnvironment} />
              <OperationsPanel operations={manifest.operations} workflowUrl={workflowUrl} />
              <MetricGrid manifest={manifest} />
              <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
                <LineagePanel manifest={manifest} />
                <aside className="space-y-6">
                  <EvidencePanel manifest={manifest} />
                  <LaunchPolicy
                    environment={qualityOperations.rftEnvironment}
                    workflowUrl={workflowUrl}
                    foundryUrl={foundryUrl}
                  />
                </aside>
              </div>
            </>
          ) : null}
        </main>
      </div>
    </RequireAuth>
  );
}

function Hero({
  manifest,
  workflowUrl,
  foundryUrl,
}: {
  manifest: QualityManifest;
  workflowUrl: string | null;
  foundryUrl: string | null;
}) {
  const state = effectiveState(manifest);
  const { t } = useTranslation("quality");
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm lg:p-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={state} />
            <span className="text-xs font-medium text-slate-500">
              {t("hero.schemaVersion", { version: manifest.schemaVersion })}
            </span>
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-slate-950">
            {t("hero.title")}
          </h1>
          <p className="mt-2 max-w-[65ch] text-sm leading-6 text-slate-600">
            {t("hero.description")}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <ExternalAction href={workflowUrl} icon={HiOutlineBolt} primary>
            {t("hero.openWorkflow")}
          </ExternalAction>
          <ExternalAction href={foundryUrl} icon={HiOutlineArrowTopRightOnSquare}>
            {t("hero.openFoundry")}
          </ExternalAction>
        </div>
      </div>
    </section>
  );
}

function GovernanceStrip({ environment }: { environment: string }) {
  const { t } = useTranslation("quality");
  return (
    <section
      aria-label={t("governance.ariaLabel")}
      className="mt-4 grid gap-4 rounded-xl border border-blue-200 bg-blue-50 p-4 md:grid-cols-[auto_1fr_auto] md:items-center"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-blue-700 shadow-sm">
        <HiOutlineShieldCheck className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <h2 className="text-sm font-semibold text-blue-950">{t("governance.title")}</h2>
        <p className="mt-1 max-w-[80ch] text-sm leading-6 text-blue-800">
          {t("governance.description")}
        </p>
      </div>
      <code className="w-fit rounded-md border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-800">
        {environment}
      </code>
    </section>
  );
}

function MetricGrid({ manifest }: { manifest: QualityManifest }) {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const optimizerLift =
    manifest.lineage.optimizer.acceptedScore - manifest.lineage.optimizer.baselineScore;
  return (
    <section className="mt-6 grid gap-4 md:grid-cols-3" aria-label={t("metrics.ariaLabel")}>
      <MetricCard
        icon={HiOutlineArrowTrendingUp}
        label={t("metrics.inferenceReduction.label")}
        value={formatPercent(manifest.lineage.rft.estimatedCostReduction, fmt)}
        detail={t("metrics.inferenceReduction.detail")}
      />
      <MetricCard
        icon={HiOutlineBeaker}
        label={t("metrics.rftPassRate.label")}
        value={formatPercent(manifest.lineage.rft.aggregatePassRate, fmt)}
        detail={t("metrics.rftPassRate.detail", {
          samples: manifest.lineage.dataset.samplesPerRun,
          runs: manifest.lineage.baseline.runs,
        })}
      />
      <MetricCard
        icon={HiOutlineArrowTrendingDown}
        label={t("metrics.optimizerLift.label")}
        value={`+${formatScore(optimizerLift, fmt)}`}
        detail={`${formatScore(manifest.lineage.optimizer.baselineScore, fmt)} → ${formatScore(manifest.lineage.optimizer.acceptedScore, fmt)}`}
      />
    </section>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: IconType;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <Icon className="h-5 w-5 text-blue-600" aria-hidden="true" />
      </div>
      <p className="mt-4 font-mono text-2xl font-semibold tabular-nums text-slate-950">{value}</p>
      <p className="mt-2 text-xs text-slate-500">{detail}</p>
    </article>
  );
}

function LineagePanel({ manifest }: { manifest: QualityManifest }) {
  const { t } = useTranslation("quality");
  const fmt = useFormat();
  const { lineage } = manifest;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <PanelHeader
        title={t("lineage.title", { agent: lineage.agent })}
        detail={t("lineage.detail", {
          dataset: lineage.dataset.name,
          datasetVersion: lineage.dataset.version,
          evaluatorVersion: lineage.evaluator.version,
        })}
      />
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 type-label">
            <tr>
              <th className="px-5 py-3 font-semibold">{t("lineage.columns.stage")}</th>
              <th className="px-5 py-3 font-semibold">{t("lineage.columns.lineage")}</th>
              <th className="px-5 py-3 font-semibold">{t("lineage.columns.quality")}</th>
              <th className="px-5 py-3 font-semibold">{t("lineage.columns.evidence")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <LineageRow
              stage={t("lineage.baseline.stage")}
              identifier={t("lineage.baseline.identifier", {
                version: lineage.baseline.agentVersion,
              })}
              model={lineage.baseline.model}
              quality={formatPercent(lineage.baseline.aggregatePassRate, fmt)}
              detail={t("lineage.baseline.evaluationRuns", { count: lineage.baseline.runs })}
              state={lineage.baseline.state}
            />
            <LineageRow
              stage={t("lineage.optimizer.stage")}
              identifier={lineage.optimizer.acceptedCandidateId}
              model={lineage.optimizer.strategy}
              quality={formatScore(lineage.optimizer.acceptedScore, fmt)}
              detail={t("lineage.job", { id: lineage.optimizer.jobId })}
              state={lineage.optimizer.state}
            />
            <LineageRow
              stage={t("lineage.rft.stage")}
              identifier={lineage.rft.deployment}
              model="o4-mini RFT"
              quality={formatPercent(lineage.rft.aggregatePassRate, fmt)}
              detail={t("lineage.job", { id: lineage.rft.jobId })}
              state={lineage.rft.state}
            />
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LineageRow({
  stage,
  identifier,
  model,
  quality,
  detail,
  state,
}: {
  stage: string;
  identifier: string;
  model: string;
  quality: string;
  detail: string;
  state: EvidenceState;
}) {
  return (
    <tr className="align-top hover:bg-slate-50/70">
      <td className="px-5 py-4">
        <p className="font-semibold text-slate-950">{stage}</p>
        <p className="mt-1 text-xs text-slate-500">{model}</p>
      </td>
      <td className="max-w-xs px-5 py-4">
        <p className="truncate font-mono text-xs text-slate-700" title={identifier}>
          {identifier}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500" title={detail}>
          {detail}
        </p>
      </td>
      <td className="px-5 py-4 font-mono font-semibold tabular-nums text-slate-950">
        {quality}
      </td>
      <td className="px-5 py-4">
        <StateBadge state={state} compact />
      </td>
    </tr>
  );
}

function OperationsPanel({
  operations,
  workflowUrl,
}: {
  operations: Operation[];
  workflowUrl: string | null;
}) {
  const { t } = useTranslation("quality");
  return (
    <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
      <PanelHeader
        title={t("operations.title")}
        detail={t("operations.detail")}
        flush
      />
      <ol className="mt-6">
        {OPERATION_STAGES.map((stage, index) => {
          const stageOperations = operations.filter((operation) => operation.stage === stage.id);
          const isLast = index === OPERATION_STAGES.length - 1;
          return (
            <li
              key={stage.id}
              className={`relative grid grid-cols-[32px_minmax(0,1fr)] gap-x-4 ${isLast ? "" : "pb-6"}`}
            >
              {isLast ? null : (
                <span
                  className="absolute bottom-0 left-4 top-9 w-px bg-slate-200"
                  aria-hidden="true"
                />
              )}
              <span
                className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-50 text-sm font-semibold text-blue-700 ring-1 ring-blue-200"
                aria-hidden="true"
              >
                {stage.step}
              </span>
              <div className="min-w-0 pt-1">
                <h3 className="text-base font-semibold text-slate-950">
                  <span className="sr-only">{t("operations.step", { step: stage.step })} </span>
                  {t(stage.titleKey)}
                </h3>
                <p className="mt-0.5 text-sm leading-6 text-slate-600">{t(stage.detailKey)}</p>
                <ul className="mt-2 divide-y divide-slate-100">
                  {stageOperations.map((operation) => (
                    <OperationRow
                      key={operation.id}
                      operation={operation}
                      workflowUrl={workflowUrl}
                    />
                  ))}
                </ul>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function OperationRow({
  operation,
  workflowUrl,
}: {
  operation: Operation;
  workflowUrl: string | null;
}) {
  const { t } = useTranslation("quality");
  const execution = {
    bounded: {
      label: t("operations.execution.bounded"),
      icon: HiOutlineClock,
    },
    "no-wait": {
      label: t("operations.execution.noWait"),
      icon: HiOutlineQueueList,
    },
    protected: {
      label: t("operations.execution.protected"),
      icon: HiOutlineLockClosed,
    },
  }[operation.execution];
  const ExecutionIcon = execution.icon;

  return (
    <li className="grid gap-x-6 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold text-slate-950">{operation.label}</h4>
          <AvailabilityBadge availability={operation.availability} />
        </div>
        <p className="mt-1 max-w-[70ch] text-sm leading-6 text-slate-600">{operation.purpose}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 type-meta">
          <span className="inline-flex items-center gap-1.5 font-medium text-slate-600">
            <ExecutionIcon className="h-4 w-4 text-blue-600" aria-hidden="true" />
            {execution.label}
          </span>
          <code>{t("operations.workflowOption", { id: operation.id })}</code>
        </p>
        <details className="text-xs text-slate-600">
          <summary className="min-h-11 w-fit cursor-pointer rounded-md py-3 font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
            {t("operations.viewPrerequisites")}
          </summary>
          <ul className="space-y-2 pb-2 leading-5">
            {operation.prerequisites.map((prerequisite) => (
              <li key={prerequisite} className="flex gap-2">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                {prerequisite}
              </li>
            ))}
          </ul>
        </details>
      </div>
      <a
        href={workflowUrl ?? undefined}
        aria-disabled={!workflowUrl}
        aria-label={t("operations.openInActionsAriaLabel", { operation: operation.label })}
        className={[
          "inline-flex min-h-11 items-center gap-2 self-start rounded-md text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500",
          workflowUrl
            ? "text-blue-700 hover:text-blue-900"
            : "cursor-not-allowed text-slate-500",
        ].join(" ")}
        target={workflowUrl ? "_blank" : undefined}
        rel={workflowUrl ? "noreferrer" : undefined}
      >
        {t("operations.openInActions")}
        <HiOutlineArrowTopRightOnSquare className="h-4 w-4" aria-hidden="true" />
      </a>
    </li>
  );
}

function EvidencePanel({ manifest }: { manifest: QualityManifest }) {
  const { t } = useTranslation(["quality", "common"]);
  const fmt = useFormat();
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <PanelHeader
        title={t("evidence.title")}
        detail={t("evidence.reviewed", { date: formatDate(manifest.reviewedAt, fmt, t) })}
        flush
      />
      <div className="mt-5 space-y-4">
        {manifest.checks.map((check) => (
          <div key={check.name} className="border-b border-slate-100 pb-4 last:border-0 last:pb-0">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-900">{check.name}</h3>
              <StateBadge state={check.state} compact />
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">{check.detail}</p>
          </div>
        ))}
      </div>
      <div className="mt-5 border-t border-slate-100 pt-4">
        <h3 className="type-label">{t("evidence.source")}</h3>
        <code className="mt-1 block break-all text-xs leading-5 text-slate-700">
          {manifest.source.workflow}
        </code>
        <p className="mt-2 text-xs text-slate-500">
          {t("evidence.staleAfter", { date: formatDate(manifest.staleAfter, fmt, t) })}
        </p>
      </div>
      <div className="mt-5 space-y-3 border-t border-slate-100 pt-4">
        {manifest.stateDefinitions.map((definition) => (
          <div key={definition.state} className="flex items-start gap-3">
            <StateBadge state={definition.state} compact />
            <p className="text-xs leading-5 text-slate-600">
              {t(EVIDENCE_STATE_KEYS[definition.state].descriptionKey)}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function LaunchPolicy({
  environment,
  workflowUrl,
  foundryUrl,
}: {
  environment: string;
  workflowUrl: string | null;
  foundryUrl: string | null;
}) {
  const { t } = useTranslation("quality");
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-950">
        <HiOutlineLockClosed className="h-5 w-5 text-blue-700" aria-hidden="true" />
        {t("safety.title")}
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        {t("safety.description")}
      </p>
      <div className="mt-5 border-t border-slate-100 pt-4">
        <h3 className="type-label">{t("safety.liveRftGate")}</h3>
        <code className="mt-1 block break-all text-xs font-semibold text-blue-900">
          {environment}
        </code>
        <p className="mt-2 text-xs leading-5 text-slate-600">
          {t("safety.gateDetail")}
        </p>
      </div>
      <div className="mt-5 grid gap-2">
        <PolicyLink href={workflowUrl}>{t("safety.reviewControls")}</PolicyLink>
        <PolicyLink href={foundryUrl}>{t("safety.inspectFoundry")}</PolicyLink>
      </div>
    </section>
  );
}

function ExternalAction({
  href,
  icon: Icon,
  primary = false,
  children,
}: {
  href: string | null;
  icon: IconType;
  primary?: boolean;
  children: ReactNode;
}) {
  return (
    <a
      href={href ?? undefined}
      aria-disabled={!href}
      target={href ? "_blank" : undefined}
      rel={href ? "noreferrer" : undefined}
      className={[
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition",
        href ? "active:translate-y-px" : "cursor-not-allowed opacity-50",
        primary
          ? "bg-blue-700 text-white shadow-sm hover:bg-blue-800"
          : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
      ].join(" ")}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      {children}
    </a>
  );
}

function PolicyLink({ href, children }: { href: string | null; children: ReactNode }) {
  return (
    <a
      href={href ?? undefined}
      aria-disabled={!href}
      target={href ? "_blank" : undefined}
      rel={href ? "noreferrer" : undefined}
      className={[
        "flex min-h-11 items-center justify-between rounded-lg border border-slate-200 px-3 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500",
        href
          ? "text-slate-700 hover:border-slate-300 hover:bg-slate-50"
          : "cursor-not-allowed text-slate-500",
      ].join(" ")}
    >
      {children}
      <HiOutlineArrowTopRightOnSquare className="h-4 w-4" aria-hidden="true" />
    </a>
  );
}

function StateBadge({ state, compact = false }: { state: EvidenceState; compact?: boolean }) {
  const { t } = useTranslation("quality");
  const styles: Record<EvidenceState, { classes: string; icon: IconType }> = {
    current: {
      classes: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: HiOutlineCheckCircle,
    },
    "reference-only": {
      classes: "border-blue-200 bg-blue-50 text-blue-700",
      icon: HiOutlineCodeBracketSquare,
    },
    stale: {
      classes: "border-amber-200 bg-amber-50 text-amber-700",
      icon: HiOutlineExclamationTriangle,
    },
  };
  const style = styles[state];
  const Icon = style.icon;
  return (
    <span
      className={[
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border font-semibold",
        compact ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-xs",
        style.classes,
      ].join(" ")}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {t(EVIDENCE_STATE_KEYS[state].labelKey)}
    </span>
  );
}

const AVAILABILITY_KEYS = {
  available: "operations.availability.available",
  guarded: "operations.availability.guarded",
  blocked: "operations.availability.blocked",
} as const satisfies Record<OperationAvailability, string>;

function AvailabilityBadge({ availability }: { availability: OperationAvailability }) {
  const { t } = useTranslation("quality");
  const classes: Record<OperationAvailability, string> = {
    available: "border-emerald-200 bg-emerald-50 text-emerald-700",
    guarded: "border-blue-200 bg-blue-50 text-blue-700",
    blocked: "border-slate-200 bg-slate-100 text-slate-600",
  };
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${classes[availability]}`}
    >
      {t(AVAILABILITY_KEYS[availability])}
    </span>
  );
}

function PanelHeader({
  title,
  detail,
  flush = false,
}: {
  title: string;
  detail: string;
  flush?: boolean;
}) {
  return (
    <div className={flush ? "" : "p-5 lg:p-6"}>
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      <p className="mt-1 max-w-[70ch] text-sm leading-6 text-slate-600">{detail}</p>
    </div>
  );
}

function QualitySkeleton() {
  const { t } = useTranslation("quality");
  return (
    <div aria-label={t("loading")} className="animate-pulse space-y-6">
      <div className="h-64 rounded-xl border border-slate-200 bg-white" />
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((item) => (
          <div key={item} className="h-36 rounded-xl border border-slate-200 bg-white" />
        ))}
      </div>
      <div className="h-96 rounded-xl border border-slate-200 bg-white" />
    </div>
  );
}

function QualityError({ message }: { message: string }) {
  const { t } = useTranslation("quality");
  return (
    <section className="rounded-xl border border-rose-200 bg-white p-8 text-center shadow-sm">
      <HiOutlineExclamationTriangle className="mx-auto h-8 w-8 text-rose-600" />
      <h1 className="mt-4 text-lg font-semibold text-slate-950">{t("errors.title")}</h1>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-600">{message}</p>
      <p className="mt-3 text-xs text-slate-500">
        {t("errors.hint")}
      </p>
    </section>
  );
}
