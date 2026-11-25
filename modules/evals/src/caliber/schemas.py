from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetRow:
    messages: list[dict[str, str]]
    expected: dict[str, Any] = field(default_factory=dict)
    expected_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DatasetRow:
        if not isinstance(data, dict):
            raise ValueError("dataset row must be a JSON object")
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("dataset row must include a non-empty messages list")
        return cls(
            messages=messages,
            expected=data.get("expected", {}),
            expected_tools=list(data.get("expected_tools", [])),
            metadata=data.get("metadata", {}),
        )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSONL row") from exc
    return rows


def validate_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"JSONL file does not exist: {path}")
    rows = read_jsonl(path)
    for index, row in enumerate(rows, 1):
        DatasetRow.from_json(row)
        if not isinstance(row.get("messages"), list):
            raise ValueError(f"{path}:{index}: messages must be a list")
    return {"path": str(path), "rows": len(rows)}
