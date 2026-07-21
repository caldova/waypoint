import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class AgentModelConfigurationTests(unittest.TestCase):
    def test_root_deployment_defaults_to_foundryiq_only(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        manifest = json.loads(
            (ROOT / "tools/deploy/deployment.manifest.json").read_text()
        )
        matrix = workflow.split("strategy:", 1)[1].split("defaults:", 1)[0]

        self.assertEqual(
            manifest["deployment"]["feature_lanes"],
            {
                "workiq": False,
                "webiq": False,
                "foundryiq": True,
                "fabriciq": False,
            },
        )
        self.assertEqual(
            manifest["expected_components"]["agents"],
            [
                "invoice-analyst",
                "assurance-orchestrator",
                "contract-policy-expert",
                "waypoint-recorder",
            ],
        )
        self.assertIn(
            "agent: ${{ fromJSON(needs.validate.outputs.agent_matrix) }}",
            matrix,
        )
        self.assertEqual(
            manifest["expected_components"]["optional_agents"],
            [
                "collaboration-evidence-expert",
                "market-evidence-expert",
                "operations-data-expert",
            ],
        )
        self.assertIn("inputs.workiq_enabled", workflow)
        self.assertIn("inputs.webiq_enabled", workflow)
        self.assertIn("inputs.fabriciq_enabled", workflow)
        self.assertIn(
            'azd env set ENABLE_WORKIQ_CONNECTIONS "${{ inputs.workiq_enabled }}"',
            workflow,
        )
        self.assertIn(
            'SELECTED_AGENTS: ${{ needs.validate.outputs.agent_matrix }}',
            workflow,
        )

    def test_orchestrator_defaults_match_foundryiq_only_fleet(self) -> None:
        expert_clients = (
            ROOT
            / "modules/agents/agents/assurance-orchestrator/expert_clients.py"
        ).read_text()

        self.assertIn('"workiq": False', expert_clients)
        self.assertIn('"webiq": False', expert_clients)
        self.assertIn('"foundryiq": True', expert_clients)
        self.assertIn('"fabriciq": False', expert_clients)

    def test_content_understanding_reuses_primary_completion_model(self) -> None:
        bicep = (ROOT / "modules/agents/infra/main.bicep").read_text()
        parameters = json.loads(
            (ROOT / "modules/agents/infra/main.parameters.json").read_text()
        )["parameters"]

        self.assertNotIn("gpt-4.1", bicep)
        self.assertNotIn("contentUnderstandingCompletionDeploymentName", parameters)
        self.assertNotIn("contentUnderstandingCompletionModelName", parameters)
        self.assertIn(
            "output CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME string = "
            "modelDeploymentName",
            bicep,
        )
        self.assertIn(
            "output CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME string = modelName",
            bicep,
        )

    def test_project_creation_is_owned_by_bootstrap_boundary(self) -> None:
        project_bicep = (
            ROOT / "modules/agents/infra/core/ai/ai-project.bicep"
        ).read_text()
        bootstrap = (
            ROOT / "modules/agents/scripts/bootstrap_foundry_account.sh"
        ).read_text()

        self.assertIn(
            "resource project 'projects@2026-03-01' existing",
            project_bicep,
        )
        self.assertIn(
            "resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-09-01' "
            "existing",
            project_bicep,
        )
        self.assertIn("--method put", bootstrap)
        self.assertIn("/projects/${project_name}", bootstrap)
        self.assertIn("az cognitiveservices account deployment create", bootstrap)

    def test_storage_module_owns_deployment_principal_blob_role(self) -> None:
        storage_bicep = (
            ROOT / "modules/agents/infra/core/storage/storage.bicep"
        ).read_text()
        search_bicep = (
            ROOT / "modules/agents/infra/core/search/azure_ai_search.bicep"
        ).read_text()

        self.assertIn("resource userStorageRoleAssignment", storage_bicep)
        self.assertNotIn("userToStorageRoleAssignment", search_bicep)

    def test_foundry_provision_initializes_contracts_kb_before_upload(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        provision = workflow.split("  provision-agents:", 1)[1].split(
            "  # ── deploy-agents", 1
        )[0]
        upload = workflow.split("  contracts-kb-upload:", 1)[1].split(
            "  # ── seed-import", 1
        )[0]

        self.assertIn("Initialize contracts knowledge base", provision)
        self.assertIn(
            "python scripts/initialize_contracts_kb.py --skip-upload",
            provision,
        )
        self.assertIn("if: ${{ inputs.foundryiq_enabled }}", provision)
        self.assertIn("needs: [validate, provision-agents]", upload)


if __name__ == "__main__":
    unittest.main()
