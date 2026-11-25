"""contract-evidence-analyst evals: optimizer data, Foundry evaluator, arm runs, summaries.

Every arm is a pinned hosted-agent version (same code, same user message = the benchmark
``task`` verbatim); only instructions/model differ. Responses are generated client-side with
retry (every attempt retained),
graded locally with the frozen grader, and summarized with unique-case vs repeat reporting.

    uv run python -m caliber.contract_evidence_eval run --arm baseline --version 1 \
        --model gpt-6-astra --split dev_eval --runs 5
    uv run python -m caliber.contract_evidence_eval summarize --arm baseline --split dev_eval
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import statistics
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caliber.contract_evidence_benchmark import AGENT_NAME, load_split

REPO = Path(__file__).resolve().parents[4]
EVALS = REPO / "modules" / "evals"
DATASET_DIR = EVALS / "datasets" / AGENT_NAME / "benchmark-v1"
GRADER_PATH = EVALS / "graders" / AGENT_NAME / "contract_evidence_grader.py"
AGENT_DIR = REPO / "modules" / "agents" / AGENT_NAME
EVIDENCE = REPO / "modules" / "optimization" / "evidence" / AGENT_NAME
PASS_THRESHOLD = 0.80
EVALUATOR_NAME = "contract-evidence-accuracy"
RUBRIC_NAME = "contract-evidence-quality"
RUBRIC_PATH = GRADER_PATH.parent / "quality-rubric.json"

# USD per 1M tokens (input, output). Sources are recorded in the evidence file;
# astra is the Alaska-used list price.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-astra": (10.0, 50.0),
    "mai-code-2-flash": (0.05, 0.25),
}
PRICE_SOURCES = {
    "gpt-6-astra": (
        "Alaska rubric_eval.PRICES (eastus Global Standard retail, as used in the Alaska report)"
    ),
    "mai-code-2-flash": "Azure retail prices API, swedencentral, MAI Models product (read 2026)",
}

_LOCK = threading.Lock()
_CREDENTIAL: Any = None


def load_grader() -> Any:
    spec = importlib.util.spec_from_file_location("contract_evidence_grader", GRADER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def price_key(model: str) -> str:
    return "mai-code-2-flash" if model.startswith("mai-code-2") else model


def cost_usd(model: str, usage: dict[str, Any]) -> float:
    price_in, price_out = PRICES[price_key(model)]
    return (
        (usage.get("input_tokens") or 0) * price_in + (usage.get("output_tokens") or 0) * price_out
    ) / 1e6


# ---------------------------------------------------------------- optimizer data and evaluator


def optimizer_rows(split: str, per_outcome: int, seed: int = 7) -> list[dict[str, Any]]:
    """Stratified {id, query, ground_truth} rows; ground_truth is the reference JSON string."""
    rows = load_split(DATASET_DIR, split)
    rng = random.Random(seed)
    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_outcome[row["outcome"]].append(row)
    picked: list[dict[str, Any]] = []
    for outcome in sorted(by_outcome):
        group = sorted(by_outcome[outcome], key=lambda r: r["id"])
        seen_families: set[str] = set()
        rng.shuffle(group)
        # Prefer distinct families first, then fill.
        ordered = [
            r for r in group if not (r["family"] in seen_families or seen_families.add(r["family"]))
        ]
        ordered += [r for r in group if r not in ordered]
        picked.extend(ordered[:per_outcome])
    return [
        {
            "id": r["id"],
            "query": r["task"],
            "ground_truth": json.dumps(r["reference"], sort_keys=True),
        }
        for r in sorted(picked, key=lambda r: r["id"])
    ]


def write_optimizer_data(train_per_outcome: int = 4, val_per_outcome: int = 3) -> dict[str, Any]:
    out = AGENT_DIR / "optimizer"
    out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {}
    for name, split, n in (
        ("train", "train", train_per_outcome),
        ("validation", "validation", val_per_outcome),
    ):
        rows = optimizer_rows(split, n)
        body = "".join(
            json.dumps({"query": r["query"], "ground_truth": r["ground_truth"]}, ensure_ascii=False)
            + "\n"
            for r in rows
        )
        path = out / f"optimizer-{name}.jsonl"
        path.write_text(body, encoding="utf-8", newline="\n")
        record[name] = {
            "split": split,
            "rows": len(rows),
            "ids": [r["id"] for r in rows],
            "sha256": sha256(body),
        }
    (out / "optimizer-data.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return record


_EVALUATOR_WRAPPER = """

