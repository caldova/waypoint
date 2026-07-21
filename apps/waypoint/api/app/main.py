"""FastAPI application entry point."""

import contextlib
import logging
from collections.abc import AsyncGenerator

import fastapi
import fastapi.responses
import opentelemetry.instrumentation.fastapi as otel_fastapi
from fastapi.middleware.cors import CORSMiddleware

from .common.audit import AuditMiddleware
from .common.database import close_waypoint_repository, get_waypoint_repository_for_settings
from .common.settings import get_settings
from .modules.assurance_runs import assurance_runs_router
from .modules.cases.routes import router as cases_router
from .modules.config import config_router
from .modules.records.routes import router as records_router
from .modules.runs.reaper import start_run_reaper, stop_run_reaper
from .modules.runs.routes import router as runs_router
from .modules.users import user_router
from .modules.work.routes import router as work_router
from .telemetry import configure_opentelemetry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI) -> AsyncGenerator[None]:
    """Application lifespan handler - configure telemetry on startup."""
    configure_opentelemetry()
    await get_waypoint_repository_for_settings(get_settings())
    reaper_task = start_run_reaper(get_settings())
    logger.info("Application started with OpenTelemetry configured")
    yield
    await stop_run_reaper(reaper_task)
    await close_waypoint_repository()
    logger.info("Application shutting down")


# Create FastAPI application
app = fastapi.FastAPI(
    title="Caldova Waypoint",
    description="Invoice assurance workspace with FastAPI, React Router, and Aspire",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

allowed_origins = [
    origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()
]

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# Register routers
app.include_router(user_router, prefix="/api")
app.include_router(records_router, prefix="/api")
app.include_router(assurance_runs_router, prefix="/api")
app.include_router(cases_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(work_router, prefix="/api")
app.include_router(config_router, prefix="/api")


@app.get("/", response_class=fastapi.responses.HTMLResponse)
async def root() -> str:
    """Root endpoint with welcome message."""
    docs_link = (
        '<p>API documentation: <a href="/docs">/docs</a></p>' if settings.api_docs_enabled else ""
    )
    return f"""
    <html>
        <head><title>Caldova Waypoint</title></head>
        <body>
            <h1>Welcome to Caldova Waypoint</h1>
            {docs_link}
            <p>Health check: <a href="/health">/health</a></p>
        </body>
    </html>
    """


@app.get("/health", response_class=fastapi.responses.PlainTextResponse)
async def health_check() -> str:
    """Health check endpoint for Aspire and container orchestration."""
    return "Healthy"


# Instrument FastAPI with OpenTelemetry
otel_fastapi.FastAPIInstrumentor.instrument_app(
    app,
    exclude_spans=["send", "receive"],
    excluded_urls="health",
)
