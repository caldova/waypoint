from __future__ import annotations

from pathlib import Path
from typing import Any


def inspect_forge(path: Path) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.exists():
        raise ValueError(f"Forge path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Forge path is not a directory: {root}")

    agents_dir = root / "agents"
    evals_dir = root / "evals"
    return {
        "path": str(root),
        "agents": _inspect_agents(agents_dir),
        "evals": _inspect_evals(evals_dir),
    }


def _inspect_agents(agents_dir: Path) -> list[dict[str, Any]]:
    if not agents_dir.is_dir():
        return []

    agents: list[dict[str, Any]] = []
    for agent_dir in sorted(item for item in agents_dir.iterdir() if item.is_dir()):
        if agent_dir.name.startswith("_"):
            continue
        agents.append(
            {
                "name": agent_dir.name,
                "agent_yaml": (agent_dir / "agent.yaml").exists(),
                "main_py": (agent_dir / "main.py").exists(),
                "toolbox_py": (agent_dir / "toolbox.py").exists(),
                "pyproject": (agent_dir / "pyproject.toml").exists(),
            }
        )
    return agents


def _inspect_evals(evals_dir: Path) -> dict[str, Any]:
    if not evals_dir.is_dir():
        return {"cases": []}

    cases_dir = evals_dir / "cases"
    return {"cases": _names(cases_dir, "*.jsonl")}


def _names(path: Path, pattern: str) -> list[str]:
    if not path.is_dir():
        return []
    return [item.name for item in sorted(path.glob(pattern))]
