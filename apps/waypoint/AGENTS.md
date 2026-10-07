# Copilot Instructions

This repository is set up to use **Aspire**. Aspire is an orchestrator for the entire application and takes care of configuring dependencies, building, and running the application. The resources that make up the application are defined in `apphost.cs` including application code and external dependencies.

## Quick Reference for Agents

### Key Files to Know

| File                         | Purpose               | When to Modify                         |
| ---------------------------- | --------------------- | -------------------------------------- |
| `apphost.cs` | Aspire orchestration | Adding Azure services, changing ports |
| `api/app/main.py` | FastAPI entry point | Adding routers, middleware |
| `api/app/common/settings.py` | Configuration | Adding environment variables |
| `api/app/common/tracer.py` | Tracing utilities | Rarely (already complete) |
| `web/vite.config.ts` | Vite + proxy config | Changing API proxy, build settings |
| `web/app/routes.ts` | Route definitions | Adding new pages |
| `web/app/i18n/locales/` | UI strings (`en`, `es`) | Adding or changing any user-visible text (see README "Localization") |

### Common Tasks

| Task               | Command/Action                       |
| ------------------ | ------------------------------------ |
| Run locally | `aspire run` |
| Run API tests | `cd api && uv run pytest` |
| Run web typecheck | `cd web && npm run typecheck` |
| Check translations | `cd web && npm run i18n:check` |
| Format Python | `cd api && uv run ruff format app/` |
| Check Python lint | `cd api && uv run ruff check app/` |
| Add Python dep | Edit `api/pyproject.toml`, then `uv sync` |
| Add npm dep | `cd web && npm install <package>` |
| Deploy to Azure | `aspire deploy` |
| Install pre-commit | `uv tool install pre-commit && pre-commit install` |
| Run all checks | `pre-commit run --all-files` |

### Pre-commit Hooks

The project includes pre-commit hooks that run automatically on `git commit`:

| Hook | What it does |
| ---- | ------------ |
| markdownlint | Lints markdown files against `.markdownlint.json` rules |
| ruff | Lints Python code in `api/` with auto-fix |
| ruff-format | Formats Python code in `api/` |
| trailing-whitespace | Removes trailing spaces (excludes `.md` files) |
| end-of-file-fixer | Ensures files end with a newline |
| check-yaml | Validates YAML syntax |
| check-json | Validates JSON syntax (excludes `.vscode/*.json` JSONC files) |
| check-added-large-files | Prevents committing large files |

### Environment Variables Pattern

All API config uses `APP_` prefix and is set in `apphost.cs`:

```python
# In api/app/common/settings.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    my_new_setting: str = Field(default="", description="...")
```

```csharp
// In apphost.cs
.WithEnvironment("APP_MY_NEW_SETTING", "value")
```

## General Recommendations for Working with Aspire

1. Before making any changes, always run the apphost using `aspire run` and inspect the state of resources to make sure you are building from a known state.
2. Changes to the `apphost.cs` file will require a restart of the application to take effect.
3. Make changes incrementally and run the aspire application using the `aspire run` command to validate changes.
4. Use the Aspire dashboard to check the status of resources and debug issues via traces and logs.

## Running the Application

```bash
aspire run
```

If there is already an instance of the application running it will prompt to stop the existing instance. You only need to restart the application if code in `apphost.cs` is changed, but if you experience problems it can be useful to reset everything to the starting state.

## Checking Resources

