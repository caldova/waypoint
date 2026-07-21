"""Tests for caliber.paths, in particular the shared git_sha() helper reused
by both caliber.lineage and caliber.contract_policy.
"""

from __future__ import annotations

from pathlib import Path

from caliber.paths import git_sha


def test_git_sha_returns_a_40_char_hex_sha_for_a_real_checkout() -> None:
    sha = git_sha(Path(__file__).resolve().parent)
    assert sha != "unknown"
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_git_sha_returns_unknown_for_a_non_git_directory(tmp_path: Path) -> None:
    assert git_sha(tmp_path) == "unknown"
