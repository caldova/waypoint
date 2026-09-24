from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from azure.ai.agentserver.optimization import load_config
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentOptimizationDatasetItem,
    AgentOptimizationEvaluatorRef,
    AgentOptimizationInlineDatasetInput,
    AgentOptimizationJob,
    AgentOptimizationJobInputs,
    AgentOptimizationOptions,
    OptimizedAgentIdentifier,
)
from azure.identity import AzureCliCredential, ChainedTokenCredential, DefaultAzureCredential


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    AGENT_ROOT
    / ".."
    / ".."
    / "evals"
    / "datasets"
    / "contract-policy-expert"
    / "contract-policy-expert-train.jsonl"
)


def _eval_config_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    defaults: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("eval_model:"):
            defaults["eval_model"] = stripped.split(":", 1)[1].strip().strip("\"'")
        elif stripped.startswith("optimization_model:"):
            defaults["optimization_model"] = (
                stripped.split(":", 1)[1].strip().strip("\"'")
            )
        elif stripped == "evaluators:":
            for candidate in lines[index + 1 :]:
                candidate = candidate.strip()
                if candidate.startswith("name:"):
                    defaults["evaluator_name"] = (
                        candidate.split(":", 1)[1].strip().strip("\"'")
                    )
                elif candidate.startswith("version:"):
                    defaults["evaluator_version"] = (
                        candidate.split(":", 1)[1].strip().strip("\"'")
                    )
                    break
                elif candidate and not candidate.startswith("-"):
                    break
    return defaults


def _read_jsonl(path: Path, *, max_items: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if len(rows) >= max_items:
                break
    return rows


def _row_to_query(row: dict[str, Any]) -> str:
    messages = row.get("messages")
    if isinstance(messages, list):
        parts = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "message")
            content = str(message.get("content", "")).strip()
            if content:
                parts.append(f"{role}: {content}")
        if parts:
            return "\n\n".join(parts)
    return json.dumps(row, ensure_ascii=False)


def _row_to_ground_truth(row: dict[str, Any]) -> str:
    expected = row.get("expected")
    if isinstance(expected, dict) and expected.get("text"):
        return str(expected["text"])
    expected_json = row.get("expected_output_json")
    if expected_json:
        return json.dumps(expected_json, ensure_ascii=False)
    return str(row.get("ground_truth", ""))


def _load_inline_dataset(path: Path, *, max_items: int) -> AgentOptimizationInlineDatasetInput:
    items = [
        AgentOptimizationDatasetItem(
            query=_row_to_query(row),
            ground_truth=_row_to_ground_truth(row),
        )
        for row in _read_jsonl(path, max_items=max_items)
    ]
    if not items:
        raise ValueError(f"Dataset has no rows: {path}")
    return AgentOptimizationInlineDatasetInput(dataset_items=items)


def _credential() -> ChainedTokenCredential:
    return ChainedTokenCredential(
        AzureCliCredential(),
        DefaultAzureCredential(exclude_interactive_browser_credential=True),
    )


def _job_summary(job: Any) -> dict[str, Any]:
    data = job.as_dict() if hasattr(job, "as_dict") else {}
    result = data.get("result") or {}
    candidates = [
        {
            "candidate_id": candidate.get("candidate_id"),
            "name": candidate.get("name"),
            "avg_score": candidate.get("avg_score"),
            "avg_duration_seconds": candidate.get("avg_duration_seconds"),
            "eval_run_id": candidate.get("eval_run_id"),
            "mutations": sorted((candidate.get("mutations") or {}).keys())
            if isinstance(candidate.get("mutations"), dict)
            else [],
        }
        for candidate in result.get("candidates") or []
    ]
    best = None
    scored_candidates = [
        candidate for candidate in candidates if candidate.get("avg_score") is not None
    ]
    if scored_candidates:
        best = max(scored_candidates, key=lambda candidate: candidate["avg_score"])

    return {
        "job_id": getattr(job, "id", None) or data.get("id"),
        "status": str(getattr(job, "status", data.get("status"))),
        "progress": data.get("progress"),
        "error": data.get("error"),
        "baseline": result.get("baseline"),
        "best": best,
        "candidates": candidates,
        "token_usage": result.get("token_usage"),
        "latency_usage": result.get("latency_usage"),
    }


def _list_jobs(project_client: AIProjectClient, *, agent_name: str, limit: int) -> list[Any]:
    return list(
        project_client.beta.agents.list_optimization_jobs(
            limit=limit,
            order="desc",
            agent_name=agent_name,
        )
    )


