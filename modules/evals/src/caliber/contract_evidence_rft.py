"""MAI-Code-2-Flash RFT for contract-evidence-analyst, following Alaska's e6 recipe.

Rows: developer = the served instructions (the applied optimizer candidate), user = the
benchmark task verbatim (exactly what the hosted agent receives), plus the frozen ``reference``
the grader reads. The grader is the frozen v1 grader source unchanged (sandbox-checked).
Train = benchmark ``train``, validation = benchmark ``validation``; ``dev_eval`` and
``final_test`` never enter the package (checked by id and task hash).

    python -m caliber.contract_evidence_rft package --instructions <md>  # free, local
    python -m caliber.contract_evidence_rft validate-grader              # free, remote
    python -m caliber.contract_evidence_rft upload                       # free, remote
    python -m caliber.contract_evidence_rft submit --approve-spend       # billable
    python -m caliber.contract_evidence_rft watch <ftjob-id>             # read-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from caliber.contract_evidence_benchmark import load_split
from caliber.contract_evidence_eval import (
    DATASET_DIR,
    EVIDENCE,
    GRADER_PATH,
    PASS_THRESHOLD,
    REPO,
    load_grader,
)

OUT = EVIDENCE / "mai2-rft"
BASE_MODEL = "mai-code-2-flash-2026-11-17"
SUFFIX = "contract-evidence-mai2-r1"
# Alaska e6 (payload.e6.json): seed, lr 2, 3 epochs, eval every 2 steps, low effort, developer tier.
# eval_samples is capped at the validation row count (Alaska used 50 against 154 validation rows).
HYPERPARAMETERS = {
    "eval_interval": 2,
    "compute_multiplier": 1,
    "reasoning_effort": "low",
    "n_epochs": 3,
    "learning_rate_multiplier": 2,
}
SEED = 1266282111
BANNED = ("compile(", "exec(", "eval(", "__import__(", "open(")
HELD_OUT = ("dev_eval", "final_test")
DEV_TIER_USD_PER_HOUR = 40.0


def _rel(path: Path) -> str:
    resolved = path.resolve()
    return (
        resolved.relative_to(REPO).as_posix()
        if resolved.is_relative_to(REPO)
        else resolved.as_posix()
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def grader_source() -> str:
    source = GRADER_PATH.read_text(encoding="utf-8")
    found = [
        b for b in BANNED if re.search(r"(?<![\w.])" + re.escape(b), source) or f".{b}" in source
    ]
    if found:
        raise ValueError(f"grader uses sandbox-banned calls: {found}")
    if source.count("\ndef grade(") != 1:
        raise ValueError("grader must define exactly one top-level grade(sample, item)")
    return source


def rft_row(row: dict[str, Any], split: str, instructions: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "developer", "content": instructions},
            {"role": "user", "content": row["task"]},
        ],
        "reference": row["reference"],
        "id": row["id"],
        "metadata": {
            "family": row["family"],
            "outcome": row["outcome"],
            "split": split,
            "review_status": row["metadata"]["review_status"],
        },
    }


def package(instructions_path: Path, out: Path = OUT) -> dict[str, Any]:
    instructions = instructions_path.read_text(encoding="utf-8").strip()
    source = grader_source()
    grader = load_grader()
    held = {s: load_split(DATASET_DIR, s) for s in HELD_OUT}
    held_ids = {r["id"] for rows in held.values() for r in rows}
    held_tasks = {_sha(r["task"].encode()) for rows in held.values() for r in rows}
    out.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Any] = {}
    parity: dict[str, Any] = {}
    for split in ("train", "validation"):
        rows = [rft_row(r, split, instructions) for r in load_split(DATASET_DIR, split)]
        leaked = [
            r["id"]
            for r in rows
            if r["id"] in held_ids or _sha(r["messages"][-1]["content"].encode()) in held_tasks
        ]
        if leaked:
            raise ValueError(f"{split} rows overlap held-out splits: {leaked[:5]}")
        scores = [
            grader.grade({"output_text": json.dumps(r["reference"]["reference_output"])}, r)
            for r in rows
        ]
        empty = [grader.grade({"output_text": "{}"}, r) for r in rows]
        parity[split] = {
            "rows": len(rows),
            "min_gold": round(min(scores), 4),
            "gold_below_threshold": sum(s < PASS_THRESHOLD for s in scores),
            "max_empty_object": round(max(empty), 4),
        }
        if (
            parity[split]["gold_below_threshold"]
            or parity[split]["max_empty_object"] >= PASS_THRESHOLD
        ):
            raise ValueError(f"gold/empty parity failed on {split}: {parity[split]}")
        body = "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows
        ).encode("utf-8")
        path = out / f"contract-evidence-rft-{split}.jsonl"
        path.write_bytes(body)
        artifacts[split] = {"path": _rel(path), "rows": len(rows), "sha256": _sha(body)}
    (out / "grader.py").write_text(source, encoding="utf-8", newline="\n")
    (out / "system-prompt.md").write_text(instructions + "\n", encoding="utf-8", newline="\n")
    payload = {
        "model": BASE_MODEL,
        "training_file": "<set by upload>",
        "validation_file": "<set by upload>",
        "suffix": SUFFIX,
        "seed": SEED,
        "trainingType": "developerTier",
        "method": {
            "type": "reinforcement",
            "reinforcement": {
                "hyperparameters": {
                    **HYPERPARAMETERS,
                    "eval_samples": artifacts["validation"]["rows"],
                },
                "grader": {
                    "type": "python",
                    "image_tag": "2025-05-08",
                    "source": source,
                    "pass_threshold": PASS_THRESHOLD,
                },
            },
        },
    }
    (out / "payload.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "base_model": BASE_MODEL,
        "suffix": SUFFIX,
        "seed": SEED,
        "recipe": "Alaska payload.e6.json",
        "instructions": _rel(instructions_path),
        "instructions_sha256": _sha(instructions.encode()),
        "grader": {
            "path": _rel(GRADER_PATH),
            "sha256": _sha(source.encode()),
            "pass_threshold": PASS_THRESHOLD,
        },
        "artifacts": artifacts,
        "gold_parity": parity,
        "held_out_excluded": {s: len(rows) for s, rows in held.items()},
        "labels": "synthetic, pending_human_review",
        "cost_model": {
            "tier": "developer",
            "usd_per_hour": DEV_TIER_USD_PER_HOUR,
            "note": "Alaska e6 trained ~3 h after queueing; estimate 2-6 h => $80-240",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


# ---------------------------------------------------------------- remote (explicit commands only)


def _endpoint() -> str:
    return os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/") + "/openai/v1"


_TOKEN: dict[str, Any] = {}


def _token() -> str:
    from azure.identity import AzureCliCredential

    cached = _TOKEN.get("token")
    if cached is None or cached.expires_on - time.time() < 300:
        cached = AzureCliCredential(process_timeout=120).get_token("https://ai.azure.com/.default")
        _TOKEN["token"] = cached
    return cached.token


def _call(method: str, path: str, body: Any = None, raw: bool = False) -> Any:
    req = urllib.request.Request(
        f"{_endpoint()}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
            return data if raw else json.loads(data or b"{}")
    except urllib.error.HTTPError as err:
        return {"_http_status": err.code, "_error": err.read().decode(errors="replace")}


def _upload(path: Path) -> dict[str, Any]:
    boundary = uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nfine-tune\r\n'
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        f"{_endpoint()}/files",
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def _write(name: str, data: Any) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def validate_grader() -> dict[str, Any]:
    grader = json.loads((OUT / "payload.json").read_text(encoding="utf-8"))["method"][
        "reinforcement"
    ]["grader"]
    result = _call("POST", "/fine_tuning/alpha/graders/validate", {"grader": grader})
    _write("grader-validate.json", result)
    return result


def upload() -> dict[str, Any]:
    payload = json.loads((OUT / "payload.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, Any] = {}
    for split, key in (("train", "training_file"), ("validation", "validation_file")):
        path = REPO / manifest["artifacts"][split]["path"]
        if _sha(path.read_bytes()) != manifest["artifacts"][split]["sha256"]:
            sys.exit(f"{path} changed since packaging")
        uploaded = _upload(path)
        for _ in range(90):
            status = _call("GET", f"/files/{uploaded['id']}").get("status")
            if status in ("processed", "error"):
                break
            time.sleep(10)
        if status != "processed":
            sys.exit(f"{uploaded['id']} status {status}")
        payload[key] = uploaded["id"]
        files[split] = {
            "id": uploaded["id"],
            "status": status,
            "sha256": manifest["artifacts"][split]["sha256"],
        }
    _write("payload.json", payload)
    _write("upload.json", files)
    return files


def submit(approve: bool) -> dict[str, Any]:
    if not approve:
        sys.exit("billable: pass --approve-spend")
    payload = json.loads((OUT / "payload.json").read_text(encoding="utf-8"))
    if payload["training_file"].startswith("<"):
        sys.exit("run upload first")
    job = _call("POST", "/fine_tuning/jobs", payload)
    _write("job.submitted.json", job)
    return job


def watch(job_id: str) -> dict[str, Any]:
    job = _call("GET", f"/fine_tuning/jobs/{job_id}")
    events = _call("GET", f"/fine_tuning/jobs/{job_id}/events?limit=100").get("data", [])
    _write(
        "job.latest.json",
        {k: v for k, v in job.items() if k != "method"}
        | {
            "hyperparameters": job.get("method", {}).get("reinforcement", {}).get("hyperparameters")
        },
    )
    _write("job.events.json", events)
    print(f"{job_id} {job.get('status')} model={job.get('fine_tuned_model')}")
    for e in reversed(events[:12]):
        print(f"  {time.strftime('%H:%M:%SZ', time.gmtime(e['created_at']))} {e.get('message')}")
    return job


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("package")
    p.add_argument("--instructions", type=Path, required=True)
    sub.add_parser("validate-grader")
    sub.add_parser("upload")
    s = sub.add_parser("submit")
    s.add_argument("--approve-spend", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("job_id")
    a = ap.parse_args()
    if a.cmd == "package":
        print(json.dumps(package(a.instructions), indent=1))
    elif a.cmd == "validate-grader":
        print(json.dumps(validate_grader(), indent=1)[:2000])
    elif a.cmd == "upload":
        print(json.dumps(upload(), indent=1))
    elif a.cmd == "submit":
        job = submit(a.approve_spend)
        print(job.get("id"), job.get("status"), job.get("_error", ""))
    else:
        watch(a.job_id)


if __name__ == "__main__":
    main()
