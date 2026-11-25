"""Strict optimizer-ready config loading: one model per version, no silent fallbacks.

Resolution follows azure-ai-agentserver-optimization ``load_config`` (first match wins):

1. ``OPTIMIZATION_CONFIG`` inline JSON (optimizer candidate executions).
2. ``OPTIMIZATION_CANDIDATE_ID`` + ``OPTIMIZATION_RESOLVE_ENDPOINT`` (resolver API).
3. Local ``<config root>/<OPTIMIZATION_CANDIDATE_ID>``, else ``<config root>/baseline``.

castia's ``load_agent_config`` degrades failures to env defaults and the Azure loader drops a missing
candidate back to ``baseline``; either would let a version run a config it does not declare, so
:func:`load` checks the resolved source and fails at startup instead.
"""

from __future__ import annotations

import os
from pathlib import Path

from castia import load_agent_config
from castia.optimizing.config import AgentConfig

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_ROOT = ROOT / ".agent_configs"


class ConfigError(RuntimeError):
    """The resolved config is not the one this version declares."""


def config_root() -> Path:
    raw = os.getenv("OPTIMIZATION_LOCAL_DIR", "").strip()
    if not raw:
        return DEFAULT_CONFIG_ROOT
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def requested_mode() -> str:
    if os.getenv("OPTIMIZATION_CONFIG", "").strip():
        return "inline"
    if os.getenv("OPTIMIZATION_CANDIDATE_ID", "").strip() and os.getenv("OPTIMIZATION_RESOLVE_ENDPOINT", "").strip():
        return "resolver"
    return "local"


def expected_local_dir() -> Path:
    candidate = os.getenv("OPTIMIZATION_CANDIDATE_ID", "").strip()
    return config_root() / (candidate or "baseline")


def load() -> AgentConfig:
    mode = requested_mode()
    if mode == "local":
        target = expected_local_dir()
        if not (target / "metadata.yaml").is_file():
            raise ConfigError(f"no agent config at {target} (OPTIMIZATION_CANDIDATE_ID / OPTIMIZATION_LOCAL_DIR)")
    config = load_agent_config(config_root())
    validate(config, mode)
    return config


def validate(config: AgentConfig, mode: str) -> None:
    source = config.source or ""
    if mode == "inline":
        if source != "env:OPTIMIZATION_CONFIG":
            raise ConfigError(f"OPTIMIZATION_CONFIG is set but config came from {source!r}")
        return
    if mode == "resolver":
        candidate = os.environ["OPTIMIZATION_CANDIDATE_ID"].strip()
        if source != f"api:candidate:{candidate}":
            raise ConfigError(f"candidate {candidate!r} did not resolve (config came from {source!r})")
        return
    target = expected_local_dir().resolve()
    if not source.startswith("local:") or Path(source.removeprefix("local:")).resolve() != target:
        raise ConfigError(f"expected local config {target}, got {source!r}")
    declared = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()
    if declared and declared != config.model:
        raise ConfigError(
            f"AZURE_AI_MODEL_DEPLOYMENT_NAME={declared!r} but {target.name}/metadata.yaml runs {config.model!r}"
        )
