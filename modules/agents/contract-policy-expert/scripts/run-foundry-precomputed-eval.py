from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential, ChainedTokenCredential, DefaultAzureCredential


AGENT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    AGENT_ROOT
    / ".foundry"
    / "datasets"
    / "contract-policy-expert-test-foundry-eval"
    / "contract-policy-expert-eval-foundry.jsonl"
)
DEFAULT_OUTPUT = (
    AGENT_ROOT
    / ".foundry"
    / "results"
    / "contract-policy-expert-baseline-precomputed.jsonl"
)


def _credential() -> ChainedTokenCredential:
    return ChainedTokenCredential(
        AzureCliCredential(),
        DefaultAzureCredential(exclude_interactive_browser_credential=True),
    )


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _request_json(
    *,
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {error.code} {detail}") from error


def _agent_endpoint(project_endpoint: str, agent_name: str) -> str:
    return (
        f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
        "/endpoint/protocols/openai/responses?api-version=v1"
    )


def _invoke_agent(
    *,
    endpoint: str,
    token: str,
    query: str,
    timeout: int,
) -> dict[str, Any]:
    return _request_json(
        method="POST",
        url=endpoint,
        token=token,
        timeout=timeout,
        body={"input": [{"role": "user", "content": query}]},
    )


def _create_eval(
    *,
    project_endpoint: str,
    token: str,
    name: str,
    evaluator_name: str,
    evaluator_version: str,
    eval_model: str,
) -> dict[str, Any]:
    return _request_json(
        method="POST",
        url=f"{project_endpoint.rstrip('/')}/openai/v1/evals",
        token=token,
        body={
            "name": name,
            "data_source_config": {
                "type": "custom",
                "item_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "response": {"type": "string"},
                        "expected_behavior": {"type": "string"},
                        "tool_calls": {"type": "array"},
                        "tool_definitions": {"type": "array"},
                    },
                    "required": ["query", "response"],
                },
                "include_sample_schema": False,
            },
            "testing_criteria": [
                {
                    "type": "azure_ai_evaluator",
                    "name": evaluator_name,
                    "evaluator_name": evaluator_name,
                    "evaluator_version": evaluator_version,
                    "initialization_parameters": {
                        "deployment_name": eval_model,
                        "model": eval_model,
                    },
                    "data_mapping": {
                        "query": "{{item.query}}",
                        "response": "{{item.response}}",
                        "tool_calls": "{{item.tool_calls}}",
                        "tool_definitions": "{{item.tool_definitions}}",
                    },
                }
            ],
            "metadata": {
                "azd_agent": "contract-policy-expert",
                "run_mode": "precomputed_responses",
            },
        },
    )


def _create_run(
    *,
    project_endpoint: str,
    token: str,
    eval_id: str,
    run_name: str,
    dataset_id: str,
) -> dict[str, Any]:
    return _request_json(
        method="POST",
        url=f"{project_endpoint.rstrip('/')}/openai/v1/evals/{eval_id}/runs",
        token=token,
        body={
            "name": run_name,
            "data_source": {
                "type": "jsonl",
                "source": {
                    "type": "file_id",
                    "id": dataset_id,
                },
            },
            "metadata": {
                "azd_agent": "contract-policy-expert",
                "trigger_type": "oneoff",
                "run_mode": "precomputed_responses",
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CPE eval with precomputed hosted-agent responses."
    )
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--agent-name", default="contract-policy-expert")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--eval-name", default="contract-policy-expert-baseline")
    parser.add_argument("--run-name", default="contract-policy-expert-baseline")
    parser.add_argument("--dataset-name", default="contract-policy-expert-baseline-responses")
    parser.add_argument("--dataset-version", default=None)
    parser.add_argument("--evaluator-name", default="contract-policy-expert-generated-rubric")
    parser.add_argument("--evaluator-version", default="7")
    parser.add_argument("--eval-model", default="gpt-6-astra")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--skip-invoke", action="store_true")
    parser.add_argument("--skip-submit", action="store_true")
    args = parser.parse_args()

    credential = _credential()
    token = credential.get_token("https://ai.azure.com/.default").token

    if not args.skip_invoke:
        rows = _read_jsonl(args.input, limit=args.limit)
        endpoint = _agent_endpoint(args.project_endpoint, args.agent_name)
        output_rows = []
        for index, row in enumerate(rows, start=1):
            query = row["query"]
            started = time.time()
            response = _invoke_agent(
                endpoint=endpoint,
                token=token,
                query=query,
                timeout=args.timeout,
            )
            elapsed = round(time.time() - started, 3)
            output_rows.append(
                {
                    "id": row.get("id"),
                    "query": query,
                    "response": response.get("output_text", ""),
                    "expected_behavior": row.get("expected_behavior", ""),
                    "ground_truth": row.get("ground_truth"),
                    "metadata": row.get("metadata", {}),
                    "tool_calls": [],
                    "tool_definitions": [],
                    "response_id": response.get("id"),
                    "response_status": response.get("status"),
                    "elapsed_seconds": elapsed,
                }
            )
            print(
                json.dumps(
                    {
                        "row": index,
                        "id": row.get("id"),
                        "response_id": response.get("id"),
                        "status": response.get("status"),
                        "elapsed_seconds": elapsed,
                    },
                    sort_keys=True,
                )
            )
        _write_jsonl(args.output, output_rows)

    if args.skip_submit:
        print(json.dumps({"output": str(args.output)}, indent=2))
        return

    version = args.dataset_version or str(int(time.time()))
    with AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project_client:
        dataset = project_client.datasets.upload_file(
            name=args.dataset_name,
            version=version,
            file_path=str(args.output),
        )

    eval_record = _create_eval(
        project_endpoint=args.project_endpoint,
        token=token,
        name=args.eval_name,
        evaluator_name=args.evaluator_name,
        evaluator_version=args.evaluator_version,
        eval_model=args.eval_model,
    )
    run = _create_run(
        project_endpoint=args.project_endpoint,
        token=token,
        eval_id=eval_record["id"],
        run_name=args.run_name,
        dataset_id=dataset.id,
    )
    print(
        json.dumps(
            {
                "dataset_id": dataset.id,
                "dataset_name": args.dataset_name,
                "dataset_version": version,
                "eval_id": eval_record["id"],
                "run_id": run["id"],
                "run_status": run["status"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
