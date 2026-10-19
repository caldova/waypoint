# Copilot Instructions

This is the Caldova Waypoint application runtime: a FastAPI API, React Router web app, and Aspire AppHost. Follow these guidelines when working with this codebase.

## Project Structure

- `api/` - FastAPI backend (Python 3.13+)
- `web/` - React Router v7 frontend (TypeScript, Vite, Tailwind)
- `apphost.cs` - Aspire orchestration

## Coding Standards

### Python (API)

- Use `async/await` for all I/O operations
- Add `@trace` decorator to all service methods for OpenTelemetry tracing
- Use `trace_span()` context manager in route handlers
- Use Pydantic models for request/response validation
- Follow the module pattern: `schemas.py`, `service.py`, `routes.py`
- Use type hints everywhere
- Format with `ruff`

### Module Pattern

Each API module should have this structure:

```text
api/app/modules/mymodule/
├── __init__.py      # Export router and key classes
├── schemas.py       # Pydantic models (Base, Create, Full, PagedResponse)
├── service.py       # Business logic with @trace decorator
└── routes.py        # FastAPI endpoints with dependency injection
```

### Dependency Injection

Use the factory pattern for Cosmos DB dependencies:

```python
from ..dependencies import _create_cosmos_service_dependency

get_mymodule_cosmos_service = _create_cosmos_service_dependency("mymodules", "mymodule")

def get_mymodule_service(
    cosmos_service: CosmosService = Depends(get_mymodule_cosmos_service),
) -> MyModuleService:
    return MyModuleService(cosmos_service)
```

### TypeScript (Web)

- Use functional components with hooks
- Use TypeScript strict mode
- Style with Tailwind CSS utility classes
- Use React Router v7 loaders for data fetching
- Wrap API calls with `traced()` for browser telemetry
- Never hardcode user-visible text. Add keys to `web/app/i18n/locales/{en,es}/*.json` and use `t()` from `useTranslation`. Use `useFormat()` for dates, numbers, and currency (see README "Localization").

### Aspire

- Define all resources in `apphost.cs`
- Use environment variables with `APP_` prefix for configuration
- Add health checks to all services
- Use `WaitFor()` to manage startup dependencies

## File Naming

- Python: `snake_case.py`
- TypeScript: `camelCase.ts` for utilities, `PascalCase.tsx` for components
- Routes: `kebab-case.tsx`

## Testing

- API: pytest with async support (`pytest-asyncio`)
- Use `MockCosmosService` and `MockStorageService` from `tests/mocks/`
- Web: TypeScript type checking (`npm run typecheck`)
- E2E: Playwright (optional, see AGENTS.md)

## When Adding Features

1. For new API endpoints, create a module in `api/app/modules/`
2. Add shared dependencies in `api/app/modules/dependencies.py`
3. For new pages, add routes in `web/app/routes/`
4. For Azure services, update `apphost.cs` and add to `api/app/common/`
5. Always add OpenTelemetry tracing to new code
6. Add unit tests with mocks in `api/tests/unit/`
