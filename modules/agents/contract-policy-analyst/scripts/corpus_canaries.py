"""Verify added source families through the unchanged real knowledge-base tool."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from toolbox import _call_foundryiq_toolbox


def references(result):
    refs = []
    for index, part in enumerate(result.get("content") or []):
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        if index == 0:
            continue
        try:
            value = json.loads(part.get("text", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("kind") == "reference":
            refs.append(value)
    return refs


async def run(args):
    rows = [json.loads(line) for line in args.canaries.read_text(encoding="utf-8").splitlines()]
    semaphore = asyncio.Semaphore(args.concurrency)
    args.out.mkdir(parents=True, exist_ok=True)

    async def check(row):
        path = args.out / f"{row['family']}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if args.offline_from:
            result = json.loads(
                (args.offline_from / f"{row['family']}.json").read_text(encoding="utf-8"),
            )["result"]
        else:
            async with semaphore:
                result = await _call_foundryiq_toolbox(None, query=row["query"])
        refs = references(result)
        identifiers = [
            unquote(str(ref.get("uri", "")) + " " + str(ref.get("sourceData", {}).get("uid", ""))
                    + " " + str(ref.get("sourceData", {}).get("blob_url", "")))
            for ref in refs
        ]
        text = "\n".join(str(ref.get("sourceData", {}).get("snippet", "")) for ref in refs)
        found = {
            document: any(document.casefold() in value.casefold() for value in identifiers)
            for document in row["expected_documents"]
        }
        report = {
            "family": row["family"], "split": row["split"],
            "not_optimizer_input": True, "query": row["query"],
            "documents": found,
            "source_anchor_found": row["distinctive_source_anchor"].casefold() in text.casefold(),
            "tool_ok": result.get("ok") is True, "reference_count": len(refs), "result": result,
        }
        report["pass"] = (
            report["tool_ok"] and all(found.values()) and report["source_anchor_found"]
        )
        with path.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(json.dumps({key: report[key] for key in ("family", "pass", "reference_count")}),
              flush=True)
        return report

    reports = await asyncio.gather(*(check(row) for row in rows))
    summary = {
        "families": len(reports), "passed": sum(report["pass"] for report in reports),
        "failed": [report["family"] for report in reports if not report["pass"]],
        "agent_model_invoked": False, "not_optimizer_input": True,
    }
    with (args.out / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(json.dumps(summary, indent=2))
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canaries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--offline-from", type=Path)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if (not args.allow_live and not args.offline_from) or args.concurrency < 1:
        parser.error("Live retrieval permission and positive concurrency required.")
    raise SystemExit(asyncio.run(run(args)))
