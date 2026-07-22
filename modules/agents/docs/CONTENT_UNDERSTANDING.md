# Content Understanding for invoice PDF intake

This note captures how Forge should create and configure the Content
Understanding dependency needed by `assurance-orchestrator` before PDF-first invoice assurance
can be tested end-to-end.

## Resource ownership

Content Understanding should use the existing Forge-owned Azure AI Foundry / AI
Services account, not a separate ad hoc resource. The current Bicep creates a
multi-service account at `infra\core\ai\ai-project.bicep` with:

```bicep
resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-09-01' = {
  kind: 'AIServices'
  properties: {
    allowProjectManagement: true
    disableLocalAuth: true
  }
}
```

That account is the correct parent for Content Understanding. The missing work
is data-plane configuration and Assurance Orchestrator integration, not creating a second
Document Intelligence or Cognitive Services account.

## Correct creation model

1. Provision or reuse the Forge `kind: AIServices` account in a Content
   Understanding-supported region.
2. Configure Content Understanding defaults on the AI Services account so the
   service can resolve the model deployments it needs.
3. Start with the GA REST API version `2025-11-01`.
4. Start Assurance Orchestrator with the prebuilt invoice analyzer (`prebuilt-invoice`) before
   adding a custom Ledgerfield analyzer.
5. Call the account endpoint, not the project endpoint:
   - account endpoint: `https://<ai-account-name>.services.ai.azure.com`
   - Content Understanding path:
     `/contentunderstanding/analyzers/prebuilt-invoice:analyze?api-version=2025-11-01`
6. Poll the `Operation-Location` response header until the analyzer result
   reaches `Succeeded`.

There should be **no separate Bicep resource** named "Content Understanding" in
Forge. Content Understanding is a data-plane capability exposed from the
AI Services account. Bicep should only ensure the parent account, required model
deployments, outputs, env vars, and RBAC exist.

The older preview API versions `2024-12-01-preview` and `2025-05-01-preview`
should not be used for new automation; Microsoft documents their retirement for
July 15, 2026. Use `2025-11-01` unless a required preview-only feature forces a
temporary exception.

## Required model defaults

Microsoft's Content Understanding setup requires resource-level default model
deployments. The docs currently call out required defaults for:

| Model family | Purpose | Forge status |
| --- | --- | --- |
| `text-embedding-3-large` | Content Understanding / indexing support | Already added for `contracts-kb` |
| `gpt-5.5` | Shared completion model for hosted agents and `prebuilt-invoice` | Wired into Forge infra as the single completion deployment |

Forge provisions one shared completion deployment plus
`text-embedding-3-large`. Content Understanding reuses the completion
deployment:

| Setting | Value |
| --- | --- |
| Deployment name | `gpt-5.5` |
| Model name | `gpt-5.5` |
| Model version | `2026-04-24` |
| SKU | `GlobalStandard` |
| Capacity | `200` |

The post-provision script explicitly maps Content Understanding defaults to the
shared completion and embedding deployments.

Direct testing against the Forge account showed this concrete failure mode:

```json
{
  "code": "ResourceError",
  "message": "This analyzer needs a 'completion' model deployment for current request, but none was resolved. Either 'models.completion' is not set on the analyzer, or the deployment it references is not registered for this resource. Configure it via 'PATCH /contentunderstanding/defaults'."
}
```

## Exact Bicep wiring

### 1. Surface account-level Content Understanding outputs

`infra\main.bicep` surfaces these outputs from the selected AI Services account:

```bicep
output CONTENT_UNDERSTANDING_ENDPOINT string = 'https://${useExistingAiProject ? existingAiProject.outputs.aiServicesAccountName : aiProject.outputs.aiServicesAccountName}.services.ai.azure.com'
output CONTENT_UNDERSTANDING_API_VERSION string = '2025-11-01'
output CONTENT_UNDERSTANDING_ANALYZER_ID string = 'prebuilt-invoice'
output CONTENT_UNDERSTANDING_SCOPE string = 'https://cognitiveservices.azure.com/.default'
output CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME string = modelDeploymentName
output CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME string = modelName
```

### 2. Reuse the primary completion deployment

`infra\main.bicep` derives the Content Understanding completion outputs from
the primary `modelDeploymentName` and `modelName` parameters. The default list
contains `gpt-5.5` followed by `text-embedding-3-large`; it does not provision a
separate Content Understanding completion model.

It includes them in `defaultDeployments` alongside the existing chat and
embedding deployments:

```bicep
{
  name: contentUnderstandingCompletionDeploymentName
  model: {
    name: contentUnderstandingCompletionModelName
    format: 'OpenAI'
    version: contentUnderstandingCompletionModelVersion
  }
  sku: {
    name: contentUnderstandingCompletionModelSkuName
    capacity: int(contentUnderstandingCompletionModelCapacity)
  }
}
```