def _recover_latest_job_id(
    project_client: AIProjectClient, *, agent_name: str
) -> str | None:
    jobs = _list_jobs(project_client, agent_name=agent_name, limit=1)
    if not jobs:
        return None
    return getattr(jobs[0], "id", None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit CPE Foundry optimizer job via SDK.")
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--agent-name", default="contract-policy-expert")
    parser.add_argument("--eval-config", type=Path, default=AGENT_ROOT / "eval.yaml")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--evaluator-name")
    parser.add_argument("--evaluator-version")
    parser.add_argument("--eval-model")
    parser.add_argument("--optimization-model")
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--max-items", type=int, default=15)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-interval", type=int, default=20)
    parser.add_argument("--list", action="store_true", help="List recent optimizer jobs.")
    parser.add_argument("--status-job-id", help="Print status/results for an optimizer job.")
    parser.add_argument("--limit", type=int, default=10, help="Recent job count for --list.")
    args = parser.parse_args()
    eval_defaults = _eval_config_defaults(args.eval_config)
    evaluator_name = (
        args.evaluator_name
        or eval_defaults.get("evaluator_name")
        or "contract-policy-expert-generated-rubric"
    )
    evaluator_version = args.evaluator_version or eval_defaults.get("evaluator_version")
    eval_model = args.eval_model or eval_defaults.get("eval_model") or "gpt-6-astra"
    optimization_model = args.optimization_model or "gpt-5.5"

    with AIProjectClient(
        endpoint=args.project_endpoint,
        credential=_credential(),
        allow_preview=True,
    ) as project_client:
        if args.list:
            jobs = _list_jobs(
                project_client,
                agent_name=args.agent_name,
                limit=args.limit,
            )
            print(
                json.dumps(
                    [
                        {
                            "job_id": getattr(job, "id", None),
                            "status": str(getattr(job, "status", None)),
                            "created_at": str(getattr(job, "created_at", None)),
                            "agent_name": getattr(job, "agent_name", None),
                        }
                        for job in jobs
                    ],
                    indent=2,
                    default=str,
                )
            )
            return

        if args.status_job_id:
            job = project_client.beta.agents.get_optimization_job(args.status_job_id)
            print(json.dumps(_job_summary(job), indent=2, default=str))
            return

        config = load_config(config_dir=str(AGENT_ROOT / ".agent_configs"))
        if config is None or not config.instructions:
            raise RuntimeError("Baseline optimization config did not resolve instructions.")

        optimization_config: dict[str, Any] = {"system_prompt": config.instructions}
        if config.tool_definitions:
            optimization_config["tools"] = config.tool_definitions
        if getattr(config, "skills", None):
            optimization_config["skills"] = [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "body": skill.body,
                }
                for skill in config.skills
            ]

        dataset_path = args.dataset.resolve()
        train_dataset = _load_inline_dataset(dataset_path, max_items=args.max_items)
        if not evaluator_version:
            raise RuntimeError(
                "Evaluator version was not supplied and could not be read from eval.yaml. "
                "Pass --evaluator-version after generating the rubric in this tenant."
            )

        job = AgentOptimizationJob(
            inputs=AgentOptimizationJobInputs(
                agent=OptimizedAgentIdentifier(agent_name=args.agent_name),
                train_dataset=train_dataset,
                evaluators=[
                    AgentOptimizationEvaluatorRef(
                        name=evaluator_name,
                        version=evaluator_version,
                    )
                ],
                options=AgentOptimizationOptions(
                    max_candidates=args.max_candidates,
                    eval_model=eval_model,
                    optimization_model=optimization_model,
                    optimization_config=optimization_config,
                ),
            )
        )

        poller = project_client.beta.agents.begin_create_optimization_job(job=job)
        job_id = getattr(getattr(poller, "details", None), "job_id", None)
        if not job_id:
            job_id = _recover_latest_job_id(project_client, agent_name=args.agent_name)
        print(json.dumps({"job_id": job_id, "status": poller.status()}, indent=2))
        if not args.wait:
            return
        while not poller.done():
            print(json.dumps({"job_id": job_id, "status": poller.status()}))
            time.sleep(args.poll_interval)
        if job_id:
            result = project_client.beta.agents.get_optimization_job(job_id)
        else:
            result = poller.result()
        print(json.dumps(_job_summary(result), indent=2, default=str))


if __name__ == "__main__":
    main()
