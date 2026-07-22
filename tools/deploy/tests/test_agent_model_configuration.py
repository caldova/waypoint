import json
import os
import subprocess
import tempfile
import textwrap
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
        self.assertIn(
            "APP_AZURE_LOCATION: ${{ inputs.app_location || vars.WAYPOINT_APP_LOCATION",
            workflow,
        )
        fabric_input = workflow.split("      fabric_provision_enabled:", 1)[1].split(
            "      workiq_enabled:", 1
        )[0]
        self.assertIn("default: false", fabric_input)
        deploy_app = workflow.split("  deploy-app:", 1)[1].split(
            "  # ── fabric-provision", 1
        )[0]
        provision_agents = workflow.split("  provision-agents:", 1)[1].split(
            "  # ── deploy-agents", 1
        )[0]
        self.assertIn("Azure__Location: ${{ env.APP_AZURE_LOCATION }}", deploy_app)
        self.assertIn('azd env set AZURE_LOCATION "$AZURE_LOCATION"', provision_agents)
        self.assertNotIn("APP_AZURE_LOCATION", provision_agents)
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
        self.assertIn("needs: [plan, validate, provision-agents]", upload)

    def test_agent_deploy_uses_key_vault_keys_without_bearer_precedence(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_agents = workflow.split("  deploy-agents:", 1)[1].split(
            "  # ── onelake-upload", 1
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

    def test_agent_deploy_skips_unchanged_active_versions(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_agents = workflow.split("  deploy-agents:", 1)[1].split(
            "  # ── onelake-upload", 1
        )[0]

        self.assertIn("Compare desired agent deployment state", deploy_agents)
        self.assertIn("git ls-files -z", deploy_agents)
        self.assertIn("azd env get-values", deploy_agents)
        self.assertIn("Microsoft.BotService/botServices", deploy_agents)
        self.assertIn("waypoint_agent_hash", deploy_agents)
        self.assertIn("waypoint_agent_version", deploy_agents)
        self.assertIn("agent_exists=true", deploy_agents)
        self.assertIn("--max-time 30", deploy_agents)
        self.assertIn(
            "if: steps.agent-state.outputs.needs_deploy == 'true'",
            deploy_agents,
        )
        self.assertIn("az tag update", deploy_agents)
        self.assertIn("--operation Merge", deploy_agents)

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

        self.assertIn(
            "bash ../../tools/deploy/scripts/aspire_deploy.sh",
            deploy_app,
        )
        aspire_deploy = (
            ROOT / "tools/deploy/scripts/aspire_deploy.sh"
        ).read_text()
        self.assertIn("ASPIRE_DEPLOY_MAX_ATTEMPTS:-2", aspire_deploy)
        self.assertIn("aspire deploy --non-interactive", aspire_deploy)
        self.assertIn("connect: connection refused", aspire_deploy)
        self.assertIn("Transient Azure/registry failure", aspire_deploy)
        self.assertIn("ASPIRE_DEPLOY_ATTEMPT_TIMEOUT:-12m", aspire_deploy)
        self.assertIn("for check in $(seq 1 20)", aspire_deploy)
        self.assertIn("timeout-minutes: 30", deploy_app)
        self.assertIn("properties.deploymentErrors", aspire_deploy)
        self.assertIn("AKSCapacityHeavyUsage", aspire_deploy)
        self.assertIn("az deployment group cancel", aspire_deploy)
        self.assertIn("az containerapp env delete", aspire_deploy)
        self.assertIn("Refusing to delete capacity-failed environment", aspire_deploy)
        self.assertIn("unable to pull image using Managed identity", aspire_deploy)
        self.assertIn("failed to resolve registry .*no such host", aspire_deploy)
        self.assertIn("ensure_acr_pull_assignment", aspire_deploy)
        self.assertIn("--assignee-principal-type ServicePrincipal", aspire_deploy)
        self.assertIn("--role AcrPull", aspire_deploy)
        self.assertIn('--name "$role_assignment_name"', aspire_deploy)
        self.assertIn("Microsoft.Authorization/roleAssignments", aspire_deploy)
        self.assertIn("--output none || return 1", aspire_deploy)
        self.assertIn("Expected one Aspire registry and identity", aspire_deploy)

    def test_apphost_preserves_container_environment_deployment_identity(self) -> None:
        apphost = (ROOT / "apps/waypoint/apphost.cs").read_text()

        self.assertIn(
            'AddAzureContainerAppEnvironment("starter-env")',
            apphost,
        )
        self.assertNotIn(
            'AddAzureContainerAppEnvironment("waypoint-env")',
            apphost,
        )

    def test_app_deploy_retries_after_silent_capacity_timeout(self) -> None:
        script = ROOT / "tools/deploy/scripts/aspire_deploy.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            state_dir = temp / "state"
            state_dir.mkdir()

            (bin_dir / "timeout").write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    count_file="$TEST_STATE/attempts"
                    count=0
                    [ -f "$count_file" ] && count="$(cat "$count_file")"
                    count=$((count + 1))
                    echo "$count" > "$count_file"
                    if [ "$count" -eq 1 ]; then
                      touch "$TEST_STATE/capacity"
                      exit 124
                    fi
                    exit 0
                    """
                )
            )
            (bin_dir / "az").write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    args="$*"
                    if [[ "$args" == *"containerapp env list"* ]]; then
                      [ -f "$TEST_STATE/capacity" ] && echo "failed-env"
                      exit 0
                    elif [[ "$args" == *"containerapp list"* ]]; then
                      echo "0"
                    elif [[ "$args" == *"deployment group list"* ]]; then
                      echo "starter-env-test"
                    elif [[ "$args" == *"deployment operation group list"* ]]; then
                      echo "1"
                    elif [[ "$args" == *"containerapp env delete"* ]]; then
                      rm "$TEST_STATE/capacity"
                      touch "$TEST_STATE/deleted"
                    elif [[ "$args" == *"containerapp env show"* ]]; then
                      [ -f "$TEST_STATE/capacity" ] && exit 0
                      exit 1
                    fi
                    exit 0
                    """
                )
            )
            for executable in ("timeout", "az"):
                (bin_dir / executable).chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "AZURE_RESOURCE_GROUP": "rg-test",
                    "ASPIRE_DEPLOY_RETRY_DELAY_SECONDS": "0",
                    "PATH": f"{bin_dir}:{environment['PATH']}",
                    "TEST_STATE": str(state_dir),
                }
            )
            completed = subprocess.run(
                ["bash", str(script)],
                cwd=temp,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((state_dir / "attempts").read_text().strip(), "2")
            self.assertTrue((state_dir / "deleted").exists())

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

    def test_clean_deploy_handles_resource_creation_races_and_soft_delete(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        msal = (ROOT / "tools/deploy/scripts/msal.sh").read_text()
        foundry_bootstrap = (
            ROOT / "modules/agents/scripts/bootstrap_foundry_account.sh"
        ).read_text()
        keyvault = workflow.split("\n  keyvault:\n", 1)[1].split(
            "\n  msal:\n", 1
        )[0]

        self.assertIn(
            'az group create --name "$AZURE_RESOURCE_GROUP"',
            keyvault,
        )
        self.assertIn("for attempt in {1..12}", msal)
        self.assertIn("did not become readable after creation", msal)
        self.assertIn("Graph application is not yet writable", msal)
        self.assertIn("Request_ResourceNotFound", msal)
        self.assertIn('az ad sp create --id "$APP_ID"', msal)
        self.assertIn("user_impersonation did not persist", msal)
        self.assertIn('az group exists --name "$resource_group"', foundry_bootstrap)
        self.assertIn("Reusing resource group", foundry_bootstrap)
        self.assertIn("cognitiveservices account list-deleted", foundry_bootstrap)
        self.assertIn("cognitiveservices account purge", foundry_bootstrap)
        self.assertIn("Timed out waiting for the soft-deleted", foundry_bootstrap)
        self.assertIn('account_name_generation="2"', foundry_bootstrap)
        self.assertIn(
            "${environment_name}${subscription_id}${account_name_generation}",
            foundry_bootstrap,
        )
        self.assertIn("azd provision --no-state --no-prompt", workflow)
        parameters = json.loads(
            (ROOT / "modules/agents/infra/main.parameters.json").read_text()
        )
        self.assertIs(
            parameters["parameters"]["enableCapabilityHost"]["value"],
            True,
        )
        capability_host = (
            ROOT / "modules/agents/infra/core/ai/ai-project.bicep"
        ).read_text()
        self.assertIn("capabilityHosts@2025-12-01", capability_host)
        self.assertNotIn("enablePublicHostingEnvironment", capability_host)
        self.assertIn("Verify hosted-agent capability host", workflow)
        self.assertIn("--api-version 2025-12-01", workflow)
        self.assertIn("/agents/${{ matrix.agent }}/versions?api-version=v1", workflow)
        self.assertIn("{version, status, error}", workflow)
        self.assertIn(
            "Agent version provisioning failed. Please retry",
            workflow,
        )
        content_understanding = (
            ROOT / "modules/agents/scripts/configure_content_understanding.py"
        ).read_text()
        self.assertIn(
            '"get-access-token",\n        "--resource",',
            content_understanding,
        )
        self.assertIn("for attempt in range(1, 13):", content_understanding)
        self.assertIn("after 12 attempts", content_understanding)
        self.assertNotIn(
            '"get-access-token",\n        "--scope",',
            content_understanding,
        )

        fabric = workflow.split("\n  fabric-provision:\n", 1)[1].split(
            "\n  # ── provision-agents", 1
        )[0]
        self.assertIn("needs.msal.result == 'success'", fabric)
        self.assertIn("needs: [plan, validate, keyvault, msal, deploy-app]", fabric)

    def test_app_only_redeploy_preserves_foundry_assurance_wiring(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_app = workflow.split("  deploy-app:", 1)[1].split(
            "  # ── provision-agents", 1
        )[0]

        self.assertIn("existing_foundry_endpoint=", deploy_app)
        self.assertIn("existing_foundry_project_url=", deploy_app)
        self.assertIn(
            'export Waypoint__Foundry__Endpoint="$existing_foundry_endpoint"',
            deploy_app,
        )
        self.assertIn(
            'export Waypoint__Foundry__ProjectUrl="$existing_foundry_project_url"',
            deploy_app,
        )

    def test_app_deploy_retains_safe_startup_database_bootstrap(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_app = workflow.split("\n  deploy-app:\n", 1)[1].split(
            "\n  # ── fabric-provision", 1
        )[0]

        self.assertNotIn("APP_RUN_STARTUP_DATABASE_BOOTSTRAP=false", deploy_app)
        self.assertIn(
            "pre-deploy database access cannot be proven on a first deployment",
            deploy_app,
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

    def test_assurance_operations_use_api_identity_and_foundry_account_scope(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        provision = workflow.split("  provision-agents:", 1)[1].split(
            "  # ── deploy-agents", 1
        )[0]
        wiring = workflow.split("  wire-app-operations:", 1)[1].split(
            "  # ── onelake-upload", 1
        )[0]

        self.assertIn("ai_account_id: ${{ steps.endpoint.outputs.ai_account_id }}", provision)
        self.assertIn("AZURE_AI_ACCOUNT_ID", provision)
        self.assertIn(
            "53ca6127-db72-4b80-b1b0-d745d6d5456d",
            wiring,
        )
        self.assertIn('--scope "$AI_ACCOUNT_ID"', wiring)
        self.assertIn("APP_FOUNDRY_ENDPOINT=${PROJECT_ENDPOINT}", wiring)
        self.assertIn(
            "APP_FOUNDRY_ORCHESTRATOR_AGENT_NAME=assurance-orchestrator",
            wiring,
        )
        self.assertIn("AZURE_CLIENT_ID=${app_client_id}", wiring)

    def test_acceptance_requires_assurance_operation_wiring(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        acceptance = workflow.split("\n  acceptance:\n", 1)[1]

        self.assertIn("- wire-app-operations", acceptance)
        self.assertIn(
            "APP_OPERATIONS_WIRING_RESULT: ${{ needs['wire-app-operations'].result }}",
            acceptance,
        )
        self.assertIn(
            'os.environ["WIRING_PLANNED"] == "true"',
            acceptance,
        )
        self.assertIn("Waypoint assurance-operation wiring did not succeed", acceptance)

    def test_agent_quality_workflow_name_is_consistent_across_operator_surfaces(
        self,
    ) -> None:
        workflow_path = ROOT / ".github/workflows/agent-quality-operations.yml"
        workflow = workflow_path.read_text()
        root_loader = (ROOT / "apps/waypoint/web/app/root.loader.ts").read_text()
        manifest = json.loads(
            (
                ROOT
                / "apps/waypoint/web/public/quality/evidence-manifest.v1.json"
            ).read_text()
        )

        self.assertTrue(workflow_path.is_file())
        self.assertFalse((ROOT / ".github/workflows/seller-operations.yml").exists())
        self.assertIn("name: Agent quality operations", workflow)
        self.assertNotIn("seller-operation", workflow.lower())
        self.assertIn('"agent-quality-operations.yml"', root_loader)
        self.assertEqual(
            manifest["source"]["workflow"],
            ".github/workflows/agent-quality-operations.yml",
        )

    def test_selective_agent_matrix_guard_uses_filtered_matrix(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        deploy_agents = workflow.split("\n  deploy-agents:\n", 1)[1].split(
            "\n  # ── wire-app-operations", 1
        )[0]

        self.assertIn("needs.validate.outputs.agent_matrix != '[]'", deploy_agents)
        self.assertNotIn("needs.plan.outputs.selected_agents != '[]'", deploy_agents)

    def test_acceptance_respects_manual_stage_upper_bounds(self) -> None:
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        acceptance = workflow.split("\n  acceptance:\n", 1)[1].split(
            "\n  record-deployment-state:\n", 1
        )[0]

        self.assertIn('os.environ["FABRIC_PROVISION_ENABLED"] == "true"', acceptance)
        self.assertIn('os.environ["FOUNDRYIQ_ENABLED"] == "true"', acceptance)
        self.assertIn('os.environ["SEED_DATA_ENABLED"] == "true"', acceptance)


if __name__ == "__main__":
    unittest.main()
