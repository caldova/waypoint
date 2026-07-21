#!/usr/bin/env python3
"""Build a deterministic deployment plan from a monorepo Git diff."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def path_matches(path: str, pattern: str) -> bool:
    normalized = path.removeprefix("./")
    normalized_pattern = pattern.removeprefix("./")
    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(f"{prefix}/")
    return fnmatch.fnmatchcase(normalized, normalized_pattern)


def _add_reason(reasons: dict[str, list[str]], name: str, reason: str) -> None:
    if reason not in reasons[name]:
        reasons[name].append(reason)


def _validate_impact_graph(impact: dict[str, Any]) -> None:
    stages = impact.get("stages")
    agents = impact.get("agents")
    if not isinstance(stages, dict) or not stages:
        raise ValueError("deployment_impact.stages must be a non-empty object")
    if not isinstance(agents, list) or not agents:
        raise ValueError("deployment_impact.agents must be a non-empty array")
    if len(set(agents)) != len(agents):
        raise ValueError("deployment_impact.agents contains duplicates")

    for stage, config in stages.items():
        for downstream in config.get("propagates_to", []):
            if downstream not in stages:
                raise ValueError(f"stage {stage!r} propagates to unknown stage {downstream!r}")
    for rule in impact.get("path_rules", []):
        for stage in rule.get("stages", []):
            if stage not in stages:
                raise ValueError(f"path rule {rule.get('name')!r} references unknown stage {stage!r}")


def _reported(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "healthy", "in_sync", "none", "ok"}
    if isinstance(value, dict):
        if "drifted" in value:
            return bool(value["drifted"])
        if "missing" in value:
            return bool(value["missing"])
        if "deployed" in value:
            return not bool(value["deployed"])
    return bool(value)


def _apply_external_signals(
    *,
    signal: dict[str, Any] | None,
    signal_label: str,
    stage_reasons: dict[str, list[str]],
    agent_reasons: dict[str, list[str]],
) -> None:
    if not signal:
        return
    for stage, value in sorted(signal.get("stages", {}).items()):
        if stage in stage_reasons and _reported(value):
            _add_reason(stage_reasons, stage, f"{signal_label} requires {stage}.")
    for agent, value in sorted(signal.get("agents", {}).items()):
        if agent in agent_reasons and _reported(value):
            _add_reason(agent_reasons, agent, f"{signal_label} requires {agent}.")
            _add_reason(stage_reasons, "deploy_agents", f"{signal_label} requires {agent}.")


def build_plan(
    manifest: dict[str, Any],
    changed_paths: list[str],
    *,
    base: str | None,
    head: str,
    initial: bool = False,
    full: bool = False,
    force_full: bool = False,
    recorded_state: dict[str, Any] | None = None,
    drift: dict[str, Any] | None = None,
) -> dict[str, Any]:
    impact = manifest["deployment_impact"]
    _validate_impact_graph(impact)
    stages = impact["stages"]
    agents = impact["agents"]
    stage_reasons = {stage: [] for stage in stages}
    agent_reasons = {agent: [] for agent in agents}
    normalized_paths = sorted({path.removeprefix("./") for path in changed_paths if path})
    unknown_paths: list[str] = []
    full_reasons: list[str] = []
    mode = "selective"

    if initial or recorded_state and recorded_state.get("initialized") is False:
        mode = "initial"
        full_reasons.append("Initial deployment has no trusted recorded baseline.")
    if full:
        mode = "full"
        full_reasons.append("Full deployment mode was requested.")
    if force_full:
        mode = "forced_full"
        full_reasons.append("Forced full deployment was requested.")

    for path in normalized_paths:
        if any(path_matches(path, pattern) for pattern in impact.get("full_deploy_paths", [])):
            full_reasons.append(f"Shared deployment definition changed: {path}.")
            continue

        matched = False
        agent_root = impact["agent_sources"]["root"].rstrip("/")
        if path.startswith(f"{agent_root}/"):
            relative = path[len(agent_root) + 1 :]
            candidate = relative.split("/", 1)[0]
            if candidate in agent_reasons:
                matched = True
                _add_reason(agent_reasons, candidate, f"Agent source or configuration changed: {path}.")
                _add_reason(stage_reasons, "deploy_agents", f"Agent {candidate} changed.")

        if any(
            path_matches(path, pattern)
            for pattern in impact["agent_sources"].get("shared_paths", [])
        ):
            matched = True
            for agent in agents:
                _add_reason(agent_reasons, agent, f"Shared agent deployment source changed: {path}.")
            _add_reason(stage_reasons, "deploy_agents", f"Shared agent source changed: {path}.")

        for rule in impact.get("path_rules", []):
            if not any(path_matches(path, pattern) for pattern in rule.get("paths", [])):
                continue
            matched = True
            for stage in rule.get("stages", []):
                _add_reason(stage_reasons, stage, f"{rule['name']} changed: {path}.")
            if rule.get("all_agents"):
                for agent in agents:
                    _add_reason(agent_reasons, agent, f"{rule['name']} changed: {path}.")
            if rule.get("exclusive"):
                break

        if matched:
            continue
        if any(path_matches(path, pattern) for pattern in impact.get("ignored_paths", [])):
            continue
        unknown_paths.append(path)

    if unknown_paths and impact.get("unknown_path_behavior") == "full":
        mode = "conservative_full"
        full_reasons.append(
            "Unknown source paths require a conservative full deployment: "
            + ", ".join(unknown_paths)
            + "."
        )

    if full_reasons:
        for stage in stages:
            for reason in full_reasons:
                _add_reason(stage_reasons, stage, reason)
        for agent in agents:
            for reason in full_reasons:
                _add_reason(agent_reasons, agent, reason)

    _apply_external_signals(
        signal=recorded_state,
        signal_label="Recorded deployment state",
        stage_reasons=stage_reasons,
        agent_reasons=agent_reasons,
    )
    _apply_external_signals(
        signal=drift,
        signal_label="Live drift",
        stage_reasons=stage_reasons,
        agent_reasons=agent_reasons,
    )

    changed = True
    while changed:
        changed = False
        for stage, config in stages.items():
            if not stage_reasons[stage]:
                continue
            if config.get("select_all_agents"):
                for agent in agents:
                    before = len(agent_reasons[agent])
                    _add_reason(
                        agent_reasons,
                        agent,
                        f"{config['label']} changes can alter agent deployment inputs.",
                    )
                    changed = changed or len(agent_reasons[agent]) != before
            for downstream in config.get("propagates_to", []):
                before = len(stage_reasons[downstream])
                _add_reason(
                    stage_reasons,
                    downstream,
                    f"Required after {config['label']}.",
                )
                changed = changed or len(stage_reasons[downstream]) != before

    if any(agent_reasons.values()) and not stage_reasons["deploy_agents"]:
        _add_reason(stage_reasons, "deploy_agents", "One or more hosted agents require deployment.")

    selected_agents = [agent for agent in agents if agent_reasons[agent]]
    plan = {
        "schema_version": "1.0",
        "mode": mode,
        "base": base,
        "head": head,
        "full_deployment": bool(full_reasons),
        "changed_paths": normalized_paths,
        "unknown_paths": unknown_paths,
        "stages": {
            stage: {
                "run": bool(stage_reasons[stage]),
                "deployable": config.get("deployable", True),
                "reasons": stage_reasons[stage],
            }
            for stage, config in stages.items()
        },
        "agents": {
            agent: {
                "deploy": bool(agent_reasons[agent]),
                "reasons": agent_reasons[agent],
            }
            for agent in agents
        },
        "selected_agents": selected_agents,
    }
    plan["has_deployment_work"] = any(
        stage["run"] and stage["deployable"] for stage in plan["stages"].values()
    )
    return plan


def git_changed_paths(repo: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--name-status",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base,
            head,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tokens = result.stdout.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index]
        index += 1
        if index >= len(tokens):
            raise ValueError("git diff returned a status without a path")
        paths.add(tokens[index])
        index += 1
        if status[0] in {"R", "C"}:
            if index >= len(tokens):
                raise ValueError("git diff returned an incomplete rename or copy")
            paths.add(tokens[index])
            index += 1
    return sorted(paths)


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_github_outputs(plan: dict[str, Any], output_path: str) -> None:
    with open(output_path, "a", encoding="utf-8") as handle:
        for stage, decision in plan["stages"].items():
            handle.write(f"{stage}={str(decision['run']).lower()}\n")
        handle.write(f"has_deployment_work={str(plan['has_deployment_work']).lower()}\n")
        handle.write(f"full_deployment={str(plan['full_deployment']).lower()}\n")
        handle.write(f"mode={plan['mode']}\n")
        handle.write(
            "selected_agents="
            + json.dumps(plan["selected_agents"], separators=(",", ":"))
            + "\n"
        )


def _write_summary(plan: dict[str, Any], summary_path: str) -> None:
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("## Deployment plan\n\n")
        handle.write(
            f"- Mode: `{plan['mode']}`\n"
            f"- Base: `{plan['base'] or '<none>'}`\n"
            f"- Head: `{plan['head']}`\n"
            f"- Changed paths: {len(plan['changed_paths'])}\n\n"
        )
        handle.write("| Stage | Decision | Reasons |\n| --- | --- | --- |\n")
        for stage, decision in plan["stages"].items():
            reasons = "<br>".join(reason.replace("|", "\\|") for reason in decision["reasons"])
            handle.write(
                f"| {stage} | {'run' if decision['run'] else 'skip'} | "
                f"{reasons or 'No source impact or drift detected.'} |\n"
            )
        selected = ", ".join(plan["selected_agents"]) or "none"
        handle.write(f"\n- Selected agents: {selected}\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--mode", choices=("auto", "initial", "full"), default="auto")
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--state")
    parser.add_argument("--drift")
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest = _load_json(args.manifest)
    assert manifest is not None
    state = _load_json(args.state)
    drift = _load_json(args.drift)
    base = args.base or (state or {}).get("base_sha")
    initial = args.mode == "initial" or not base
    changed_paths = list(args.changed_path)
    if not changed_paths and not initial and args.mode != "full":
        changed_paths = git_changed_paths(Path(args.repo), base, args.head)

    plan = build_plan(
        manifest,
        changed_paths,
        base=base,
        head=args.head,
        initial=initial,
        full=args.mode == "full",
        force_full=args.force_full,
        recorded_state=state,
        drift=drift,
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2, sort_keys=True)
        handle.write("\n")
    github_output = args.github_output or os.environ.get("GITHUB_OUTPUT")
    if github_output:
        _write_github_outputs(plan, github_output)
    summary = args.summary or os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        _write_summary(plan, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
