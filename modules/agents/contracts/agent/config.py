"""Configuration helpers for the Contracts agent."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

AGENT_ROOT = Path(__file__).resolve().parents[1]


def env_value(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def env_flag(name: str, *, default: bool = False) -> bool:
    value = env_value(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def waypoint_base_url() -> str | None:
    value = env_value("WAYPOINT_API_BASE_URL")
    return value.rstrip("/") if value else None


def foundry_project_endpoint() -> str | None:
    explicit = (
        env_value("CONTRACTS_FOUNDRY_PROJECT_ENDPOINT")
        or env_value("AGENT_CONTRACTS_PROJECT_ENDPOINT")
        or env_value("FOUNDRY_PROJECT_ENDPOINT")
        or env_value("AZURE_AI_PROJECT_ENDPOINT")
    )
    if explicit:
        return explicit.rstrip("/")

    version_endpoint = env_value("CONTRACTS_FOUNDRY_AGENT_ENDPOINT") or env_value(
        "AGENT_CONTRACTS_ENDPOINT"
    )
    if not version_endpoint:
        return None
    match = re.match(r"(.+?)/agents/[^/]+(?:/versions/[^/?]+)?(?:[/?].*)?$", version_endpoint)
    return match.group(1).rstrip("/") if match else None


def foundry_agent_version() -> str:
    configured = env_value("CONTRACTS_FOUNDRY_AGENT_VERSION") or env_value(
        "AGENT_CONTRACTS_VERSION"
    )
    if configured:
        return configured

    endpoint = env_value("CONTRACTS_FOUNDRY_AGENT_ENDPOINT") or env_value(
        "AGENT_CONTRACTS_ENDPOINT"
    )
    if not endpoint:
        return "<unset>"
    match = re.search(r"/versions/([^/?]+)", endpoint)
    return match.group(1) if match else "<unset>"


def contracts_inbox() -> str:
    return env_value("CONTRACTS_INBOX_ADDRESS") or "contracts@company.example"


def local_fixture_enabled() -> bool:
    raw = env_value("CONTRACTS_LOCAL_FIXTURE_MODE")
    if raw is not None:
        return raw.lower() not in {"0", "false", "no", "off"}
    return waypoint_base_url() is None


def local_state_dir() -> Path:
    configured = env_value("CONTRACTS_LOCAL_STATE_DIR")
    return Path(configured) if configured else AGENT_ROOT / ".contracts-state"
