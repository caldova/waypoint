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

# Rows excluded from optimizer selection data only (never relabeled; RFT/eval splits unchanged).
# Found by the wrong-entity detectability scan: the generator's same-titled "wrong entity"
# distractor differs only by an identifier that appears nowhere else in the task, so the
# reference's "record not supplied" label cannot be derived from the sources.
KNOWN_LABEL_DEFECTS: dict[str, str] = {
    "sup009-utilized-capacity--missing-batch-records": "undetectable wrong-entity distractor",
    "sup015-country-scope--missing-work-order": "undetectable wrong-entity distractor",
    "sup013-material-surcharge--missing-market-event": "undetectable wrong-entity distractor",
}

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


def optimizer_rows(
    split: str, per_outcome: int, seed: int = 7, exclude: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    """Stratified {id, query, ground_truth} rows; ground_truth is the reference JSON string."""
    rows = [r for r in load_split(DATASET_DIR, split) if r["id"] not in exclude]
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


def write_optimizer_data(
    train_per_outcome: int = 4,
    val_per_outcome: int = 3,
    subdir: str = "",
    exclude_known_defects: bool = False,
) -> dict[str, Any]:
    out = AGENT_DIR / "optimizer" / subdir if subdir else AGENT_DIR / "optimizer"
    out.mkdir(parents=True, exist_ok=True)
    exclude = frozenset(KNOWN_LABEL_DEFECTS) if exclude_known_defects else frozenset()
    record: dict[str, Any] = {
        "excluded_known_label_defects": {i: KNOWN_LABEL_DEFECTS[i] for i in sorted(exclude)},
    }
    for name, split, n in (
        ("train", "train", train_per_outcome),
        ("validation", "validation", val_per_outcome),
    ):
        rows = optimizer_rows(split, n, exclude=exclude)
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


def rubric_body(path: Path = RUBRIC_PATH) -> dict[str, Any]:
    """LLM-judge rubric paired with the code grader for the optimizer (Alaska's working shape).

    The code grader returns no reason text; the rubric gives GEPA's reflection step judge reasons.
    The optimizer judge was observed not to receive ground_truth (rubric-sanity-v1.json), so v2
    states the benchmark's evidence conventions and critical failures directly. Accuracy is still
    reported by the code grader.
    """
    rubric = json.loads(path.read_text(encoding="utf-8"))
    rubric_sha = sha256(path.read_text(encoding="utf-8"))
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


def register_rubric(endpoint: str, path: Path = RUBRIC_PATH) -> dict[str, Any]:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    evaluators = getattr(client, "evaluators", None) or client.beta.evaluators
    created = evaluators.create_version(
        name=RUBRIC_NAME,
        evaluator_version=rubric_body(path),
        headers={"Foundry-Features": "Evaluations=V1Preview"},
    )
    return {
        "name": RUBRIC_NAME,
        "version": str(created.version),
        "rubric_sha256": sha256(path.read_text(encoding="utf-8")),
    }


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


ARMS: dict[str, dict[str, str]] = {
    "baseline": {
        "agent_version": "1",
        "model": "gpt-6-astra",
        "instructions": ".agent_configs/baseline/instructions.md",
        "description": "Minimal honest starter prompt on the teacher model",
    },
    "optimized": {
        "agent_version": "2",
        "model": "gpt-6-astra",
        "instructions": "releases/optimized/baseline/instructions.md",
        "description": "Agent Optimizer candidate opt_1a50d6dd..._0001 on the teacher model",
    },
    "mai2-base": {
        "agent_version": "3",
        "model": "mai-code-2-flash-base",
        "instructions": "releases/mai2-base/baseline/instructions.md",
        "description": "Optimized prompt on untuned MAI-Code-2-Flash",
    },
    "mai2-rft": {
        "agent_version": "4",
        "model": "tuned mai-code-2-flash (contract-evidence-mai2-r1)",
        "instructions": "releases/mai2-rft/baseline/instructions.md",
        "description": "Optimized prompt on RFT-tuned MAI-Code-2-Flash",
    },
}
QUALITY_SPLITS = ("dev_eval", "validation", "final_test")

# final_test history. Arms scored on final_test before the final all-arms comparison are
# non-pristine for that comparison; final_test must not be run or inspected again until then.
FINAL_TEST_STATUS: dict[str, Any] = {
    "policy": (
        "final_test is untouched until the final all-arms comparison: no runs or inspection for "
        "selection or interim reporting. r1/r2 candidates and RFT checkpoints are chosen on "
        "dev_eval/validation only."
    ),
    "label": (
        "final_test previously observed (baseline, optimized, mai2-base x1); not a pristine "
        "holdout for those arms"
    ),
    "interim_scorings": {
        "baseline": {"runs": 1, "date": "2026-11-24", "pristine": False},
        "optimized": {"runs": 1, "date": "2026-11-24", "pristine": False},
        "mai2-base": {"runs": 1, "date": "2026-11-24", "pristine": False},
    },
    "interim_inspection": (
        "comparisons/*-final_test.json were computed at interim from those runs; none was used "
        "to select a prompt, candidate or checkpoint."
    ),
}


def review_items() -> dict[str, Any]:
    """Benchmark items queued for human review. Labels are listed, never modified."""
    known = []
    wrong_entity = []
    for split in ("train", "validation", "dev_eval", "final_test"):
        for r in load_split(DATASET_DIR, split):
            if r["id"] in KNOWN_LABEL_DEFECTS:
                known.append({"id": r["id"], "split": split, "issue": KNOWN_LABEL_DEFECTS[r["id"]]})
            if "wrong_entity" in (r.get("modifiers") or []):
                wrong_entity.append(
                    {"id": r["id"], "split": split, "undetectable": r["id"] in KNOWN_LABEL_DEFECTS}
                )
    return {
        "status": "pending_human_review",
        "labels_modified": False,
        "known_label_defects": {
            "description": (
                "The missing_evidence generator adds a same-titled operational record for a "
                "different entity (wrong_entity). In these rows the altered identifier appears "
                "nowhere else in the task and the amount matches the bill, so the reference's "
                "'record not supplied' label cannot be derived from the sources. Excluded from "
                "optimizer r2 selection data only; RFT and eval splits are unchanged."
            ),
            "found_by": "identifier-token detectability scan over wrong_entity distractors",
            "items": known,
        },
        "wrong_entity_distractor_cases": {
            "description": (
                "All rows with the wrong_entity modifier. Reviewers should confirm the "
                "distractor's entity is distinguishable from the billed line and that the "
                "missing-record label holds."
            ),
            "counts": dict(Counter(i["split"] for i in wrong_entity)),
            "items": wrong_entity,
        },
        "grader_review": [
            {
                "component": "contract_evidence_grader v1 _score_gaps supplied-predicate keywords",
                "issue": (
                    "A model gap that names a document type also mentioned in a supplied record "
                    "(e.g. a purchase order 'identifying ... final-report deliverables' matching "
                    "[report]+[final]) is flagged false_gap and capped at 0.6. Frozen grader not "
                    "changed; review with the P1 'authorized source document' convention."
                ),
            }
        ],
    }


def build_quality() -> dict[str, Any]:
    """Collect every recorded arm/split summary into one machine-readable evidence file."""
    arms: dict[str, Any] = {}
    for arm, meta in ARMS.items():
        results = {}
        for split in QUALITY_SPLITS:
            path = EVIDENCE / "runs" / f"{arm}-{split}.jsonl"
            if path.exists():
                results[split] = summarize_records(load_records(arm, split))
        if results:
            instructions = AGENT_DIR / meta["instructions"]
            arms[arm] = {
                **meta,
                "instructions_sha256": sha256(instructions.read_text(encoding="utf-8"))
                if instructions.exists()
                else None,
                "results": results,
            }
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    rft_job = EVIDENCE / "mai2-rft" / "job.final.json"
    return {
        "agent": AGENT_NAME,
        "generated_at": datetime.now(UTC).isoformat(),
        "grader": {
            "path": str(GRADER_PATH.relative_to(REPO)).replace("\\", "/"),
            "sha256": sha256(GRADER_PATH.read_text(encoding="utf-8")),
            "version": load_grader().GRADER_VERSION,
            "pass_threshold": PASS_THRESHOLD,
        },
        "benchmark": {
            "path": str(DATASET_DIR.relative_to(REPO)).replace("\\", "/"),
            "splits": manifest.get("splits"),
            "selection_policy": (
                "Prompt/checkpoint selection used train/validation/dev_eval only; final_test "
                "was run once per arm after that arm was frozen."
            ),
            "final_test_status": FINAL_TEST_STATUS,
            "human_review_items": "human-review-items.json",
        },
        "prices_usd_per_1m_tokens": {
            model: {"input": p[0], "output": p[1], "source": PRICE_SOURCES[model]}
            for model, p in PRICES.items()
        },
        "rft_job": json.loads(rft_job.read_text(encoding="utf-8")) if rft_job.exists() else None,
        "arms": arms,
        "caveats": [
            "Benchmark labels are synthetic and pending_human_review; scores measure agreement "
            "with synthetic references, not audited ground truth.",
            "The code grader's decision-language screen is a phrase screen, not a semantic "
            "guarantee.",
            "gpt-6-astra price is the Alaska-report list price; MAI-2 price is the retail base "
            "serving price and excludes fine-tuned hosting fees and RFT training cost.",
            "Cost covers model tokens only, not hosted-agent compute.",
            "final_test results for baseline, optimized and mai2-base were scored once at interim "
            "and are non-pristine for the final comparison (benchmark.final_test_status).",
            "Three benchmark rows have undetectable wrong-entity labels and other wrong_entity "
            "rows await review (human-review-items.json); labels were not changed.",
        ],
    }


APPROVAL_FLAGS = ("false_approval", "missed_approval")


def _per_case(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for r in records:
        c = cases.setdefault(
            r["id"], {"family": r["family"], "outcome": r["outcome"], "scores": [], "passes": []}
        )
        c["scores"].append(float(r["score"] or 0.0))
        c["passes"].append(bool(r["passed"]))
        for flag in r.get("flags") or []:
            c.setdefault("flags", Counter())[flag] += 1
    for c in cases.values():
        c["mean"] = statistics.fmean(c["scores"])
        c["pass_rate"] = statistics.fmean(c["passes"])
    return cases


def _bootstrap_ci(
    groups: list[list[float]], n: int, seed: int, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile CI of the mean paired diff, resampling whole groups (cases or families)."""
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sample = [d for _g in range(len(groups)) for d in rng.choice(groups)]
        stats.append(statistics.fmean(sample))
    stats.sort()
    return stats[int(n * alpha / 2)], stats[int(n * (1 - alpha / 2)) - 1]


def _sign_flip_p(diffs: list[float], n: int, seed: int) -> float:
    """Two-sided paired randomization test on per-case mean diffs (exact when small)."""
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    if len(nonzero) <= 16:
        hits = total = 0
        for mask in range(1 << len(nonzero)):
            s = sum(d if mask >> i & 1 else -d for i, d in enumerate(nonzero))
            hits += abs(s) >= observed - 1e-12
            total += 1
        return hits / total
    rng = random.Random(seed)
    hits = sum(
        abs(sum(d if rng.random() < 0.5 else -d for d in nonzero)) >= observed - 1e-12
        for _ in range(n)
    )
    return (hits + 1) / (n + 1)


def paired_compare(
    arm_a: str, arm_b: str, split: str, resamples: int = 10000, seed: int = 7
) -> dict[str, Any]:
    """Per-case paired comparison of arm_b minus arm_a on the same split and grader."""
    ra, rb = load_records(arm_a, split), load_records(arm_b, split)
    graders = {r["grader_version"] for r in ra + rb}
    if len(graders) != 1:
        raise SystemExit(f"grader mismatch across arms: {sorted(graders)}")
    a, b = _per_case(ra), _per_case(rb)
    hashes_a = {r["id"]: r["task_sha256"] for r in ra}
    hashes_b = {r["id"]: r["task_sha256"] for r in rb}
    shared = sorted(set(a) & set(b))
    if not shared or any(hashes_a[i] != hashes_b[i] for i in shared):
        raise SystemExit("arms do not share identical task prompts")
    diffs = {i: b[i]["mean"] - a[i]["mean"] for i in shared}
    pass_diffs = {i: b[i]["pass_rate"] - a[i]["pass_rate"] for i in shared}
    by_family: dict[str, list[float]] = defaultdict(list)
    by_outcome: dict[str, list[float]] = defaultdict(list)
    for i in shared:
        by_family[a[i]["family"]].append(diffs[i])
        by_outcome[a[i]["outcome"]].append(diffs[i])
    values = list(diffs.values())
    pass_values = list(pass_diffs.values())

    def flag_total(cases: dict[str, dict[str, Any]], flag: str) -> int:
        return sum(cases[i].get("flags", Counter())[flag] for i in shared)

    return {
        "split": split,
        **({"holdout_status": FINAL_TEST_STATUS["label"]} if split == "final_test" else {}),
        "arm_a": arm_a,
        "arm_b": arm_b,
        "grader_version": next(iter(graders)),
        "cases": len(shared),
        "families": len(by_family),
        "runs_per_case": {
            arm_a: sorted({len(a[i]["scores"]) for i in shared}),
            arm_b: sorted({len(b[i]["scores"]) for i in shared}),
        },
        "mean_score": {
            arm_a: statistics.fmean(a[i]["mean"] for i in shared),
            arm_b: statistics.fmean(b[i]["mean"] for i in shared),
        },
        "mean_diff": statistics.fmean(values),
        "ci95_case_bootstrap": _bootstrap_ci([[d] for d in values], resamples, seed),
        "ci95_family_bootstrap": _bootstrap_ci(list(by_family.values()), resamples, seed),
        "sign_flip_p": _sign_flip_p(values, resamples, seed),
        "pass_rate_diff": statistics.fmean(pass_values),
        "pass_rate_ci95_case_bootstrap": _bootstrap_ci([[d] for d in pass_values], resamples, seed),
        "pass_rate_sign_flip_p": _sign_flip_p(pass_values, resamples, seed),
        "cases_improved": sum(d > 1e-9 for d in values),
        "cases_worse": sum(d < -1e-9 for d in values),
        "cases_tied": sum(abs(d) <= 1e-9 for d in values),
        "per_outcome_mean_diff": {k: statistics.fmean(v) for k, v in sorted(by_outcome.items())},
        "critical_flags": {
            flag: {arm_a: flag_total(a, flag), arm_b: flag_total(b, flag)}
            for flag in APPROVAL_FLAGS
        },
        "largest_moves": sorted(
            (
                {
                    "id": i,
                    "outcome": a[i]["outcome"],
                    "diff": round(diffs[i], 4),
                    arm_a: round(a[i]["mean"], 4),
                    arm_b: round(b[i]["mean"], 4),
                }
                for i in shared
                if abs(diffs[i]) > 1e-9
            ),
            key=lambda m: m["diff"],
        ),
        "method": (
            "Per-case mean over runs, paired on identical task_sha256; 95% percentile bootstrap "
            f"({resamples} resamples, seed {seed}) over cases and over families (families are "
            "correlated scenario templates, so the family CI is the conservative one); "
            "two-sided sign-flip randomization test on per-case diffs. Repeated runs reduce "
            "within-case noise only; inference is over cases."
        ),
    }


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    od = sub.add_parser("optimizer-data")
    od.add_argument("--train-per-outcome", type=int, default=4)
    od.add_argument("--val-per-outcome", type=int, default=3)
    od.add_argument("--subdir", default="")
    od.add_argument("--exclude-known-defects", action="store_true")
    sub.add_parser("evaluator-source")
    sub.add_parser("review-items")
    sub.add_parser("register-evaluator")
    rr = sub.add_parser("register-rubric")
    rr.add_argument("--rubric", type=Path, default=RUBRIC_PATH)
    run = sub.add_parser("run")
    for name in ("--arm", "--version", "--model", "--split"):
        run.add_argument(name, required=True)
    run.add_argument("--runs", type=int, default=5)
    run.add_argument("--concurrency", type=int, default=3)
    run.add_argument("--limit", type=int)
    summ = sub.add_parser("summarize")
    summ.add_argument("--arm", required=True)
    summ.add_argument("--split", required=True)
    sub.add_parser("quality")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--a", required=True)
    cmp_.add_argument("--b", required=True)
    cmp_.add_argument("--split", required=True)
    cmp_.add_argument("--out")
    args = ap.parse_args()
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if args.cmd == "optimizer-data":
        record = write_optimizer_data(
            args.train_per_outcome, args.val_per_outcome, args.subdir, args.exclude_known_defects
        )
        print(json.dumps(record, indent=2))
    elif args.cmd == "evaluator-source":
        print(evaluator_source())
    elif args.cmd == "review-items":
        out = EVIDENCE / "human-review-items.json"
        out.write_text(json.dumps(review_items(), indent=2) + "\n", encoding="utf-8")
        print(out)
    elif args.cmd == "register-evaluator":
        print(json.dumps(register_evaluator(endpoint)))
    elif args.cmd == "register-rubric":
        print(json.dumps(register_rubric(endpoint, args.rubric)))
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
    elif args.cmd == "quality":
        out = EVIDENCE / "quality.json"
        out.write_text(json.dumps(build_quality(), indent=2) + "\n", encoding="utf-8")
        print(out)
    elif args.cmd == "compare":
        body = json.dumps(paired_compare(args.a, args.b, args.split), indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(body, encoding="utf-8", newline="\n")
        print(body)


if __name__ == "__main__":
    _main()
