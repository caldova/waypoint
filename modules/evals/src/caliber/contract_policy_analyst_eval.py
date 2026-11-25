"""Single-attempt hosted analyst probes: no hidden retries or run substitution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contract_evidence_eval import _bootstrap_ci, _sign_flip_p
from .paths import repo_root


def hosted_call(endpoint: str, version: str, task: str) -> dict[str, Any]:
    from azure.identity import AzureCliCredential
    from openai import APIError, OpenAI

    started = time.perf_counter()
    credential = AzureCliCredential()
    try:
        token = credential.get_token("https://ai.azure.com/.default").token
        with OpenAI(
            base_url=f"{endpoint.rstrip('/')}/agents/contract-policy-analyst/endpoint/protocols/openai",
            api_key=token,
            default_query={"api-version": "v1"},
            max_retries=0,
            timeout=300,
        ) as client:
            response = client.responses.create(
                input=task,
                extra_body={
                    "agent_reference": {
                        "type": "agent_reference",
                        "name": "contract-policy-analyst",
                        "version": version,
                    }
                },
            )
        dumped = response.model_dump()
        return {
            "output_text": response.output_text or "",
            "usage": dumped.get("usage"),
            "response_model": dumped.get("model"),
            "response_id": response.id,
            "response": dumped,
            "error": None,
            "attempts": 1,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except APIError as error:
        return {
            "output_text": "",
            "usage": None,
            "response_model": None,
            "response_id": None,
            "error": f"{type(error).__name__}: {error}",
            "attempts": 1,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    finally:
        credential.close()


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def paired_records(
    records_a: list[dict[str, Any]], records_b: list[dict[str, Any]],
    resamples: int = 10000, seed: int = 7,
) -> dict[str, Any]:
    def keyed(records: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
        result = {}
        for record in records:
            key = (record["id"], record["run"])
            if key in result:
                raise ValueError(f"Duplicate recorded attempt: {key}")
            result[key] = record
        return result

    a, b = keyed(records_a), keyed(records_b)
    if not a or a.keys() != b.keys():
        raise ValueError("Paired arms require identical cases and recorded runs, including errors.")
    diffs: dict[str, list[float]] = defaultdict(list)
    families: dict[str, list[str]] = defaultdict(list)
    for key, left in a.items():
        right = b[key]
        for field in (
            "task_sha256", "judge_sha256", "judge_model", "reference_sha256", "source_family",
        ):
            if left.get(field) is None or left[field] != right.get(field):
                raise ValueError(f"Paired {field} mismatch at {key}.")
        diffs[key[0]].append(right["score"] - left["score"])
        if key[0] not in families[left["source_family"]]:
            families[left["source_family"]].append(key[0])
    means = {case: statistics.fmean(values) for case, values in diffs.items()}
    values = list(means.values())
    return {
        "unique_cases": len(means),
        "source_families": len(families),
        "attempts_per_arm": len(a),
        "runs_per_case": sorted({len(diffs[case]) for case in diffs}),
        "mean_difference": statistics.fmean(values),
        "ci95_case_bootstrap": _bootstrap_ci([[value] for value in values], resamples, seed),
        "ci95_family_bootstrap": _bootstrap_ci(
            [[means[case] for case in cases] for cases in families.values()], resamples, seed
        ),
        "paired_sign_flip_p": _sign_flip_p(values, resamples, seed),
        "uncertainty_unit": "case means; source-family cluster CI also reported",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""))
    parser.add_argument("--version", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("Live inference requires --allow-live; no call was made.")
    if not args.endpoint:
        parser.error("FOUNDRY_PROJECT_ENDPOINT or --endpoint is required.")
    result = hosted_call(args.endpoint, args.version, args.task)
    record = {
        "created_at": datetime.now(UTC).isoformat(),
        "agent_version": args.version,
        "task_sha256": hashlib.sha256(args.task.encode("utf-8")).hexdigest(),
        "task": args.task,
        **result,
    }
    out = args.out or (
        repo_root().parents[1]
        / "modules" / "agents" / "contract-policy-analyst" / "runs" / "smoke.jsonl"
    )
    append_record(out, record)
    print(json.dumps({k: v for k, v in record.items() if k != "response"}, indent=2))
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
