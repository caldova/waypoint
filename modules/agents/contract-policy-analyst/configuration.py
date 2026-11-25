"""Explicit release selection; never silently fall back to another arm."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from castia import load_agent_config
from castia.optimizing.config import AgentConfig

from toolbox import validate_tool_definitions

ROOT = Path(__file__).resolve().parent


def release_directory() -> Path:
    local_dir = os.getenv("OPTIMIZATION_LOCAL_DIR", "").strip()
    directory = (ROOT / local_dir).resolve() if local_dir else ROOT / ".agent_configs"
    if not directory.is_relative_to(ROOT):
        raise ValueError("Release directory must be inside the analyst agent.")
    return directory


def load_release() -> Any:
    directory = release_directory()
    baseline = directory / "baseline"
    baseline_metadata = yaml.safe_load(
        (baseline / "metadata.yaml").read_text(encoding="utf-8")
    )
    inline = os.getenv("OPTIMIZATION_CONFIG", "").strip()
    candidate_id = os.getenv("OPTIMIZATION_CANDIDATE_ID", "").strip()
    resolver = os.getenv("OPTIMIZATION_RESOLVE_ENDPOINT", "").strip()
    if inline:
        from azure.ai.agentserver.optimization import load_config

        payload = json.loads(inline, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
        _validate_injected_payload(payload, baseline_metadata["model"])
        resolved = load_config(config_dir=directory)
        if resolved is None or resolved.source != "env:OPTIMIZATION_CONFIG":
            raise ValueError("Native optimizer injection did not resolve its inline config.")
        return _injected_config(resolved, payload)
    if resolver:
        from azure.ai.agentserver.optimization import (
            CandidateConfig,
            OptimizationConfig,
        )
        from castia.optimizing.jobs import OptimizerClient

        project = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
        prefix = f"{project}/agent_optimization_jobs/"
        job = resolver.removeprefix(prefix)
        if not resolver.startswith(prefix) or not _identifier(job) or not _identifier(candidate_id):
            raise ValueError("Native optimizer requires a valid GA job-scoped candidate config URI.")
        payload = OptimizerClient(project).candidate_config(job, candidate_id)
        _validate_injected_payload(payload, baseline_metadata["model"])
        candidate = CandidateConfig.from_dict(payload)
        resolved = OptimizationConfig(
            instructions=candidate.instructions, model=candidate.model,
            tool_definitions=candidate.tool_definitions,
            source=f"api:candidate:{candidate_id}", candidate_id=candidate_id,
        )
        return _injected_config(resolved, payload)
    selected = baseline
    if candidate_id:
        if not _identifier(candidate_id):
            raise ValueError("Invalid applied candidate identifier.")
        selected = directory / candidate_id
        if not selected.is_dir():
            raise ValueError("Applied candidate is missing; refusing baseline fallback.")
    config = load_agent_config(directory)
    expected = selected / "instructions.md"
    if not expected.is_file():
        raise ValueError(f"Missing release instructions: {expected}")
    if not config.instructions or config.instructions.strip() != expected.read_text(
        encoding="utf-8"
    ).strip():
        raise ValueError("Loaded instructions do not match the selected release.")
    if config.source == "default" or (
        candidate_id and config.source != f"local:{selected}"
    ):
        raise ValueError("Release config fell back to environment defaults.")
    validate_tool_definitions(config.tool_definitions)
    expected_tools = json.loads((expected.parent / "tools.json").read_text(encoding="utf-8"))
    if list(config.tool_definitions) != expected_tools:
        raise ValueError("Loaded tool definitions do not match the selected release.")
    expected_metadata = yaml.safe_load(
        (expected.parent / "metadata.yaml").read_text(encoding="utf-8")
    )
    if config.model != expected_metadata["model"]:
        raise ValueError("Loaded model does not match the selected release.")
    if candidate_id and config.model != baseline_metadata["model"]:
        raise ValueError("Applied candidate changed the fixed target model.")
    return config


def _identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key in native optimizer config.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant in native optimizer config: {value}")


def _validate_injected_payload(payload: Any, model: str) -> None:
    if not isinstance(payload, dict) or set(payload) - {
        "name", "model", "instructions", "tools", "skills", "temperature",
    }:
        raise ValueError("Unknown native optimizer candidate schema.")
    if not isinstance(payload.get("instructions"), str) or not payload["instructions"].strip():
        raise ValueError("Native optimizer instructions must be non-empty text.")
    if payload.get("model") != model:
        raise ValueError("Native optimizer candidate changed the fixed target model.")
    if payload.get("skills") not in (None, []) or payload.get("temperature") is not None:
        raise ValueError("Only instructions and tool descriptions may be optimized.")
    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise TypeError("Native optimizer tools must be a list.")
    validate_tool_definitions(tools)


def _injected_config(resolved: Any, payload: dict[str, Any]) -> AgentConfig:
    instructions = resolved.compose_instructions()
    if (
        instructions.strip() != payload["instructions"].strip()
        or resolved.model != payload["model"]
        or list(resolved.tool_definitions) != payload["tools"]
    ):
        raise ValueError("Native optimizer config differs from its actual injected payload.")
    return AgentConfig(
        model=resolved.model, instructions=instructions, source=resolved.source,
        tool_definitions=tuple(resolved.tool_definitions),
    )


def config_evidence(config: Any) -> dict[str, str]:
    def digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "model": config.model,
        "instructions_sha256": digest(config.instructions),
        "tools_sha256": digest(json.dumps(list(config.tool_definitions), sort_keys=True)),
        "config_source": str(config.source),
        "route": os.getenv("CPA_MODEL_ROUTE", "account"),
        "reasoning_effort": os.getenv("CPA_REASONING_EFFORT", ""),
    }
