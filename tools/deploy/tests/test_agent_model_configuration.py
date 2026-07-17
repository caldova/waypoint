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


if __name__ == "__main__":
    unittest.main()