Use the Aspire dashboard (<http://localhost:15888> by default) to:

- View all running resources
- Check resource health status
- View structured logs
- Inspect distributed traces

## Debugging Issues

The Aspire dashboard captures rich logs and telemetry for all resources. Use these diagnostic tools when debugging issues:

1. **Structured logs** — View logs from all services in one place
2. **Console logs** — Raw console output from each service
3. **Traces** — Distributed tracing across frontend and backend
4. **Metrics** — Application performance metrics

---

## Extending the Template

### Adding Azure Cosmos DB

To add Azure Cosmos DB for data persistence:

1. **Update `apphost.cs`**:

```csharp
#:package Aspire.Hosting.Azure.CosmosDB@13.4.3

// Add after builder creation
var cosmos = builder.AddAzureCosmosDB("cosmos");
var database = cosmos.AddCosmosDatabase("starterdb", "StarterDB");
var items = database.AddContainer("items", "/id");

// Update API resource
var api = builder.AddUvicornApp("api", "./api", "app.main:app")
    .WithUv()
    .WaitFor(cosmos)
    .WithEnvironment("APP_DATABASE_CONNECTION", cosmos.Resource.ConnectionStringExpression)
    .WithEnvironment("APP_DATABASE_NAME", database.Resource.DatabaseName)
    // ... rest of configuration
```

1. **Update `api/pyproject.toml`**:

```toml
dependencies = [
    # ... existing deps
    "azure-cosmos>=4.9.0",
    "azure-identity>=1.19.0",
]
```

1. **Create `api/app/common/cosmos.py`**:

```python
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from .settings import get_settings

class CosmosService:
    def __init__(self, container_name: str):
        settings = get_settings()
        self.client = CosmosClient(
            settings.database_connection,
            credential=DefaultAzureCredential(),
        )
        self.database = self.client.get_database_client(settings.database_name)
        self.container = self.database.get_container_client(container_name)
```

1. **Update `ItemService`** to use `CosmosService` instead of in-memory storage.

### Adding Azure Blob Storage

To add Azure Blob Storage for file uploads:

1. **Update `apphost.cs`**:

```csharp
#:package Aspire.Hosting.Azure.Storage@13.4.3

var storage = builder.AddAzureStorage("storage");
var blobs = storage.AddBlobContainer("uploads");

var api = builder.AddUvicornApp("api", "./api", "app.main:app")
    .WaitFor(blobs)
    .WithEnvironment("APP_STORAGE_CONNECTION", storage.Resource.BlobEndpoint)
    .WithEnvironment("APP_STORAGE_CONTAINER", blobs.Resource.Name)
    // ...
```

1. **Update `api/pyproject.toml`**:

```toml
dependencies = [
    # ... existing deps
    "azure-storage-blob>=12.24.0",
    "azure-identity>=1.19.0",
]
```

1. **Create `api/app/common/storage.py`** with `StorageService` class.

### Adding Azure AI Foundry

To add Azure AI capabilities:

1. **Create `infra/foundry.bicep`** with Azure AI Foundry resource definition.

2. **Update `apphost.cs`**:

```csharp
var foundry = builder.AddResource(
    new MicrosoftFoundryResource("foundry", "./infra/foundry.bicep"))
    .WithParameter("aiFoundryName", "myproject");

var api = builder.AddUvicornApp("api", "./api", "app.main:app")
    .WaitFor(foundry)
    .WithEnvironment("APP_FOUNDRY_ENDPOINT", foundry.Resource.AiProjectUrl)
    .WithEnvironment("APP_AZURE_OPENAI_ENDPOINT", foundry.Resource.OpenAIEndpoint)
    // ...
```

1. **Add `azure-ai-projects` to dependencies** and create `api/app/common/foundry.py`.

### Adding Authentication

For production authentication:

1. **Azure Easy Auth** — Configure Azure Container Apps with Microsoft Entra ID authentication
2. **API Key Auth** — Add middleware to validate API keys
3. **JWT Auth** — Use `python-jose` for JWT token validation

Example middleware pattern:

```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key
```

---

## Module Pattern

When adding new API modules, follow this structure:

```text
api/app/modules/newmodule/
├── __init__.py      # Export router and classes
├── schemas.py       # Pydantic models
├── service.py       # Business logic with @trace decorator
└── routes.py        # FastAPI endpoints
```

### Step-by-Step: Adding a New Module

1. **Create the directory**: `api/app/modules/newmodule/`

2. **Create schemas.py** with Pydantic models:

   ```python
   from pydantic import BaseModel, Field

   class NewItemBase(BaseModel):
       name: str = Field(..., description="Item name")

   class NewItemCreate(NewItemBase):
       pass

   class NewItem(NewItemBase):
       id: str
       type: str = "newitem"
   ```

3. **Create service.py** with business logic:

   ```python
   from ...common.tracer import trace

   class NewItemService:
       @trace
       async def create(self, item: NewItemCreate) -> NewItem:
           # Implementation
           pass
   ```

4. **Create routes.py** with endpoints:

   ```python
   from fastapi import APIRouter, Depends
   from ...common.tracer import trace_span

   router = APIRouter(prefix="/newitems", tags=["newitems"])

   @router.post("/", response_model=NewItem)
   async def create(item: NewItemCreate, service = Depends(get_service)):
       with trace_span("create_newitem"):
           return await service.create(item)
   ```

5. **Create **init**.py** to export:

   ```python
   from .routes import router as newitem_router
   __all__ = ["newitem_router"]
   ```

6. **Register in main.py**:

   ```python
   from .modules.newmodule import newitem_router
   app.include_router(newitem_router, prefix="/api")
   ```

7. **Add tests** in `api/tests/unit/test_newitem_service.py`

Register the router in `api/app/main.py`:

```python
from .modules.newmodule import newmodule_router
app.include_router(newmodule_router, prefix="/api")
```

---

## Adding Playwright E2E Testing

For end-to-end browser testing, add Playwright to the web project:

1. **Install Playwright**:

```bash
cd web
npm install -D @playwright/test
npx playwright install
```

1. **Create `web/playwright.config.ts`**:

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: process.env.WEB_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
  },
});
```

1. **Create `web/e2e/example.spec.ts`**:

```typescript
import { test, expect } from '@playwright/test';