`infra\main.parameters.json` maps these params to azd env variables so
operators can override deployment name, model name, version, SKU, or capacity
without editing Bicep.

### 3. Keep RBAC explicit

`infra\core\ai\ai-project.bicep` already defines these role IDs:

| Role | Role definition ID |
| --- | --- |
| `Foundry User` | `53ca6127-db72-4b80-b1b0-d745d6d5456d` |
| `Foundry Project Manager` | `eadc314b-1a2d-4efa-be10-5d325db5065e` |
| `Cognitive Services User` | `a97b65f3-24c7-4388-baec-2e87135dc908` |

The project managed identity already receives `Cognitive Services User` on the
AI Services account:

```bicep
resource projectMICognitiveServicesUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccount
  name: guid(aiAccount.id, aiAccount::project.id, cognitiveServicesUserRoleId)
  properties: {
    principalId: aiAccount::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}
```

Do not remove this assignment; it is what lets hosted `assurance-orchestrator` call the
Content Understanding data plane when local auth is disabled.

## Exact azd / workflow env seeding

After `azd provision`, the deploy workflow copies the Bicep outputs into
azd env so `agents\assurance-orchestrator\agent.yaml` can inject them into the container:

```bash
azd env set CONTENT_UNDERSTANDING_ENDPOINT "$CONTENT_UNDERSTANDING_ENDPOINT"
azd env set CONTENT_UNDERSTANDING_API_VERSION "${CONTENT_UNDERSTANDING_API_VERSION:-2025-11-01}"
azd env set CONTENT_UNDERSTANDING_ANALYZER_ID "${CONTENT_UNDERSTANDING_ANALYZER_ID:-prebuilt-invoice}"
azd env set CONTENT_UNDERSTANDING_SCOPE "${CONTENT_UNDERSTANDING_SCOPE:-https://cognitiveservices.azure.com/.default}"
```

`agents\assurance-orchestrator\agent.yaml` includes:

```yaml
- name: CONTENT_UNDERSTANDING_ENDPOINT
  value: ${CONTENT_UNDERSTANDING_ENDPOINT}
- name: CONTENT_UNDERSTANDING_API_VERSION
  value: ${CONTENT_UNDERSTANDING_API_VERSION}
- name: CONTENT_UNDERSTANDING_ANALYZER_ID
  value: ${CONTENT_UNDERSTANDING_ANALYZER_ID}
- name: CONTENT_UNDERSTANDING_SCOPE
  value: ${CONTENT_UNDERSTANDING_SCOPE}
```

## Environment contract for Assurance Orchestrator

Assurance Orchestrator should not infer these values from the project endpoint. It should read
explicit env vars:

| Env var | Example | Notes |
| --- | --- | --- |
| `CONTENT_UNDERSTANDING_ENDPOINT` | `https://ai-account-xxxx.services.ai.azure.com` | Account endpoint, not `*.cognitiveservices.azure.com` and not project endpoint |
| `CONTENT_UNDERSTANDING_API_VERSION` | `2025-11-01` | GA API for new automation |
| `CONTENT_UNDERSTANDING_ANALYZER_ID` | `prebuilt-invoice` | Replace later with a custom Ledgerfield analyzer id |
| `CONTENT_UNDERSTANDING_SCOPE` | `https://cognitiveservices.azure.com/.default` | Entra token scope when local auth is disabled |

Since Forge sets `disableLocalAuth: true` on the AI Services account, runtime
code should use Entra ID bearer tokens rather than subscription keys.

## Exact Content Understanding defaults setup

Bicep/ARM should not PATCH `/contentunderstanding/defaults`; that is a
data-plane operation. Forge uses `scripts\configure_content_understanding.py`
after provision to set the account defaults.

Inputs:

| Argument/env | Required | Meaning |
| --- | --- | --- |
| `CONTENT_UNDERSTANDING_ENDPOINT` | yes | `https://<ai-account>.services.ai.azure.com` |
| `CONTENT_UNDERSTANDING_API_VERSION` | yes | `2025-11-01` |
| `CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME` | yes | Shared `gpt-5.5` deployment |
| `CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME` | yes | Shared completion model family; Forge defaults to `gpt-5.5` |
| `AZURE_AI_EMBEDDING_DEPLOYMENT_NAME` | yes | Deployment to use for `text-embedding-3-large` default |

REST shape:

```http
PATCH {CONTENT_UNDERSTANDING_ENDPOINT}/contentunderstanding/defaults?api-version=2025-11-01
Authorization: Bearer <token for https://cognitiveservices.azure.com/.default>
Content-Type: application/merge-patch+json

{
  "modelDeployments": {
    "<CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME>": "<CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME>",
    "text-embedding-3-large": "<AZURE_AI_EMBEDDING_DEPLOYMENT_NAME>"
  }
}
```

