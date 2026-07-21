from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .calibration import calibrate_grader
from .contract_policy import (
    build_contract_policy_contract_expansion,
    build_contract_policy_datasets,
)
from .doctor import run_doctor
from .eval import build_eval_plan
from .eval_assets import validate_eval_config
from .forge import inspect_forge
from .foundry_eval import export_eval_output_items
from .gates import evaluate_gates
from .lineage import (
    REVIEW_STATUSES,
    VERIFY_STATUSES,
    append_snapshot,
    build_snapshot,
    default_ledger_path,
    find_snapshot,
    latest_snapshot,
    lineage_report,
    verify_snapshot,
)
from .manifest import build_manifest
from .optimizer import build_optimizer_plan
from .rft import build_rft_plan, package_rft_assets, read_rft_status
from .rle import build_rle_plan
from .telemetry import build_telemetry_backfill_plan


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 2

    try:
        result = args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result is None:
        return 0

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caliber",
        description="Fine-tuning support tools for Forge agents.",
    )
    sub = parser.add_subparsers(dest="command")

    manifest = sub.add_parser("manifest", help="Print Caliber's source-of-truth paths.")
    manifest.add_argument("--json", action="store_true", help="Print JSON.")
    manifest.set_defaults(handler=lambda _args: build_manifest())

    doctor = sub.add_parser("doctor", help="Validate local Caliber setup.")
    doctor.add_argument("--json", action="store_true", help="Print JSON.")
    doctor.set_defaults(handler=lambda _args: run_doctor())

    forge = sub.add_parser("inspect-forge", help="Summarize a Forge checkout without editing it.")
    forge.add_argument("--path", required=True, type=Path, help="Path to a local Forge checkout.")
    forge.add_argument("--json", action="store_true", help="Print JSON.")
    forge.set_defaults(handler=lambda args: inspect_forge(args.path))

    datasets = sub.add_parser("datasets", help="Dataset generation helpers.")
    datasets_sub = datasets.add_subparsers(dest="datasets_command")
    contract_policy = datasets_sub.add_parser(
        "contract-policy",
        help="Build contract-policy RFT datasets from Ledgerfield sources.",
    )
    contract_policy_sub = contract_policy.add_subparsers(dest="contract_policy_command")
    contract_policy_build = contract_policy_sub.add_parser(
        "build",
        help="Generate train/validation/eval JSONL files.",
    )
    contract_policy_build.add_argument(
        "--ledgerfield-path",
        required=True,
        type=Path,
        help="Path to a read-only Ledgerfield checkout or worktree.",
    )
    contract_policy_build.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for generated JSONL files. Defaults to datasets\\<agent>.",
    )
    contract_policy_build.add_argument(
        "--agent",
        default="contract-policy-expert",
        help="Caliber candidate and expected output agent identity.",
    )
    contract_policy_build.add_argument(
        "--forge-agent",
        default="",
        help="Optional Forge runtime agent name when it differs from --agent.",
    )
    contract_policy_build.add_argument(
        "--source-ref",
        default="",
        help="Optional Ledgerfield source ref override for dataset lineage.",
    )
    contract_policy_build.add_argument(
        "--variants-per-scenario",
        type=int,
        default=1,
        help="Number of deterministic prompt variants to generate for each Ledgerfield scenario.",
    )
    contract_policy_build.add_argument("--json", action="store_true", help="Print JSON.")
    contract_policy_build.set_defaults(
        handler=lambda args: build_contract_policy_datasets(
            ledgerfield_path=args.ledgerfield_path,
            out_dir=args.out_dir or Path("datasets") / args.agent,
            source_ref=args.source_ref or None,
            variants_per_scenario=args.variants_per_scenario,
            agent=args.agent,
            forge_agent=args.forge_agent or None,
        )
    )
    contract_policy_expand = contract_policy_sub.add_parser(
        "expand-contracts",
        help="Generate additional clause-grounded rows from Ledgerfield contract Markdown.",
    )
    contract_policy_expand.add_argument(
        "--ledgerfield-path",
        required=True,
        type=Path,
        help="Path to a read-only Ledgerfield checkout or worktree.",
    )
    contract_policy_expand.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for generated JSONL files. Defaults to datasets\\<agent>.",
    )
    contract_policy_expand.add_argument(
        "--agent",
        default="contract-policy-expert",
        help="Caliber candidate and expected output agent identity.",
    )
    contract_policy_expand.add_argument(
        "--forge-agent",
        default="",
        help="Optional Forge runtime agent name when it differs from --agent.",
    )
    contract_policy_expand.add_argument(
        "--source-ref",
        default="",
        help="Optional Ledgerfield source ref override for dataset lineage.",
    )
    contract_policy_expand.add_argument(
        "--variants-per-clause",
        type=int,
        default=3,
        help="Number of deterministic prompt variants to generate per contract clause.",
    )
    contract_policy_expand.add_argument("--json", action="store_true", help="Print JSON.")
    contract_policy_expand.set_defaults(
        handler=lambda args: build_contract_policy_contract_expansion(
            ledgerfield_path=args.ledgerfield_path,
            out_dir=args.out_dir or Path("datasets") / args.agent,
            source_ref=args.source_ref or None,
            variants_per_clause=args.variants_per_clause,
            agent=args.agent,
            forge_agent=args.forge_agent or None,
        )
    )

    eval_parser = sub.add_parser("eval", help="Eval workflow helpers.")
    eval_sub = eval_parser.add_subparsers(dest="eval_command")
    eval_plan = eval_sub.add_parser("plan", help="Validate dataset and grader for an eval run.")
    eval_plan.add_argument("--dataset", required=True, type=Path, help="Eval JSONL file.")
    eval_plan.add_argument("--grader", required=True, type=Path, help="Python grader file.")
    eval_plan.add_argument("--model", default="o4-mini", help="Model deployment name.")
    eval_plan.add_argument("--limit", type=int, default=0, help="Optional scenario limit.")
    eval_plan.add_argument("--json", action="store_true", help="Print JSON.")
    eval_plan.set_defaults(
        handler=lambda args: build_eval_plan(
            dataset_path=args.dataset,
            grader_path=args.grader,
            model=args.model,
            limit=args.limit,
        )
    )
    eval_export = eval_sub.add_parser(
        "export-output-items",
        help="Export Foundry eval run output-items for calibration.",
    )
    eval_export.add_argument("--project-endpoint", required=True, help="Foundry project endpoint.")
    eval_export.add_argument("--eval-id", required=True, help="Foundry eval ID.")
    eval_export.add_argument("--run-id", required=True, help="Foundry eval run ID.")
    eval_export.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSONL path.",
    )
    eval_export.add_argument("--limit", type=int, default=100, help="Maximum output items.")
    eval_export.add_argument("--json", action="store_true", help="Print JSON.")
    eval_export.set_defaults(
        handler=lambda args: export_eval_output_items(
            project_endpoint=args.project_endpoint,
            eval_id=args.eval_id,
            run_id=args.run_id,
            out_path=args.out,
            limit=args.limit,
        )
    )

    eval_validate = eval_sub.add_parser(
        "validate-assets",
        help="Validate an eval.yaml plus its referenced dataset and rubric files.",
    )
    eval_validate.add_argument(
        "--eval-config",
        required=True,
        type=Path,
        help="Path to an azd ai agent eval.yaml config.",
    )
    eval_validate.add_argument("--json", action="store_true", help="Print JSON.")
    eval_validate.set_defaults(
        handler=lambda args: validate_eval_config(args.eval_config)
    )

    optimizer = sub.add_parser("optimizer", help="Agent Optimizer planning helpers.")
    optimizer_sub = optimizer.add_subparsers(dest="optimizer_command")
    optimizer_plan = optimizer_sub.add_parser(
        "plan",
        help="Inspect Forge optimizer readiness and prompt-agent repair steps.",
    )
    optimizer_plan.add_argument(
        "--forge-path",
        required=True,
        type=Path,
        help="Path to a read-only Forge checkout.",
    )
    optimizer_plan.add_argument(
        "--agent",
        default="contract-policy-expert",
        help="Forge agent name to inspect.",
    )
    optimizer_plan.add_argument(
        "--dataset",
        type=Path,
        help="Optional eval dataset that will drive optimization.",
    )
    optimizer_plan.add_argument(
        "--eval-config",
        type=Path,
        help="Optional reviewed eval.yaml path for Agent Optimizer.",
    )
    optimizer_plan.add_argument("--json", action="store_true", help="Print JSON.")
    optimizer_plan.set_defaults(
        handler=lambda args: build_optimizer_plan(
            forge_path=args.forge_path,
            agent=args.agent,
            dataset_path=args.dataset,
            eval_config_path=args.eval_config,
        )
    )

    rft = sub.add_parser("rft", help="Foundry fine-tuning workflow helpers.")
    rft_sub = rft.add_subparsers(dest="rft_command")

    plan = rft_sub.add_parser("plan", help="Validate inputs and print an RFT submission plan.")
    plan.add_argument("--train", required=True, type=Path, help="Training JSONL file.")
    plan.add_argument("--validation", required=True, type=Path, help="Validation JSONL file.")
    plan.add_argument("--grader", required=True, type=Path, help="Python grader file.")
    plan.add_argument("--base-model", default="o4-mini", help="Base model deployment name.")
    plan.add_argument("--suffix", default="", help="Optional fine-tune suffix.")
    plan.add_argument(
        "--project-endpoint",
        default="",
        help="Optional Foundry project endpoint override.",
    )
    plan.add_argument("--json", action="store_true", help="Print JSON.")
    plan.set_defaults(
        handler=lambda args: build_rft_plan(
            train_path=args.train,
            validation_path=args.validation,
            grader_path=args.grader,
            base_model=args.base_model,
            suffix=args.suffix or None,
            project_endpoint=args.project_endpoint or None,
        )
    )

    package = rft_sub.add_parser(
        "package",
        help="Create RFT-ready JSONL, grader, and dry-run job spec under ignored runs storage.",
    )
    package.add_argument("--train", required=True, type=Path, help="Training JSONL file.")
    package.add_argument("--validation", required=True, type=Path, help="Validation JSONL file.")
    package.add_argument("--grader", required=True, type=Path, help="Python grader file.")
    package.add_argument("--agent", default="contract-policy-expert", help="Target agent name.")
    package.add_argument(
        "--base-model",
        default="o4-mini",
        help="Cheap base model deployment name.",
    )
    package.add_argument("--suffix", default="", help="Optional fine-tune suffix.")
    package.add_argument(
        "--out-dir",
        type=Path,
        default=Path("runs") / "rft" / "contract-policy-expert",
        help="Output directory for local RFT packaging artifacts.",
    )
    package.add_argument(
        "--optimizer-job-id",
        default="",
        help="Optional optimizer job ID that must complete before live RFT submission.",
    )
    package.add_argument(
        "--optimizer-candidate-id",
        default="",
        help="Optional optimizer candidate ID used as the gold-standard behavior target.",
    )
    package.add_argument("--json", action="store_true", help="Print JSON.")
    package.set_defaults(
        handler=lambda args: package_rft_assets(
            train_path=args.train,
            validation_path=args.validation,
            grader_path=args.grader,
            out_dir=args.out_dir,
            agent=args.agent,
            base_model=args.base_model,
            suffix=args.suffix or None,
            optimizer_job_id=args.optimizer_job_id or None,
            optimizer_candidate_id=args.optimizer_candidate_id or None,
        )
    )

    status = rft_sub.add_parser("status", help="Read local RFT job metadata if present.")
    status.add_argument(
        "--state",
        type=Path,
        default=Path(".rft_job.json"),
        help="State file path.",
    )
    status.add_argument("--json", action="store_true", help="Print JSON.")
    status.set_defaults(handler=lambda args: read_rft_status(args.state))

    grader = sub.add_parser("grader", help="Grader calibration helpers.")
    grader_sub = grader.add_subparsers(dest="grader_command")
    calibrate = grader_sub.add_parser(
        "calibrate",
        help="Score captured outputs and report pass rates across thresholds.",
    )
    calibrate.add_argument("--dataset", required=True, type=Path, help="Dataset JSONL file.")
    calibrate.add_argument(
        "--outputs",
        required=True,
        type=Path,
        help="Output-items or raw invocation JSONL file.",
    )
    calibrate.add_argument("--grader", required=True, type=Path, help="Python grader file.")
    calibrate.add_argument(
        "--threshold",
        dest="thresholds",
        action="append",
        type=float,
        help="Threshold to test; repeat for multiple values.",
    )
    calibrate.add_argument("--json", action="store_true", help="Print JSON.")
    calibrate.set_defaults(
        handler=lambda args: calibrate_grader(
            dataset_path=args.dataset,
            outputs_path=args.outputs,
            grader_path=args.grader,
            thresholds=args.thresholds,
        )
    )

    rle = sub.add_parser("rle", help="Reinforcement learning environment helpers.")
    rle_sub = rle.add_subparsers(dest="rle_command")

    rle_plan = rle_sub.add_parser(
        "plan",
        help="Validate an offline Deploy -> Observe -> Learn environment plan.",
    )
    rle_plan.add_argument("--agent", required=True, help="Target agent name.")
    rle_plan.add_argument("--environment", required=True, help="Environment name, e.g. dev.")
    rle_plan.add_argument("--train", required=True, type=Path, help="Training JSONL file.")
    rle_plan.add_argument("--validation", required=True, type=Path, help="Validation JSONL file.")
    rle_plan.add_argument("--eval", required=True, type=Path, help="Held-out eval JSONL file.")
    rle_plan.add_argument("--grader", required=True, type=Path, help="Python reward grader file.")
    rle_plan.add_argument("--base-model", default="o4-mini", help="Base model deployment name.")
    rle_plan.add_argument(
        "--frontier-model",
        default="gpt-5.5",
        help="Frontier model deployment name for before/after comparison.",
    )
    rle_plan.add_argument(
        "--fine-tuned-model",
        default="o4-mini-finetuned",
        help="Fine-tuned model deployment name.",
    )
    rle_plan.add_argument(
        "--project-endpoint",
        default="",
        help="Optional Foundry project endpoint override.",
    )
    rle_plan.add_argument(
        "--tool-url",
        default="",
        help="Optional tool server URL for tool-augmented RFT.",
    )
    rle_plan.add_argument(
        "--plain-reinforcement",
        action="store_true",
        help="Plan reward-only RFT without training-time tools.",
    )
    rle_plan.add_argument("--json", action="store_true", help="Print JSON.")
    rle_plan.set_defaults(
        handler=lambda args: build_rle_plan(
            agent=args.agent,
            environment=args.environment,
            train_path=args.train,
            validation_path=args.validation,
            eval_path=args.eval,
            grader_path=args.grader,
            base_model=args.base_model,
            frontier_model=args.frontier_model,
            fine_tuned_model=args.fine_tuned_model,
            project_endpoint=args.project_endpoint or None,
            tool_url=args.tool_url or None,
            plain_reinforcement=args.plain_reinforcement,
        )
    )

    telemetry = sub.add_parser(
        "telemetry",
        help="Telemetry simulation and backfill helpers.",
    )
    telemetry_sub = telemetry.add_subparsers(dest="telemetry_command")
    backfill_plan = telemetry_sub.add_parser(
        "backfill-plan",
        help="Plan the 48-hour App Insights / Log Analytics telemetry backfill.",
    )
    backfill_plan.add_argument("--hours", type=int, default=48, help="Backfill window in hours.")
    backfill_plan.add_argument("--environment", default="demo", help="Environment label.")
    backfill_plan.add_argument(
        "--app-insights-resource-id",
        default="",
        help="Optional App Insights resource ID override.",
    )
    backfill_plan.add_argument(
        "--log-analytics-workspace-id",
        default="",
        help="Optional Log Analytics workspace ID override.",
    )
    backfill_plan.add_argument(
        "--stream",
        dest="streams",
        action="append",
        help="Telemetry stream to include; repeat for multiple streams.",
    )
    backfill_plan.add_argument("--json", action="store_true", help="Print JSON.")
    backfill_plan.set_defaults(
        handler=lambda args: build_telemetry_backfill_plan(
            hours=args.hours,
            environment=args.environment,
            app_insights_resource_id=args.app_insights_resource_id or None,
            log_analytics_workspace_id=args.log_analytics_workspace_id or None,
            streams=args.streams,
        )
    )

    lineage = sub.add_parser(
        "lineage",
        help="Quality-evidence lineage: immutable, hash-anchored snapshots for FT/eval gates.",
    )
    lineage_sub = lineage.add_subparsers(dest="lineage_command")

    lineage_snapshot = lineage_sub.add_parser(
        "snapshot",
        help="Compute and append an immutable lineage snapshot. Never overwrites.",
    )
    lineage_snapshot.add_argument("--agent", required=True, help="Agent name.")
    lineage_snapshot.add_argument(
        "--operation-id",
        required=True,
        help="Correlation id for the operation this snapshot documents (eval run, optimizer "
        "job, RFT job, etc.).",
    )
    lineage_snapshot.add_argument(
        "--operation-kind",
        required=True,
        help="Kind of operation, e.g. eval, agent_optimizer, rft, manual.",
    )
    lineage_snapshot.add_argument(
        "--review-status",
        default="draft",
        choices=sorted(REVIEW_STATUSES),
        help="Human review status for this snapshot.",
    )
    lineage_snapshot.add_argument(
        "--environment",
        default="local",
        help="Non-secret environment label, e.g. local, dev, demo.",
    )
    lineage_snapshot.add_argument("--prompt-config", type=Path, help="Agent prompt/config file.")
    lineage_snapshot.add_argument("--dataset", type=Path, help="Dataset JSONL file.")
    lineage_snapshot.add_argument(
        "--rubric-eval-config", type=Path, help="Rubric/eval config file, e.g. eval.yaml."
    )
    lineage_snapshot.add_argument("--grader", type=Path, help="Python grader file.")
    lineage_snapshot.add_argument("--model-deployment", default="", help="Model deployment name.")
    lineage_snapshot.add_argument("--base-model", default="", help="Base model name.")
    lineage_snapshot.add_argument(
        "--source-path",
        type=Path,
        default=None,
        help="Path used to resolve the source commit SHA. Defaults to the current directory.",
    )
    lineage_snapshot.add_argument(
        "--reference-only",
        action="store_true",
        help="Mark this snapshot as a historical reference whose sources cannot be re-hashed.",
    )
    lineage_snapshot.add_argument("--notes", default="", help="Free-form notes.")
    lineage_snapshot.add_argument(
        "--metric",
        dest="metrics",
        action="append",
        default=[],
        help="key=value metric to attach; repeat for multiple values.",
    )
    lineage_snapshot.add_argument(
        "--approval",
        dest="approvals",
        action="append",
        default=[],
        help="approver:role approval to attach; repeat for multiple values.",
    )
    lineage_snapshot.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Ledger JSONL path. Defaults to runs/lineage/<agent>/manifest.jsonl.",
    )
    lineage_snapshot.add_argument("--json", action="store_true", help="Print JSON.")
    lineage_snapshot.set_defaults(handler=_handle_lineage_snapshot)

    lineage_verify = lineage_sub.add_parser(
        "verify",
        help="Recompute hashes from current sources and classify current/stale/reference-only.",
    )
    lineage_verify.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Ledger JSONL path. Required unless --agent is given with the default path.",
    )
    lineage_verify.add_argument(
        "--agent", default="", help="Agent name, for the default ledger path."
    )
    lineage_verify.add_argument(
        "--snapshot-id",
        default="",
        help="Snapshot id to verify. Defaults to the latest snapshot for --agent.",
    )
    lineage_verify.add_argument(
        "--prompt-config", type=Path, help="Current agent prompt/config file."
    )
    lineage_verify.add_argument("--dataset", type=Path, help="Current dataset JSONL file.")
    lineage_verify.add_argument(
        "--rubric-eval-config", type=Path, help="Current rubric/eval config file."
    )
    lineage_verify.add_argument("--grader", type=Path, help="Current Python grader file.")
    lineage_verify.add_argument(
        "--model-deployment", default="", help="Current model deployment name."
    )
    lineage_verify.add_argument("--json", action="store_true", help="Print JSON.")
    lineage_verify.set_defaults(handler=_handle_lineage_verify)

    lineage_report = lineage_sub.add_parser(
        "report",
        help="Report current/stale/reference-only status per agent across the ledger.",
    )
    lineage_report.add_argument(
        "--ledger", type=Path, default=None, help="Ledger JSONL path, for a single agent's ledger."
    )
    lineage_report.add_argument("--agent", default="", help="Filter to one agent.")
    lineage_report.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Committed reference-lineage JSON file to include as reference_only evidence.",
    )
    lineage_report.add_argument("--json", action="store_true", help="Print JSON.")
    lineage_report.set_defaults(handler=_handle_lineage_report)

    gates = sub.add_parser(
        "gates",
        help="Fail-closed fine-tuning/eval promotion gates. Never applies/deploys/promotes.",
    )
    gates_sub = gates.add_subparsers(dest="gates_command")
    gates_check = gates_sub.add_parser(
        "check",
        help="Evaluate whether a named operation would be allowed. Read-only; enforces nothing.",
    )
    gates_check.add_argument(
        "--operation",
        required=True,
        help="Operation label, e.g. optimizer_apply, rft_submit, candidate_promote.",
    )
    gates_check.add_argument("--review-approved", action="store_true")
    gates_check.add_argument(
        "--lineage-status",
        default="unverifiable",
        choices=sorted(VERIFY_STATUSES),
        help="Result of a prior `caliber lineage verify` run.",
    )
    gates_check.add_argument("--model-ready", action="store_true")
    gates_check.add_argument("--quota-ready", action="store_true")
    gates_check.add_argument("--spend-confirmed", action="store_true")
    gates_check.add_argument(
        "--protected-approver", default="", help="Name of a protected approver."
    )
    gates_check.add_argument(
        "--required-approver-role",
        default="",
        help="Approver role required for protected_approval, e.g. eng-lead.",
    )
    gates_check.add_argument(
        "--approval",
        dest="approvals",
        action="append",
        default=[],
        help="approver:role approval to consider; repeat for multiple values.",
    )
    gates_check.add_argument("--json", action="store_true", help="Print JSON.")
    gates_check.set_defaults(handler=_handle_gates_check)

    return parser


