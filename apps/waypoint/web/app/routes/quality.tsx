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
import { fetchDrilldownConfig, type DrilldownConfig } from "../../lib/waypointConfig";
import { AppHeader } from "../components/AppHeader";
import { RequireAuth } from "../components/RequireAuth";

export const meta: MetaFunction = () => [
  { title: "Quality & optimization - Waypoint" },
  {
    name: "description",
    content: "Quality lineage, readiness, and guarded GitHub operations for Waypoint agents",
  },
];

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

const OPERATION_STAGES: Array<{
  id: OperationStage;
  step: number;
  title: string;
  detail: string;
  icon: IconType;
}> = [
  {
    id: "run",
    step: 1,
    title: "Run assurance",
    detail: "Generate live, governed evidence from an invoice.",
    icon: HiOutlineBolt,
  },
  {
    id: "inspect",
    step: 2,
    title: "Inspect the run",
    detail: "Correlate the result with sanitized operational traces.",
    icon: HiOutlineCodeBracketSquare,
  },
  {
    id: "measure",
    step: 3,
    title: "Measure quality",
    detail: "Evaluate the current agent and verify its quality assets.",
    icon: HiOutlineBeaker,
  },
  {
    id: "improve",
    step: 4,
    title: "Improve the agent",
    detail: "Search and prepare candidates without applying them.",
    icon: HiOutlineArrowTrendingUp,
  },
  {
    id: "release",
    step: 5,
    title: "Release with approval",
    detail: "Keep live training behind review, spend, and command gates.",
    icon: HiOutlineLockClosed,
  },
];

function safeHttpsUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString().replace(/\/$/, "") : null;
  } catch {
    return null;
  }
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function effectiveState(manifest: QualityManifest): EvidenceState {
  if (manifest.evidenceState !== "current") return manifest.evidenceState;
  const staleAt = new Date(manifest.staleAfter).getTime();
  return Number.isFinite(staleAt) && staleAt < Date.now() ? "stale" : "current";
}

export default function Quality() {
  const { qualityOperations } = useOutletContext<QualityOutletContext>();
  const [manifest, setManifest] = useState<QualityManifest | null>(null);
  const [drilldown, setDrilldown] = useState<DrilldownConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetch(MANIFEST_URL, { signal: controller.signal }).then(async (response) => {
        if (!response.ok) {
          throw new Error(`Evidence manifest returned ${response.status}`);
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
          setError(reason instanceof Error ? reason.message : "Quality evidence is unavailable");
        }
      },
    );
    return () => controller.abort();
  }, []);

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
        <main id="main-content" className="mx-auto max-w-[1400px] px-4 py-6 lg:px-8">
          {error ? <QualityError message={error} /> : null}
          {!manifest && !error ? <QualitySkeleton /> : null}
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
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm lg:p-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={state} />
            <span className="text-xs font-medium text-slate-500">
              Schema v{manifest.schemaVersion}
            </span>
          </div>
          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">
            Quality operations
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
            Quality &amp; optimization
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            Follow one controlled loop: generate invoice evidence, inspect its trace, measure the
            agent, improve it, and require approval before release. GitHub Actions and Foundry own
            the work; this browser only explains the path and links to it.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <ExternalAction href={workflowUrl} icon={HiOutlineBolt} primary>
            Open agent quality workflow
          </ExternalAction>
          <ExternalAction href={foundryUrl} icon={HiOutlineArrowTopRightOnSquare}>
            Open Foundry project
          </ExternalAction>
        </div>
      </div>
    </section>
  );
}

function GovernanceStrip({ environment }: { environment: string }) {
  return (
    <section
      aria-label="Control plane boundary"
      className="mt-4 grid gap-4 rounded-xl border border-blue-200 bg-blue-50 p-4 md:grid-cols-[auto_1fr_auto] md:items-center"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-white text-blue-700 shadow-sm">
        <HiOutlineShieldCheck className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <h2 className="text-sm font-semibold text-blue-950">Why these operations are guarded</h2>
        <p className="mt-1 text-sm leading-6 text-blue-800">
          Every cloud action runs in GitHub Actions so inputs, credentials, evidence, and
          approvals stay auditable. This page never runs cloud commands in your browser.
        </p>
      </div>
      <code className="w-fit rounded-md border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-800">
        {environment}
      </code>
    </section>
  );
}