Token acquisition for local/manual setup:

```powershell
az account get-access-token `
  --scope https://cognitiveservices.azure.com/.default `
  --query accessToken -o tsv
```

The setup script should fail loudly if any deployment name is missing or the
PATCH returns a non-2xx status. Do not silently continue with defaults
unconfigured; Assurance Orchestrator PDF intake would later fail in a less obvious place.

## RBAC

The identity calling Content Understanding needs data-plane access on the Forge
AI Services account.

| Caller | Needed role | Scope |
| --- | --- | --- |
| Assurance Orchestrator hosted agent project identity | `Cognitive Services User` | AI Services account |
| Local developer running Assurance Orchestrator | `Cognitive Services User` | AI Services account |
| Admin/operator configuring account defaults | Contributor or higher for resource setup; `Azure AI Account Owner` / Foundry-admin equivalent for Foundry data-plane configuration | Resource group / AI Services account |

Forge Bicep already grants the project managed identity `Cognitive Services
User` on the parent AI Services account for hosted-agent data-plane operations.
Existing environments may need `azd provision` or a one-time role assignment
before Assurance Orchestrator can call Content Understanding.

## Assurance Orchestrator workflow integration

Assurance Orchestrator now accepts PDF URL and inline base64 inputs, invokes Content
Understanding, normalizes extracted invoice fields, fans out to the configured
IQ validators, and prepares a read-only Waypoint write plan. The waypoint-recorder
remains the only component allowed to perform Waypoint writes.

The integration flow is:

1. Accept a PDF URL or uploaded file reference.
2. Call Content Understanding with `prebuilt-invoice`.
3. Normalize extracted fields into the Assurance Orchestrator target/context:
   supplier name, invoice number, invoice date, due date, currency, total,
   line descriptions, quantities, unit prices, PO, batch/shipment, and milestone
   references.
4. Preserve page/span references from the analyzer result so later judgements
   can cite the PDF evidence.
5. Resolve the canonical supplier before FoundryIQ contract retrieval.
6. Fan out to the configured IQs.
7. Prepare a `write_plan.future_payloads[]` preview for the waypoint-recorder.
8. Hand the fused evidence to the waypoint-recorder when a governed Waypoint write is
   intended.

### Exact analyze call Assurance Orchestrator should make

For a PDF URL:

```http
POST {CONTENT_UNDERSTANDING_ENDPOINT}/contentunderstanding/analyzers/{CONTENT_UNDERSTANDING_ANALYZER_ID}:analyze?api-version={CONTENT_UNDERSTANDING_API_VERSION}
Authorization: Bearer <token for CONTENT_UNDERSTANDING_SCOPE>
Content-Type: application/json

{
  "inputs": [
    {
      "url": "<pdf_uri>"
    }
  ]
}
```

For inline PDF bytes, use the binary endpoint. Do not wrap PDF bytes in the
JSON `inputs` shape; the SDK's `AnalyzeBinaryAsync` maps to `:analyzeBinary`.

```http
POST {CONTENT_UNDERSTANDING_ENDPOINT}/contentunderstanding/analyzers/{CONTENT_UNDERSTANDING_ANALYZER_ID}:analyzeBinary?api-version={CONTENT_UNDERSTANDING_API_VERSION}
Authorization: Bearer <token for CONTENT_UNDERSTANDING_SCOPE>
Content-Type: application/pdf

<raw PDF bytes decoded from pdf_base64>
```

Expected response:

```http
202 Accepted
Operation-Location: https://<ai-account>.services.ai.azure.com/contentunderstanding/analyzerResults/<operation-id>?api-version=2025-11-01
```

Assurance Orchestrator should poll `Operation-Location` with the same bearer token until:

```json
{
  "status": "Succeeded",
  "result": {
    "analyzerId": "prebuilt-invoice",
    "contents": [
      {
        "fields": {}
      }
    ]
  }
}
```

The workflow's `resolve_documents` output should change from:

```json
{"content_understanding_status": "not_invoked"}
```

to a succeeded/failed state that carries enough structured facts for the rest of
the workflow:

```json
{
  "content_understanding_status": "succeeded",
  "analyzer_id": "prebuilt-invoice",
  "invoice_number": "INV-2026-08034",
  "supplier_name": "BluePeak Biologics",
  "invoice_date": "2026-05-31",
  "currency": "USD",
  "total_amount": "128000.00",
  "line_count": 4,
  "source_spans": [
    {
      "field": "invoice_number",
      "page": 1,
      "offset": 123,
      "length": 14
    }
  ]
}
```

If Content Understanding returns `Failed`, Assurance Orchestrator should stop before fan-out
for a PDF-only request and report a structured extraction failure. It should not
pretend the PDF was understood and should not post anything to Waypoint.

## Exact validation sequence

After changing this integration, validate in this order:

1. Confirm the AI Services account endpoint:

   ```powershell
   azd env get-value CONTENT_UNDERSTANDING_ENDPOINT
   ```

2. Confirm role assignment for the project identity or local caller:

   ```powershell
   az role assignment list `
     --scope "$(azd env get-value AZURE_AI_ACCOUNT_ID)" `
     --role "Cognitive Services User" `
     -o table
   ```