test('home page loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/FastAPI React Aspire/);
});

test('items page shows items from API', async ({ page }) => {
  await page.goto('/items');
  // Wait for items to load from API
  await expect(page.locator('text=Welcome Item')).toBeVisible();
});

test('can create a new item', async ({ page }) => {
  await page.goto('/items');
  await page.fill('input[placeholder="Item name"]', 'Test Item');
  await page.click('button:has-text("Add")');
  await expect(page.locator('text=Test Item')).toBeVisible();
});
```

1. **Add scripts to `web/package.json`**:

```json
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

1. **Update CI workflow** (`.github/workflows/ci.yml`):

```yaml
  e2e:
    name: E2E Tests
    runs-on: ubuntu-latest
    needs: [api, web]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - name: Install dependencies
        run: cd web && npm ci
      - name: Install Playwright browsers
        run: cd web && npx playwright install --with-deps
      - name: Run Playwright tests
        run: cd web && npm run test:e2e
```

**Note**: For full e2e testing with the API, run `aspire run` first, then use the Aspire-provided URLs.

---

## Official Documentation

Always prefer official documentation when available:

1. <https://aspire.dev>
2. <https://learn.microsoft.com/dotnet/aspire>
3. <https://nuget.org> (for specific integration package details)
4. <https://fastapi.tiangolo.com>
5. <https://reactrouter.com>
6. <https://playwright.dev>

---

## Troubleshooting Guide

### Aspire Won't Start

```bash
# Update Aspire CLI
curl -sSL https://aspire.dev/install.sh | bash  # Linux/macOS
irm https://aspire.dev/install.ps1 | iex        # Windows

# Check for port conflicts
netstat -an | grep 8000
netstat -an | grep 5173
```

### API Tests Failing

```bash
# Ensure dependencies installed
cd api && uv sync

# Run with verbose output
uv run pytest -v --tb=long

# Check for mypy issues
uv run mypy app/
```

### Web TypeScript Errors

```bash
# Ensure dependencies installed
cd web && npm ci

# Clear caches and rebuild
rm -rf node_modules .react-router
npm install
npm run typecheck
```

### Traces Not Appearing in Dashboard

1. Check `api/app/telemetry.py` is called in lifespan
2. Verify OTEL environment variables are set (check Aspire logs)
3. Ensure `@trace` decorator is on service methods
4. Look for errors in Aspire console logs

### Deployment Failures

1. Check GitHub secrets are configured:
   - `AZURE_CLIENT_ID`
   - `AZURE_TENANT_ID`
   - `AZURE_SUBSCRIPTION_ID`
   - `AZURE_LOCATION`
   - `AZURE_RESOURCE_GROUP`

2. Verify Azure permissions:

   ```bash
   az role assignment list --assignee <CLIENT_ID>
   ```

3. Check Aspire logs for specific errors