function MetricGrid({ manifest }: { manifest: QualityManifest }) {
  const optimizerLift =
    manifest.lineage.optimizer.acceptedScore - manifest.lineage.optimizer.baselineScore;
  return (
    <section className="mt-6 grid gap-4 md:grid-cols-3" aria-label="Reference quality outcomes">
      <MetricCard
        icon={HiOutlineArrowTrendingUp}
        label="Estimated inference reduction"
        value={formatPercent(manifest.lineage.rft.estimatedCostReduction)}
        detail="Reference comparison per evidence request"
      />
      <MetricCard
        icon={HiOutlineBeaker}
        label="RFT aggregate pass rate"
        value={formatPercent(manifest.lineage.rft.aggregatePassRate)}
        detail={`${manifest.lineage.dataset.samplesPerRun} samples × ${manifest.lineage.baseline.runs} runs`}
      />
      <MetricCard
        icon={HiOutlineArrowTrendingDown}
        label="Optimizer score lift"
        value={`+${optimizerLift.toFixed(4)}`}
        detail={`${manifest.lineage.optimizer.baselineScore.toFixed(4)} → ${manifest.lineage.optimizer.acceptedScore.toFixed(4)}`}
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
  const { lineage } = manifest;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <PanelHeader
        eyebrow="Measured lineage"
        title={`${lineage.agent} quality path`}
        detail={`${lineage.dataset.name} v${lineage.dataset.version} · evaluator v${lineage.evaluator.version}`}
      />
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-y border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-3 font-semibold">Stage</th>
              <th className="px-5 py-3 font-semibold">Lineage</th>
              <th className="px-5 py-3 font-semibold">Quality</th>
              <th className="px-5 py-3 font-semibold">Evidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <LineageRow
              stage="Hosted baseline"
              identifier={`agent v${lineage.baseline.agentVersion}`}
              model={lineage.baseline.model}
              quality={formatPercent(lineage.baseline.aggregatePassRate)}
              detail={`${lineage.baseline.runs} evaluation runs`}
              state={lineage.baseline.state}
            />
            <LineageRow
              stage="Agent Optimizer"
              identifier={lineage.optimizer.acceptedCandidateId}
              model={lineage.optimizer.strategy}
              quality={lineage.optimizer.acceptedScore.toFixed(4)}
              detail={`Job ${lineage.optimizer.jobId}`}
              state={lineage.optimizer.state}
            />
            <LineageRow
              stage="RFT cost transfer"
              identifier={lineage.rft.deployment}
              model="o4-mini RFT"
              quality={formatPercent(lineage.rft.aggregatePassRate)}
              detail={`Job ${lineage.rft.jobId}`}
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
  return (
    <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:p-6">
      <PanelHeader
        eyebrow="Controlled quality loop"
        title="From invoice evidence to a safe release"
        detail="Use the steps in order for a new quality cycle, or open the operation you need for an existing run."
        flush
      />
      <ol className="mt-6 space-y-4">
        {OPERATION_STAGES.map((stage) => {
          const stageOperations = operations.filter((operation) => operation.stage === stage.id);
          const StageIcon = stage.icon;
          return (
            <li
              key={stage.id}
              className="grid gap-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 md:grid-cols-[48px_minmax(0,1fr)] md:p-5"
            >
              <div
                className="flex h-12 w-12 items-center justify-center rounded-full border border-blue-200 bg-white text-blue-700 shadow-sm"
                aria-hidden="true"
              >
                <span className="text-sm font-bold">{stage.step}</span>
              </div>
              <div>
                <div className="flex items-start gap-3">
                  <StageIcon className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
                  <div>
                    <h3 className="text-base font-semibold text-slate-950">{stage.title}</h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{stage.detail}</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  {stageOperations.map((operation) => (
                    <OperationCard
                      key={operation.id}
                      operation={operation}
                      workflowUrl={workflowUrl}
                    />
                  ))}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function OperationCard({
  operation,
  workflowUrl,
}: {
  operation: Operation;
  workflowUrl: string | null;
}) {
  const execution = {
    bounded: {
      label: "Completes in Actions",
      icon: HiOutlineClock,
    },
    "no-wait": {
      label: "Starts an asynchronous job",
      icon: HiOutlineQueueList,
    },
    protected: {
      label: "Requires protected approval",
      icon: HiOutlineLockClosed,
    },
  }[operation.execution];
  const ExecutionIcon = execution.icon;

  return (
    <article className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-950">{operation.label}</h4>
          <p className="mt-1 text-xs leading-5 text-slate-600">{operation.purpose}</p>
        </div>
        <AvailabilityBadge availability={operation.availability} />
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs font-medium text-slate-600">
        <ExecutionIcon className="h-4 w-4 text-blue-600" aria-hidden="true" />
        {execution.label}
      </div>
      <details className="mt-3 text-xs text-slate-600">
        <summary className="min-h-11 cursor-pointer rounded-md py-3 font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
          View prerequisites
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
      <div className="mt-auto border-t border-slate-100 pt-3">
        <code className="block text-[11px] text-slate-500">Workflow option: {operation.id}</code>
        <a
          href={workflowUrl ?? undefined}
          aria-disabled={!workflowUrl}
          className={[
            "mt-2 inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500",
            workflowUrl
              ? "text-blue-700 hover:text-blue-900"
              : "cursor-not-allowed text-slate-400",
          ].join(" ")}
          target={workflowUrl ? "_blank" : undefined}
          rel={workflowUrl ? "noreferrer" : undefined}
        >
          Open in GitHub Actions
          <HiOutlineArrowTopRightOnSquare className="h-4 w-4" aria-hidden="true" />
        </a>
      </div>
    </article>
  );
}

function EvidencePanel({ manifest }: { manifest: QualityManifest }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <PanelHeader
        eyebrow="Evidence health"
        title="Freshness & source"
        detail={`Reviewed ${formatDate(manifest.reviewedAt)}`}
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
      <div className="mt-5 rounded-lg bg-slate-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Source</p>
        <code className="mt-2 block break-all text-xs leading-5 text-slate-700">
          {manifest.source.workflow}
        </code>
        <p className="mt-2 text-xs text-slate-500">
          Stale after {formatDate(manifest.staleAfter)}
        </p>
      </div>
      <div className="mt-5 space-y-3">
        {manifest.stateDefinitions.map((definition) => (
          <div key={definition.state} className="flex items-start gap-3">
            <StateBadge state={definition.state} compact />
            <p className="text-xs leading-5 text-slate-600">{definition.description}</p>
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
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
        <HiOutlineLockClosed className="h-5 w-5" aria-hidden="true" />
      </span>
      <h2 className="mt-4 text-lg font-semibold text-slate-950">Safety boundary</h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        The workflow can run, inspect, measure, and prepare. It never auto-applies an optimizer
        candidate, promotes a model, or deploys an agent.
      </p>
      <div className="mt-5 rounded-lg border border-blue-100 bg-blue-50 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
          Live RFT gate
        </p>
        <code className="mt-2 block break-all text-xs font-semibold text-blue-900">
          {environment}
        </code>
        <p className="mt-2 text-xs leading-5 text-blue-900">
          Required reviewers and explicit spend acknowledgement are prerequisites. Submission
          remains blocked until a committed first-class command exists.
        </p>
      </div>
      <div className="mt-5 grid gap-2">
        <PolicyLink href={workflowUrl}>Review workflow controls</PolicyLink>
        <PolicyLink href={foundryUrl}>Inspect current Foundry status</PolicyLink>
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
          ? "bg-blue-600 text-white shadow-sm hover:bg-blue-700"
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
          : "cursor-not-allowed text-slate-400",
      ].join(" ")}
    >
      {children}
      <HiOutlineArrowTopRightOnSquare className="h-4 w-4" aria-hidden="true" />
    </a>
  );
}

function StateBadge({ state, compact = false }: { state: EvidenceState; compact?: boolean }) {
  const styles: Record<EvidenceState, { label: string; classes: string; icon: IconType }> = {
    current: {
      label: "Current",
      classes: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: HiOutlineCheckCircle,
    },
    "reference-only": {
      label: "Reference only",
      classes: "border-blue-200 bg-blue-50 text-blue-700",
      icon: HiOutlineCodeBracketSquare,
    },
    stale: {
      label: "Stale",
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
        compact ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        style.classes,
      ].join(" ")}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {style.label}
    </span>
  );
}

function AvailabilityBadge({ availability }: { availability: OperationAvailability }) {
  const classes: Record<OperationAvailability, string> = {
    available: "border-emerald-200 bg-emerald-50 text-emerald-700",
    guarded: "border-blue-200 bg-blue-50 text-blue-700",
    blocked: "border-slate-200 bg-slate-100 text-slate-600",
  };
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${classes[availability]}`}
    >
      {availability}
    </span>
  );
}

function PanelHeader({
  eyebrow,
  title,
  detail,
  flush = false,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  flush?: boolean;
}) {
  return (
    <div className={flush ? "" : "p-5 lg:p-6"}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">{eyebrow}</p>
      <h2 className="mt-2 text-lg font-semibold text-slate-950">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-slate-600">{detail}</p>
    </div>
  );
}

function QualitySkeleton() {
  return (
    <div aria-label="Loading quality evidence" className="animate-pulse space-y-6">
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
  return (
    <section className="rounded-xl border border-rose-200 bg-white p-8 text-center shadow-sm">
      <HiOutlineExclamationTriangle className="mx-auto h-8 w-8 text-rose-600" />
      <h1 className="mt-4 text-lg font-semibold text-slate-950">Quality evidence unavailable</h1>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-600">{message}</p>
      <p className="mt-3 text-xs text-slate-500">
        Verify that the versioned public evidence manifest is included in this deployment.
      </p>
    </section>
  );
}
