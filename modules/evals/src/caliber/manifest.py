from __future__ import annotations

from typing import Any

from .paths import repo_root


def build_manifest() -> dict[str, Any]:
    root = repo_root()
    return {
        "project": "caliber",
        "purpose": "Fine-tuning support tools for Forge agents.",
        "paths": {
            "package": str(root / "src" / "caliber"),
            "datasets": str(root / "datasets"),
            "graders": str(root / "graders"),
            "runs": str(root / "runs"),
            "outputs": str(root / "outputs"),
            "demo_flow": str(root / "docs" / "DEMO_FLOW.md"),
        },
        "strategy": {
            "sequence": [
                "foundry_generated_rubrics",
                "baseline_evals",
                "agent_optimizer_for_accuracy",
                "rft_for_cheaper_model_cost",
                "before_after_cost_quality_gate",
            ],
            "summary": (
                "Use Foundry/azd to generate rubrics and run baseline evals, use Agent "
                "Optimizer to get the best hosted-agent behavior, then use RFT to preserve "
                "that behavior on a cheaper model."
            ),
        },
        "fine_tuning_candidates": [
            {
                "priority": 1,
                "agent": "contract-policy-expert",
                "forge_agent": "contract-policy-expert",
                "status": "hosted_foundryiq_first_candidate",
                "forge_pr": "caldova/waypoint#24",
                "deployment_shape": {
                    "current": "hosted_responses_agent",
                    "prompt_enabled": False,
                    "hosted_enabled": True,
                    "azure_yaml_service": True,
                    "responses_endpoint_env": "FOUNDRYIQ_EXPERT_ENDPOINT",
                    "deploy_command": (
                        "azd deploy contract-policy-expert -C <forge-checkout> -e <env>"
                    ),
                },
                "forge_sources": {
                    "agent_root": "agents/contract-policy-expert",
                    "instructions": "agents/contract-policy-expert/prompt.md",
                    "azure_yaml_service": "contract-policy-expert",
                },
                "pacioli_lane": "foundryiq",
                "grounding": {
                    "plane": "foundryiq",
                    "expected_tooling": "Forge-hosted FoundryIQ contract/policy retrieval",
                    "current_seed_source": (
                        "Ledgerfield contract, policy, invoice, and scenario corpus"
                    ),
                },
                "ledgerfield_sources": {
                    "scenarios": "data/scenarios/invoice-assurance-scenarios.json",
                    "invoices": "data/invoices/supplier-invoices.json",
                    "suppliers": "data/suppliers/cmo_suppliers.json",
                    "contracts": "data/contracts/source-markdown/*.md",
                    "policies": "data/policies/source-markdown/*.md",
                },
                "caliber_assets": {
                    "datasets": "datasets/contract-policy-expert",
                    "grader": (
                        "graders/contract-policy-expert/contract_policy_evidence_grader.py"
                    ),
                    "generated_eval_runs": "runs/eval-results/contract-policy-expert",
                    "generated_rft_packages": "runs/rft/contract-policy-expert",
                    "demo_flow": "docs/DEMO_FLOW.md",
                },
                "caliber_owns": [
                    "dataset generation and curation",
                    "Foundry-generated rubric/evaluator lineage",
                    "eval output-item export and analysis",
                    "Agent Optimizer candidate output metadata",
                    "RFT candidate data and cost/quality promotion metadata",
                ],
                "forge_owns": [
                    "hosted agent runtime source",
                    "FoundryIQ tool and connection wiring",
                    "deployment through azure.yaml",
                    "consumption of promoted canonical gates",
                ],
                "why_first": (
                    "It is the hosted FoundryIQ evidence expert from Forge PR #24 and the best "
                    "initial lane for contract/policy grounded evals, optimizer, and RFT cost "
                    "optimization."
                ),
                "workflow": [
                    {
                        "stage": "rubric_generation",
                        "owner": "Foundry via azd, orchestrated by Caliber",
                        "command": (
                            "azd ai agent eval generate --agent contract-policy-expert "
                            "--dataset <eval-jsonl> --gen-instruction-file "
                            "<forge>\\agents\\contract-policy-expert\\prompt.md"
                        ),
                    },
                    {
                        "stage": "baseline_eval",
                        "owner": "Foundry via azd, output-items exported by Caliber",
                        "command": "azd ai agent eval run --config <generated-eval-yaml>",
                    },
                    {
                        "stage": "agent_optimizer",
                        "owner": "Forge runtime plus Foundry optimizer, tracked by Caliber",
                        "purpose": "Improve hosted-agent accuracy before model fine-tuning.",
                    },
                    {
                        "stage": "rft_cost_optimization",
                        "owner": "Caliber",
                        "purpose": (
                            "Move optimized behavior to a cheaper model after the optimizer "
                            "establishes the quality target."
                        ),
                    },
                ],
            },
            {
                "priority": 2,
                "agent": "assurance-analyst",
                "forge_agent": "assurance-analyst",
                "status": "preserved_calibration_context",
                "caliber_assets": {
                    "datasets": "datasets/assurance-analyst",
                    "grader": "graders/assurance-analyst/assurance_evidence_grader.py",
                    "output_items": "runs/eval-results/assurance-analyst/output-items.jsonl",
                },
                "completed_eval": {
                    "eval_id": "eval_781387f48ae541c4baf0e7963c7905a5",
                    "run_id": "evalrun_3af04c6d8a1e49dcb7d274a7891a38f8",
                    "total": 24,
                    "passed": 4,
                    "failed": 20,
                    "errored": 0,
                },
                "strict_grader_calibration": {
                    "min": 0.0,
                    "max": 0.43,
                    "avg": 0.069,
                    "decision": (
                        "Useful as calibration and roadmap context, but not the first real "
                        "hosted FoundryIQ candidate after Forge PR #24."
                    ),
                },
            },
        ],
        "commands": [
            "uv run caliber doctor",
            "uv run caliber manifest",
            "uv run caliber inspect-forge --path <forge-checkout>",
            "uv run caliber datasets contract-policy build --ledgerfield-path "
            "<ledgerfield-checkout> --agent contract-policy-expert --variants-per-scenario 8",
            "uv run caliber datasets contract-policy expand-contracts --ledgerfield-path "
            "<ledgerfield-checkout> --agent contract-policy-expert --variants-per-clause 3",
            "azd ai agent eval generate --agent contract-policy-expert --dataset <eval-jsonl>",
            "azd ai agent eval run --config <generated-eval-yaml>",
            "uv run caliber eval export-output-items --project-endpoint <endpoint> "
            "--eval-id <eval-id> --run-id <run-id> --out <output.jsonl>",
            "uv run caliber grader calibrate --dataset <eval.jsonl> "
            "--outputs <output-items.jsonl> --grader <grader.py>",
            "uv run caliber optimizer plan --forge-path <forge-checkout> "
            "--agent contract-policy-expert --dataset <eval.jsonl> --eval-config <eval.yaml>",
            "azd ai agent optimize --agent contract-policy-expert --config <eval.yaml>",
            "uv run caliber rft plan --train <train.jsonl> --validation <val.jsonl> "
            "--grader <grader.py> --base-model <cheap-model> --project-endpoint <endpoint>",
            "uv run caliber rft package --train <train.jsonl> --validation <val.jsonl> "
            "--grader <grader.py> --agent contract-policy-expert --base-model <cheap-model>",
        ],
        "external_inputs": {
            "forge": "Read-only source for hosted agent runtime unless explicitly modifying Forge.",
            "ledgerfield": (
                "Read-only source for canonical contract, policy, invoice, and scenario data."
            ),
            "reinforcement_learning": "Reference for Foundry eval/RFT lifecycle scripts.",
        },
    }
