"""Bind Castia's native exporter to the existing project connection at startup."""

import logging
import os

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential

_LOG = logging.getLogger("agent")


def configure_project_export() -> None:
    if os.getenv("CPA_NATIVE_TRACE_PROJECT", "").lower() != "true":
        return
    if any(os.getenv(name) for name in (
        "AZURE_MONITOR_CONNECTION_STRING", "APPLICATIONINSIGHTS_CONNECTION_STRING",
    )):
        return
    try:
        with (
            DefaultAzureCredential() as credential,
            AIProjectClient(
                endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=credential,
            ) as project,
        ):
            connection_string = project.telemetry.get_application_insights_connection_string()
        if not connection_string.strip():
            raise ValueError("Project telemetry connection is empty.")
    except (AzureError, ValueError) as exc:
        _LOG.warning(
            "Native project telemetry discovery failed (%s, status=%s); "
            "tracing export is not configured. Verify the existing AppInsights "
            "connection and hosted identity permissions.",
            type(exc).__name__, getattr(exc, "status_code", None),
        )
        return
    # Process-local only: never copy this credential into azd or artifact files.
    os.environ["AZURE_MONITOR_CONNECTION_STRING"] = connection_string
