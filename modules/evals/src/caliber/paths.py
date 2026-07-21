from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root()))
    except ValueError:
        return str(path)


def git_sha(path: Path) -> str:
    """Return the current commit SHA for a git checkout, or "unknown" if unavailable.

    Safe to call against any directory; never raises. Used for source-commit
    lineage across dataset generation and quality-evidence snapshots.
    """
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
