param(
    [Parameter(Mandatory = $true)]
    [string] $EvalModel,

    [Parameter(Mandatory = $true)]
    [string] $OptimizerModel,

    [string] $Dataset = "..\..\evals\datasets\contract-policy-expert\contract-policy-expert-train.jsonl",

    [string] $SuiteName = "contract-policy-expert-generated-rubric",

    [string] $AgentName = "contract-policy-expert",

    [string] $ProjectEndpoint,

    [switch] $SkipOptimize
)

$ErrorActionPreference = "Stop"

$agentRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $agentRoot "..\..\..")
$evalConfig = Join-Path $agentRoot "eval.yaml"
$generationBrief = Join-Path $agentRoot "eval-generation-instructions.md"
$rubricPath = Join-Path $agentRoot "evaluators\$SuiteName\rubric_dimensions.json"

function Invoke-Logged {
    param([Parameter(Mandatory = $true)][string[]] $Command)
    Write-Host "> $($Command -join ' ')"
    & $Command[0] @($Command | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $($Command -join ' ')"
    }
}

if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
    throw "azd is required before running the Foundry optimizer demo workflow."
}

if (-not (Test-Path $generationBrief)) {
    throw "Rubric generation brief not found: $generationBrief"
}

if (-not (Test-Path (Join-Path $agentRoot $Dataset))) {
    throw "Dataset not found relative to agent root: $Dataset"
}

$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"

Push-Location $agentRoot
try {
    if (-not $ProjectEndpoint) {
        $values = azd env get-values
        if ($LASTEXITCODE -ne 0) {
            throw "azd env get-values failed. Select or configure the target azd environment first, or pass -ProjectEndpoint."
        }
        $hasProjectEndpoint = $values | Where-Object {
            $_ -match '^AZURE_AI_PROJECT_ENDPOINT=' -or $_ -match '^AZURE_AIPROJECT_ENDPOINT='
        }
        if (-not $hasProjectEndpoint) {
            throw "The selected azd environment does not define AZURE_AI_PROJECT_ENDPOINT or AZURE_AIPROJECT_ENDPOINT. Run provisioning, select the deployed Foundry environment, or pass -ProjectEndpoint before generating the rubric."
        }
    }

    $generateCommand = @(
        "azd", "ai", "agent", "eval", "generate",
        "--agent", $AgentName,
        "--reset-defaults",
        "--dataset", $Dataset,
        "--gen-instruction-file", ".\eval-generation-instructions.md",
        "--eval-model", $EvalModel,
        "--name", $SuiteName,
        "--out-file", ".\eval.yaml"
    )
    if ($ProjectEndpoint) {
        $generateCommand += @("--project-endpoint", $ProjectEndpoint)
    }
    Invoke-Logged $generateCommand

    if (-not (Test-Path $rubricPath)) {
        throw "Expected generated rubric was not found at $rubricPath. Review azd output and generated evaluator paths before optimizing."
    }

    Push-Location (Join-Path $repoRoot "modules\evals")
    try {
        Invoke-Logged @(
            "uv", "run", "caliber", "eval", "validate-assets",
            "--eval-config", "..\agents\contract-policy-expert\eval.yaml",
            "--json"
        )
    }
    finally {
        Pop-Location
    }

    if (-not $SkipOptimize) {
        Push-Location $agentRoot
        try {
            $optimizeCommand = @(
                "azd", "ai", "agent", "optimize",
                "--agent", $AgentName,
                "--config", ".\eval.yaml",
                "--optimize-model", $OptimizerModel
            )
            if ($ProjectEndpoint) {
                $optimizeCommand += @("--project-endpoint", $ProjectEndpoint)
            }
            Invoke-Logged $optimizeCommand
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
}
