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

    def test_agent_deploy_uses_key_vault_keys_without_bearer_precedence(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_agents = workflow.split("  deploy-agents:", 1)[1].split(
            "  # ── corpus-seed", 1
        )[0]

        self.assertIn(
            'azd env set WAYPOINT_WRITER_API_KEY "$writer_key"',
            deploy_agents,
        )
        self.assertIn(
            'azd env set WAYPOINT_READER_API_KEY "$reader_key"',
            deploy_agents,
        )
        self.assertIn('azd env set WAYPOINT_API_SCOPE ""', deploy_agents)
        self.assertNotIn(
            'azd env set WAYPOINT_API_SCOPE "$WP_SCOPE"',
            deploy_agents,
        )

    def test_acceptance_selects_an_invoice_from_the_deployed_work_queue(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        acceptance = workflow.split("  acceptance:", 1)[1]

        self.assertIn('"$API_BASE_URL/api/work"', acceptance)
        self.assertIn("e2e_invoice_id=", acceptance)
        self.assertIn(
            '--input "Run the full invoice-assurance review for invoice ${e2e_invoice_id}."',
            acceptance,
        )
        self.assertIn('--invoice-id "$e2e_invoice_id"', acceptance)
        self.assertNotIn("INV-SUP-001-2026-10", acceptance)

    def test_app_deploy_retries_transient_registry_failures(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_app = workflow.split("  deploy-app:", 1)[1].split(
            "  # ── provision-agents", 1
        )[0]

        self.assertIn("max_attempts=3", deploy_app)
        self.assertIn(
            "aspire deploy --non-interactive 2>&1 | tee aspire-deploy.log",
            deploy_app,
        )
        self.assertIn("connect: connection refused", deploy_app)
        self.assertIn("Transient Azure/registry failure", deploy_app)

    def test_app_redeploy_preserves_msal_redirect_without_invalid_revision(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_app = workflow.split("  deploy-app:", 1)[1].split(
            "  # ── provision-agents", 1
        )[0]
        msal_auth = (ROOT / "apps/waypoint/web/lib/msalAuth.ts").read_text()

        self.assertIn("existing_web_fqdn=", deploy_app)
        self.assertIn(
            'Waypoint__Msal__RedirectUri="https://${existing_web_fqdn}/login"',
            deploy_app,
        )
        self.assertIn(
            "normalizeValue(config.redirectUri) ?? getCurrentOriginLoginUri()",
            msal_auth,
        )

    def test_fabric_provision_wires_aspire_user_assigned_identity(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        fabric = workflow.split("  fabric-provision:", 1)[1].split(
            "  # ── provision-agents", 1
        )[0]

        self.assertIn(".userAssignedIdentities", fabric)
        self.assertIn('WAYPOINT_FABRIC_MI_PRINCIPAL_ID="$app_mi"', fabric)
        self.assertIn("AZURE_CLIENT_ID=", fabric)
        self.assertIn("has no resolvable managed identity", fabric)


if __name__ == "__main__":
    unittest.main()
