"""Explicit release selection; never silently fall back to another arm."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from castia import load_agent_config
import yaml

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
    config = load_agent_config(directory)
    expected = directory / "baseline" / "instructions.md"
    if not expected.is_file():
        raise ValueError(f"Missing release instructions: {expected}")
    if not config.instructions or config.instructions.strip() != expected.read_text(
        encoding="utf-8"
    ).strip():
        raise ValueError("Loaded instructions do not match the selected release.")
    if config.source == "default":
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
    return config


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
