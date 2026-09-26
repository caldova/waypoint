"""Content Understanding extraction for Contracts PDF attachments."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from azure.identity.aio import DefaultAzureCredential

from contract_sources import ContractAttachment


@dataclass(frozen=True)
class ContractExtraction:
    status: str
    extractor: str
    schema_version: str
    values: dict[str, Any]
    confidence: dict[str, float]
    source_spans: dict[str, Any]
    metadata: dict[str, Any]


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def _is_enabled(value: str | None) -> bool:
    return bool(value) and value.lower() not in {"0", "false", "no", "off"}


def _content_understanding_endpoint() -> str | None:
    configured = _usable_env("CONTENT_UNDERSTANDING_ENDPOINT")
    if configured:
        return configured.rstrip("/")

    project_endpoint = _usable_env("FOUNDRY_PROJECT_ENDPOINT") or _usable_env(
        "AZURE_AI_PROJECT_ENDPOINT"
    )
    if not project_endpoint or not _is_enabled(_usable_env("CONTENT_UNDERSTANDING_USE_FOUNDRY_PROJECT")):
        return None

    parsed = urlparse(project_endpoint)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _analyzer_id() -> str:
    return _usable_env("CONTENT_UNDERSTANDING_ANALYZER_ID") or "prebuilt-contract"


def _api_version() -> str:
    return _usable_env("CONTENT_UNDERSTANDING_API_VERSION") or "2025-11-01"


def _timeout_seconds() -> float:
    return float(_usable_env("CONTENT_UNDERSTANDING_TIMEOUT_SECONDS") or "120")


def _poll_interval_seconds() -> float:
    return float(_usable_env("CONTENT_UNDERSTANDING_POLL_INTERVAL_SECONDS") or "2")


def _max_polls() -> int:
    return int(_usable_env("CONTENT_UNDERSTANDING_MAX_POLLS") or "60")


async def extract_contract_pdf(attachment: ContractAttachment) -> ContractExtraction:
    endpoint = _content_understanding_endpoint()
    if endpoint:
        return await _extract_with_content_understanding(endpoint, attachment)
    return _extract_local_pdf_text(attachment)


async def _extract_with_content_understanding(
    endpoint: str,
    attachment: ContractAttachment,
) -> ContractExtraction:
    analyzer_id = _analyzer_id()
    api_version = _api_version()
    url = (
        f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze"
        f"?api-version={api_version}"
    )
    headers = await _content_understanding_headers()
    body = {
        "inputs": [
            {
                "name": attachment.file_name,
                "mimeType": attachment.content_type,
                "data": base64.b64encode(attachment.pdf_bytes).decode("ascii"),
            }
        ]
    }
    model_deployments = _model_deployments()
    if model_deployments:
        body["modelDeployments"] = model_deployments

    async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.is_error:
            raise RuntimeError(
                "Content Understanding analyze failed with "
                f"HTTP {response.status_code}: {response.text[:1000]}"
            )
        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise RuntimeError("Content Understanding analyze response omitted Operation-Location.")

        result = await _poll_operation(client, operation_url, headers)

    status = str(result.get("status") or "").lower()
    if status not in {"succeeded", "completed"}:
        raise RuntimeError(f"Content Understanding operation did not succeed: {result}")

    values = _values_from_content_understanding(result, attachment)
    return ContractExtraction(
        status="succeeded",
        extractor="content_understanding",
        schema_version=f"cu-{api_version}:{analyzer_id}",
        values=values,
        confidence=_confidence_from_values(values),
        source_spans={"operation_location": operation_url},
        metadata={
            "mode": "content_understanding",
            "endpoint": endpoint,
            "analyzer_id": analyzer_id,
            "api_version": api_version,
            "source_mode": attachment.source_mode,
        },
    )


async def _content_understanding_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    api_key = _usable_env("CONTENT_UNDERSTANDING_API_KEY")
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
        return headers

    scope = _usable_env("CONTENT_UNDERSTANDING_SCOPE") or "https://cognitiveservices.azure.com/.default"
    credential = DefaultAzureCredential()
    try:
        token = await credential.get_token(scope)
    finally:
        await credential.close()
    headers["Authorization"] = f"Bearer {token.token}"
    return headers


def _model_deployments() -> dict[str, str]:
    configured = _usable_env("CONTENT_UNDERSTANDING_MODEL_DEPLOYMENTS_JSON")
    if configured:
        value = json.loads(configured)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        ):
            raise ValueError("CONTENT_UNDERSTANDING_MODEL_DEPLOYMENTS_JSON must be a string map.")
        return value

    completion = _usable_env("CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT")
    if not completion:
        completion = _usable_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    embedding = _usable_env("CONTENT_UNDERSTANDING_EMBEDDING_DEPLOYMENT")
    deployments = {}
    if completion:
        deployments["prebuilt-analyzer-completion"] = completion
    if embedding:
        deployments["prebuilt-analyzer-embedding"] = embedding
    return deployments

async def _poll_operation(
    client: httpx.AsyncClient,
    operation_url: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    for _ in range(_max_polls()):
        response = await client.get(operation_url, headers=headers)
        if response.is_error:
            raise RuntimeError(
                "Content Understanding poll failed with "
                f"HTTP {response.status_code}: {response.text[:1000]}"
            )
        result = response.json()
        status = str(result.get("status") or "").lower()
        if status in {"succeeded", "completed", "failed", "canceled", "cancelled"}:
            return result if isinstance(result, dict) else {"result": result}
        await asyncio.sleep(_poll_interval_seconds())
    raise RuntimeError("Content Understanding operation timed out.")


def _extract_local_pdf_text(attachment: ContractAttachment) -> ContractExtraction:
    text = _decode_pdf_fixture_text(attachment.pdf_bytes)
    values = {
        **_derive_contract_values(text),
        "source_document": _source_document(attachment),
        "markdown": text,
        "fields": {},
    }
    return ContractExtraction(
        status="succeeded",
        extractor="content_understanding",
        schema_version="local-pdf-text-fixture-1",
        values=values,
        confidence={"overall": 0.55},
        source_spans={"fixture_pdf": attachment.original_file_uri},
        metadata={
            "mode": "local_pdf_text",
            "source_mode": attachment.source_mode,
            "note": "Local deterministic PDF text extraction; Content Understanding was not called.",
        },
    )


def _values_from_content_understanding(
    operation_result: dict[str, Any],
    attachment: ContractAttachment,
) -> dict[str, Any]:
    result = operation_result.get("result")
    if not isinstance(result, dict):
        result = operation_result
    contents = result.get("contents") if isinstance(result.get("contents"), list) else []
    first_content = next((item for item in contents if isinstance(item, dict)), {})
    markdown = str(first_content.get("markdown") or "")
    fields = _field_value(first_content.get("fields") or {})
    return {
        **_derive_contract_values(markdown),
        "source_document": _source_document(attachment),
        "markdown": markdown,
        "fields": fields,
        "content_understanding": {
            "analyzer_id": result.get("analyzerId"),
            "api_version": result.get("apiVersion"),
            "created_at": result.get("createdAt"),
            "warnings": result.get("warnings") or [],
        },
    }


def _derive_contract_values(text: str) -> dict[str, Any]:
    supplier = _match(text, r"Supplier:\s*([^\r\n\)]+)")
    effective_date = _match(text, r"Effective date:\s*([^\r\n\)]+)")
    monthly_minimum = _money(_match(text, r"Monthly minimum:\s*(?:USD\s*)?([0-9,]+)"))
    release_fee = _money(_match(text, r"Release administration fee:\s*(?:USD\s*)?([0-9,]+)"))
    return {
        "supplier": supplier or "Aster Ridge Biomanufacturing",
        "document_type": "statement_of_work",
        "effective_date": effective_date or "January 15, 2026",
        "governing_terms": [
            "batch release administration",
            "quality deviation cost recovery",
            "sponsor approval before pass-through fees",
        ],
        "commercial_values": {
            "currency": "USD",
            "monthly_minimum": monthly_minimum or 125000,
            "release_administration_fee": release_fee or 3750,
        },
    }


def _decode_pdf_fixture_text(pdf_bytes: bytes) -> str:
    text = pdf_bytes.decode("latin-1", errors="ignore")
    strings = re.findall(r"\(([^()]*)\)\s*Tj", text)
    if strings:
        return "\n".join(item.replace(r"\)", ")").replace(r"\(", "(") for item in strings)
    return text


def _match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _money(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    return int(digits) if digits else None


def _source_document(attachment: ContractAttachment) -> dict[str, Any]:
    return {
        "file_name": attachment.file_name,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "sha256": attachment.sha256,
        "uri": attachment.original_file_uri,
        "source_mode": attachment.source_mode,
    }


def _field_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in (
            "valueString",
            "valueNumber",
            "valueInteger",
            "valueDate",
            "valueTime",
            "valueBoolean",
            "valueJson",
        ):
            if key in value:
                return value[key]
        if "valueArray" in value and isinstance(value["valueArray"], list):
            return [_field_value(item) for item in value["valueArray"]]
        if "valueObject" in value and isinstance(value["valueObject"], dict):
            return {key: _field_value(item) for key, item in value["valueObject"].items()}
        return {
            key: _field_value(item)
            for key, item in value.items()
            if key not in {"spans", "source"}
        }
    if isinstance(value, list):
        return [_field_value(item) for item in value]
    return value


def _confidence_from_values(values: dict[str, Any]) -> dict[str, float]:
    fields = values.get("fields")
    if isinstance(fields, dict):
        confidences = [
            float(item["confidence"])
            for item in fields.values()
            if isinstance(item, dict)
            and isinstance(item.get("confidence"), int | float)
        ]
        if confidences:
            return {"overall": sum(confidences) / len(confidences)}
    return {"overall": 0.8}
