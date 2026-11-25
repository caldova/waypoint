"""Capture real retrieval before/after a batch without substituting model answers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolbox import _call_foundryiq_toolbox  # noqa: E402


def reference_fingerprint(result: dict) -> tuple[str, int]:
    references = []
    for item in result.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        try:
            value = json.loads(item.get("text", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("kind") == "reference":
            references.append({
                "uri": value.get("uri"),
                "snippet": (value.get("sourceData") or {}).get("snippet"),
            })
    canonical = sorted(
        {json.dumps(reference, sort_keys=True) for reference in references}
    )
    return hashlib.sha256(json.dumps(canonical).encode("utf-8")).hexdigest(), len(canonical)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("--allow-live is required; retrieval may incur search/model charges.")
    if args.out.exists():
        parser.error("Refusing to overwrite an existing retrieval snapshot.")
    records = []
    for query in args.query:
        result = await _call_foundryiq_toolbox(None, query=query)
        digest, count = reference_fingerprint(result)
        records.append({
            "query": query,
            "result": result,
            "sha256": digest,
            "reference_count": count,
        })
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "all_retrievals_ok": all(
            record["result"]["ok"] and record["reference_count"] for record in records
        ),
        "records": records,
        "retrieval_variation": None,
        "snapshot_scope": (
            "Retrieved URI/snippet sets, excluding generated synthesis and request IDs; "
            "variation is not proof of source/index drift."
        ),
    }
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        old = {row["query"]: row["sha256"] for row in before["records"]}
        new = {row["query"]: row["sha256"] for row in records}
        report["retrieval_variation"] = old != new
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))
    return 0 if report["all_retrievals_ok"] and not report["retrieval_variation"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