3. Run the defaults script:

   ```powershell
   python scripts\configure_content_understanding.py
   ```

4. Smoke-test `prebuilt-invoice` against a known invoice PDF URL and verify the
   analyzer result reaches `Succeeded`.

5. Run Assurance Orchestrator with a request item that includes `pdf_uri`; verify:

   - `documents[0].content_understanding_status == "succeeded"`
   - extracted supplier/invoice fields are present
   - WorkIQ and FoundryIQ fan-out occurs
   - aggregation is invoked
   - Assurance Orchestrator only prepares `write_plan.future_payloads[]`
   - only the waypoint-recorder writes to Waypoint

## Deployment validation

After provisioning, run
`python scripts/test_content_understanding_preflight.py --skip-hosted-agent`.
The effective defaults must map both the model family and analyzer alias to the
shared deployments:

```json
{
  "modelDeployments": {
    "gpt-5.5": "gpt-5.5",
    "text-embedding-3-large": "text-embedding-3-large",
    "prebuilt-analyzer-completion": "gpt-5.5",
    "prebuilt-analyzer-embedding": "text-embedding-3-large"
  }
}
```

Direct Content Understanding smoke tests succeeded for both supported input
forms:

- PDF URL: `:analyze` with JSON `{"inputs":[{"url":"..."}]}` returned `202`
  and reached `Succeeded`.
- PDF bytes: `:analyzeBinary` with `Content-Type: application/pdf` returned
  `202` and reached `Succeeded`.

Earlier integrated validation also succeeded through the governed write
boundary:

| Step | Result |
| --- | --- |
| Canvas pipeline with existing Waypoint invoice `INV-2026-08034` and PDF URL | Completed read-only with Assurance Orchestrator, WebIQ, FabricIQ, WorkIQ, FoundryIQ, and Waypoint API touched |
| Direct Assurance Orchestrator hosted-IQ smoke | Content Understanding succeeded with extracted fields; IQ fan-out ran; overall status was `partial` because some IQ evidence lanes were partial/failed |
| Waypoint Recorder write from Assurance Orchestrator write plan | Wrote a Waypoint case, run, recommendation, and supplier-dispute draft for `INV-2026-08034` |

The waypoint-recorder write correlation from that earlier smoke was:

```json
{
  "waypoint_run_id": "run-bb7d5f4c9a8a46e1a40e73a5e05277cb",
  "waypoint_case_id": "case-73ccd897d69f4cf4aa3e38fc02210c04",
  "waypoint_recommendation_id": "rec-5364d2f6e0034e98afd114275df15bc1",
  "waypoint_draft_id": "draft-e3a43c7b24de417a808beb3b9eea7e90",
  "waypoint_invoice_id": "INV-2026-08034"
}
```

The latest Pipeline Mission Control run on 2026-06-27 intentionally used an
existing Waypoint invoice without `pdf_uri` or `pdf_base64`. That run exercised
Assurance Orchestrator, the four local IQ lanes, waypoint-recorder handoff, and Waypoint writes, but
the workflow reported:

```json
{"content_understanding_status": "not_invoked"}
```

because no PDF/document input was supplied. Treat that run as proof of the
Assurance Orchestrator -> waypoint-recorder -> Waypoint path, not proof of CU document analysis inside
the workflow.

## Remaining gaps

Content Understanding is now wired and validated at the resource level for
PDF-first Assurance Orchestrator tests. The remaining gaps are not resource-creation blockers:

1. The hosted/local WorkIQ evidence lane still needs investigation; it returned
   failed evidence during the direct hosted-IQ smoke.
2. One traceable Mission Control run still needs to pass `pdf_uri` or
   `pdf_base64` and show `content_understanding_status == "succeeded"` inside
   the Assurance Orchestrator workflow output.
3. FoundryIQ and FabricIQ can return partial evidence depending on available
   source data.
4. Assurance Orchestrator remains read-only in the current proof path. Any real Waypoint
   mutation must go through the waypoint-recorder write tool until WaypointIQ write
   authority is proven; later Assurance Orchestrator may write through that governed surface.
