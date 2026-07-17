import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class AgentModelConfigurationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