def _parse_key_value_pairs(values: list[str], *, label: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{label} must be in key=value form: {value}")
        key, _, raw_value = value.partition("=")
        if not key.strip():
            raise ValueError(f"{label} key must not be empty: {value}")
        parsed[key.strip()] = raw_value
    return parsed


def _parse_approvals(values: list[str]) -> list[dict[str, str]]:
    approvals = []
    for value in values:
        if ":" not in value:
            raise ValueError(f"--approval must be in approver:role form: {value}")
        approver, _, role = value.partition(":")
        if not approver.strip() or not role.strip():
            raise ValueError(f"--approval must be in approver:role form: {value}")
        approvals.append({"approver": approver.strip(), "role": role.strip()})
    return approvals


def _handle_lineage_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    ledger_path = args.ledger or default_ledger_path(args.agent)
    snapshot = build_snapshot(
        agent=args.agent,
        operation_id=args.operation_id,
        operation_kind=args.operation_kind,
        review_status=args.review_status,
        environment=args.environment,
        prompt_config_path=args.prompt_config,
        dataset_path=args.dataset,
        rubric_eval_config_path=args.rubric_eval_config,
        grader_path=args.grader,
        model_deployment=args.model_deployment or None,
        base_model=args.base_model or None,
        source_path=args.source_path,
        reference_only=args.reference_only,
        notes=args.notes,
        metrics=_parse_key_value_pairs(args.metrics, label="--metric"),
        approvals=_parse_approvals(args.approvals),
    )
    appended = append_snapshot(ledger_path, snapshot)
    return {"ledger": str(ledger_path), "snapshot": appended}


def _handle_lineage_verify(args: argparse.Namespace) -> dict[str, Any]:
    ledger_path = args.ledger or (default_ledger_path(args.agent) if args.agent else None)
    if ledger_path is None:
        raise ValueError("either --ledger or --agent is required")

    if args.snapshot_id:
        snapshot = find_snapshot(ledger_path, args.snapshot_id)
        if snapshot is None:
            raise ValueError(f"snapshot not found in {ledger_path}: {args.snapshot_id}")
    else:
        snapshot = latest_snapshot(ledger_path, agent=args.agent or None)
        if snapshot is None:
            raise ValueError(f"no snapshots found in {ledger_path}")

    result = verify_snapshot(
        snapshot,
        prompt_config_path=args.prompt_config,
        dataset_path=args.dataset,
        rubric_eval_config_path=args.rubric_eval_config,
        grader_path=args.grader,
        model_deployment=args.model_deployment or None,
    )
    return {"ledger": str(ledger_path), "agent": snapshot.get("agent"), **result}


def _handle_lineage_report(args: argparse.Namespace) -> dict[str, Any]:
    ledger_path = args.ledger or (default_ledger_path(args.agent) if args.agent else None)
    if ledger_path is None and args.reference is None:
        raise ValueError("at least one of --ledger, --agent, or --reference is required")
    return lineage_report(
        ledger_path or Path(default_ledger_path(args.agent or "unknown")),
        agent=args.agent or None,
        reference_path=args.reference,
    )


def _handle_gates_check(args: argparse.Namespace) -> dict[str, Any]:
    return evaluate_gates(
        operation=args.operation,
        review_approved=args.review_approved,
        lineage_status=args.lineage_status,
        model_ready=args.model_ready,
        quota_ready=args.quota_ready,
        spend_confirmed=args.spend_confirmed,
        protected_approver=args.protected_approver or None,
        required_approver_role=args.required_approver_role or None,
        approvals=_parse_approvals(args.approvals),
    )


def _print_human(result: Any) -> None:
    if isinstance(result, dict):
        _print_dict(result)
        return
    print(result)


def _print_dict(data: dict[str, Any], indent: int = 0) -> None:
    prefix = " " * indent
    for key, value in data.items():
        label = key.replace("_", " ")
        if isinstance(value, dict):
            print(f"{prefix}{label}:")
            _print_dict(value, indent + 2)
        elif isinstance(value, list):
            print(f"{prefix}{label}:")
            for item in value:
                if isinstance(item, dict):
                    print(f"{prefix}  -")
                    _print_dict(item, indent + 4)
                else:
                    print(f"{prefix}  - {item}")
        else:
            print(f"{prefix}{label}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