# ---- Foundry evaluator wrapper: map {response, ground_truth} or messages onto the grader ----
def _foundry_response_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for message in reversed(value):
            if isinstance(message, dict) and message.get("role") in (None, "assistant"):
                text = _content_text(message.get("content"))
                if text:
                    return text
        return _content_text(value)
    if isinstance(value, dict):
        return _output_text(value)
    return str(value or "")


_frozen_grade = grade


def grade(sample, item):
    sample = sample or {}
    item = item or {}
    if "reference" in item:
        return _frozen_grade(sample, item)
    response = item.get("response")
    if response is None:
        response = item.get("messages")
    if response is None:
        response = sample.get("output_text") if isinstance(sample, dict) else sample
    return _frozen_grade(
        {"output_text": _foundry_response_text(response)}, {"reference": item.get("ground_truth")}
    )
"""


def evaluator_source() -> str:
    return GRADER_PATH.read_text(encoding="utf-8") + _EVALUATOR_WRAPPER


def evaluator_body() -> dict[str, Any]:
    return {
        "display_name": "Contract evidence accuracy (frozen code grader v1, 0-1)",
        "description": (
            "Frozen contract-evidence-analyst grader v1; code sha256 "
            f"{sha256(GRADER_PATH.read_text(encoding='utf-8'))}."
        ),
        "evaluator_type": "custom",
        "categories": ["quality"],
        "definition": {
            "type": "code",
            "code_text": evaluator_source(),
            "data_schema": {
                "type": "object",
                "properties": {"response": {}, "ground_truth": {}, "messages": {}},
                "required": [],
            },
            "metrics": {
                "score": {
                    "type": "continuous",
                    "desirable_direction": "increase",
                    "min_value": 0,
                    "max_value": 1,
                }
            },
        },
    }


def register_evaluator(endpoint: str) -> dict[str, Any]:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    evaluators = getattr(client, "evaluators", None) or client.beta.evaluators
    created = evaluators.create_version(
        name=EVALUATOR_NAME,
        evaluator_version=evaluator_body(),
        headers={"Foundry-Features": "Evaluations=V1Preview"},
    )
    return {"name": EVALUATOR_NAME, "version": str(created.version)}


def rubric_body() -> dict[str, Any]:
    """LLM-judge rubric paired with the code grader for the optimizer (Alaska's working shape).

    The code grader returns no reason text; the rubric gives GEPA's reflection step judge reasons.
    It sees ground_truth (the synthetic reference). Accuracy is still reported by the code grader.
    """
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    rubric_sha = sha256(RUBRIC_PATH.read_text(encoding="utf-8"))
    text_props = ("query", "response", "ground_truth")
    return {
        "display_name": "Contract evidence quality (rubric judge; reference-anchored)",
        "description": (
            "Judge rubric for contract-evidence-analyst, anchored on ground_truth.reference_output "
            f"(synthetic, pending human review). rubric sha256 {rubric_sha}."
        ),
        "categories": ["quality", "agents"],
        "supported_evaluation_levels": ["turn", "conversation"],
        "evaluator_type": "custom",
        "definition": {
            **rubric,
            "init_parameters": {
                "type": "object",
                "required": ["model"],
                "properties": {
                    "model": {"type": "string", "description": "Judge model deployment"},
                    "threshold": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.5},
                },
            },
            "metrics": {
                RUBRIC_NAME: {
                    "type": "continuous",
                    "desirable_direction": "increase",
                    "min_value": 0.0,
                    "max_value": 1.0,
                    "is_primary": True,
                }
            },
            "data_schema": {
                "type": "object",
                "required": [],
                "properties": {
                    **{k: {"type": "string"} for k in text_props},
                    "messages": {"type": "array"},
                    "tool_definitions": {"type": "array"},
                },
            },
        },
    }


def register_rubric(endpoint: str) -> dict[str, Any]:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    evaluators = getattr(client, "evaluators", None) or client.beta.evaluators
    created = evaluators.create_version(
        name=RUBRIC_NAME,
        evaluator_version=rubric_body(),
        headers={"Foundry-Features": "Evaluations=V1Preview"},
    )
    return {"name": RUBRIC_NAME, "version": str(created.version)}


# ---------------------------------------------------------------- agent calls


def agent_call(endpoint: str, version: str, text: str, attempts: int = 8) -> dict[str, Any]:
    """One hosted-agent Responses call; every failed attempt is retained."""
    from azure.identity import DefaultAzureCredential
    from openai import OpenAI

    global _CREDENTIAL
    with _LOCK:
        _CREDENTIAL = _CREDENTIAL or DefaultAzureCredential()
    base = f"{endpoint.rstrip('/')}/agents/{AGENT_NAME}/endpoint/protocols/openai"
    reference = {"type": "agent_reference", "name": AGENT_NAME, "version": version}
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            token = _CREDENTIAL.get_token("https://ai.azure.com/.default").token
            started = time.perf_counter()
            with OpenAI(
                base_url=base,
                api_key=token,
                default_query={"api-version": "v1"},
                max_retries=0,
                timeout=300,
            ) as client:
                response = client.responses.create(
                    input=text, extra_body={"agent_reference": reference}
                )
            latency_ms = round((time.perf_counter() - started) * 1000)
            dumped = response.model_dump()
            return {
                "output_text": response.output_text or "",
                "usage": dumped.get("usage") or {},
                "model": dumped.get("model"),
                "latency_ms": latency_ms,
                "attempts": attempt,
                "attempt_errors": errors,
            }
        except Exception as error:  # noqa: BLE001 - retried, then recorded as a failure
            errors.append(f"{type(error).__name__}: {error}"[:400])
            if attempt < attempts:
                time.sleep(min(60.0, 2.0**attempt) + random.uniform(0, 2))
    return {
        "output_text": "",
        "usage": {},
        "model": None,
        "latency_ms": None,
        "attempts": attempts,
        "attempt_errors": errors,
        "error": errors[-1] if errors else "unknown",
    }


def run_arm(
    arm: str,
    version: str,
    model: str,
    split: str,
    runs: int,
    endpoint: str,
    concurrency: int = 3,
    limit: int | None = None,
) -> Path:
    """Generate `runs` responses per row (resumable), grade locally, append to the records."""
    grader = load_grader()
    rows = load_split(DATASET_DIR, split)[:limit] if limit else load_split(DATASET_DIR, split)
    out = EVIDENCE / "runs" / f"{arm}-{split}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done.add((rec["id"], rec["run"]))
    todo = [(row, k) for k in range(1, runs + 1) for row in rows if (row["id"], k) not in done]

    def one(job: tuple[dict[str, Any], int]) -> None:
        row, k = job
        sample = agent_call(endpoint, version, row["task"])
        result = grader.evaluate({"output_text": sample["output_text"]}, row)
        if sample.get("error"):
            result = {"score": 0.0, "components": {}, "flags": ["agent_error"]}
        rec = {
            "arm": arm,
            "agent_version": version,
            "model": model,
            "split": split,
            "run": k,
            "id": row["id"],
            "family": row["family"],
            "outcome": row["outcome"],
            "kind": row["kind"],
            "task_sha256": sha256(row["task"]),
            "score": result["score"],
            "passed": result["score"] >= PASS_THRESHOLD,
            "flags": result["flags"],
            "components": result.get("components", {}),
            "usage": sample["usage"],
            "response_model": sample["model"],
            "latency_ms": sample["latency_ms"],
            "attempts": sample["attempts"],
            "attempt_errors": sample["attempt_errors"],
            "error": sample.get("error"),
            "cost_usd": cost_usd(model, sample["usage"]),
            "output_text": sample["output_text"],
            "grader_version": grader.GRADER_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with _LOCK, out.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(concurrency) as pool:
        list(pool.map(one, todo))
    return out


# ---------------------------------------------------------------- summaries

CRITICAL_FLAGS = (
    "invalid_json",
    "invalid_shape",
    "boundary_violation",
    "false_approval",
    "fabricated_ref",
    "agent_error",
)


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        by_run[rec["run"]].append(rec)
        by_case[rec["id"]].append(rec)
    run_means = [statistics.mean(r["score"] for r in recs) for _, recs in sorted(by_run.items())]
    run_pass = [statistics.mean(r["passed"] for r in recs) for _, recs in sorted(by_run.items())]
    case_mean = {cid: statistics.mean(r["score"] for r in recs) for cid, recs in by_case.items()}
    case_majority = {
        cid: sum(r["passed"] for r in recs) * 2 > len(recs) for cid, recs in by_case.items()
    }
    by_outcome: dict[str, list[str]] = defaultdict(list)
    for cid, recs in by_case.items():
        by_outcome[recs[0]["outcome"]].append(cid)
    flags = Counter(f for r in records for f in r["flags"])
    latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]
    n = len(records)
    usage_mean = {
        k: statistics.mean((r["usage"] or {}).get(k) or 0 for r in records)
        for k in ("input_tokens", "output_tokens")
    }
    reasoning = [
        ((r["usage"] or {}).get("output_tokens_details") or {}).get("reasoning_tokens") or 0
        for r in records
    ]
    return {
        "unique_cases": len(by_case),
        "runs": len(by_run),
        "responses": n,
        "mean_score": statistics.mean(r["score"] for r in records),
        "pass_rate": statistics.mean(r["passed"] for r in records),
        "run_mean_scores": run_means,
        "run_pass_rates": run_pass,
        "run_score_sd": statistics.pstdev(run_means) if len(run_means) > 1 else 0.0,
        "unique_case_mean_score": statistics.mean(case_mean.values()),
        "unique_case_majority_pass_rate": statistics.mean(case_majority.values()),
        "cases_always_pass": sum(all(r["passed"] for r in recs) for recs in by_case.values()),
        "cases_never_pass": sum(not any(r["passed"] for r in recs) for recs in by_case.values()),
        "per_outcome": {
            outcome: {
                "cases": len(ids),
                "mean_score": statistics.mean(case_mean[i] for i in ids),
                "majority_pass_rate": statistics.mean(case_majority[i] for i in ids),
            }
            for outcome, ids in sorted(by_outcome.items())
        },
        "flag_counts": dict(flags.most_common()),
        "critical_failures": {f: flags.get(f, 0) for f in CRITICAL_FLAGS},
        "unrecovered_errors": sum(1 for r in records if r.get("error")),
        "retried_calls": sum(1 for r in records if r["attempts"] > 1),
        "latency_ms": {
            "p50": _pct(latencies, 0.5),
            "p95": _pct(latencies, 0.95),
            "mean": statistics.mean(latencies) if latencies else None,
        },
        "tokens_mean": {**usage_mean, "reasoning_tokens": statistics.mean(reasoning)},
        "cost_usd_total": sum(r["cost_usd"] for r in records),
        "cost_usd_per_1k_lines": 1000 * sum(r["cost_usd"] for r in records) / n,
        "models": dict(Counter(str(r.get("response_model")) for r in records)),
        "grader_versions": sorted({r["grader_version"] for r in records}),
    }


def load_records(arm: str, split: str) -> list[dict[str, Any]]:
    path = EVIDENCE / "runs" / f"{arm}-{split}.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("optimizer-data")
    sub.add_parser("evaluator-source")
    sub.add_parser("register-evaluator")
    sub.add_parser("register-rubric")
    run = sub.add_parser("run")
    for name in ("--arm", "--version", "--model", "--split"):
        run.add_argument(name, required=True)
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--concurrency", type=int, default=3)
    run.add_argument("--limit", type=int)
    summ = sub.add_parser("summarize")
    summ.add_argument("--arm", required=True)
    summ.add_argument("--split", required=True)
    args = ap.parse_args()
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if args.cmd == "optimizer-data":
        print(json.dumps(write_optimizer_data(), indent=2))
    elif args.cmd == "evaluator-source":
        print(evaluator_source())
    elif args.cmd == "register-evaluator":
        print(json.dumps(register_evaluator(endpoint)))
    elif args.cmd == "register-rubric":
        print(json.dumps(register_rubric(endpoint)))
    elif args.cmd == "run":
        path = run_arm(
            args.arm,
            args.version,
            args.model,
            args.split,
            args.runs,
            endpoint,
            args.concurrency,
            args.limit,
        )
        print(json.dumps(summarize_records(load_records(args.arm, args.split)), indent=2))
        print(path)
    elif args.cmd == "summarize":
        print(json.dumps(summarize_records(load_records(args.arm, args.split)), indent=2))


if __name__ == "__main__":
    _main()
