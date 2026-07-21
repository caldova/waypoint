"""Regression tests for the app-simplification pass.

These lock in the removal of the starter ``items`` feature, the Waypoint branding/config
defaults, and the separation of privileged database bootstrap from request-serving startup.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app import bootstrap
from app.common import database
from app.common.database import (
    bootstrap_database,
    get_waypoint_repository_for_settings,
    reset_waypoint_repository_for_tests,
)
from app.common.settings import Settings, get_settings
from app.common.tracer import DEFAULT_TRACER_NAME
from app.main import app


@pytest.fixture
async def client():
    app.dependency_overrides[get_settings] = lambda: Settings(local_auth_enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    reset_waypoint_repository_for_tests()


# --- Starter items feature is gone ---------------------------------------


@pytest.mark.asyncio
async def test_items_collection_route_removed(client: AsyncClient):
    response = await client.get("/api/items/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_items_detail_route_removed(client: AsyncClient):
    response = await client.get("/api/items/item-1")
    assert response.status_code == 404


def test_items_module_not_registered():
    routes = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith("/api/items") for path in routes)


def test_items_module_import_removed():
    with pytest.raises(ModuleNotFoundError):
        __import__("app.modules.items")


# --- Waypoint branding and config defaults -------------------------------


@pytest.mark.asyncio
async def test_root_uses_waypoint_branding(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "Waypoint" in body
    assert "Starter" not in body


def test_default_tracer_name_is_waypoint():
    assert DEFAULT_TRACER_NAME == "waypoint.api"
    assert "starter" not in DEFAULT_TRACER_NAME


def test_database_name_default_has_no_starter_residue():
    assert Settings().database_name == "WaypointDB"


# --- Privileged bootstrap is separable from startup ----------------------


def test_bootstrap_cli_entry_points_exist():
    assert callable(bootstrap.main)
    assert callable(bootstrap.run)


async def test_bootstrap_database_requires_connections():
    with pytest.raises(ValueError):
        await bootstrap_database(Settings())
    with pytest.raises(ValueError):
        await bootstrap_database(Settings(database_connection="postgresql://app@db/waypoint"))


class _FakeRepository:
    """Minimal repository stand-in so bootstrap gating can be tested without Postgres."""

    def __init__(self, connection_string: str, *, min_pool_size: int = 1, max_pool_size: int = 10):
        self.connection_string = connection_string
        self.initialized = False

    async def initialize(self, load_default_seed: bool = True) -> None:
        self.initialized = True

    async def close(self) -> None:
        pass


@pytest.fixture
def patched_postgres(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def _record_role_bootstrap(bootstrap_connection: str, application_connection: str):
        calls.append((bootstrap_connection, application_connection))

    monkeypatch.setattr(database, "_bootstrap_postgres_application_role", _record_role_bootstrap)
    monkeypatch.setattr(
        "app.common.repository.PostgresWaypointRepository", _FakeRepository, raising=True
    )
    reset_waypoint_repository_for_tests()
    yield calls
    reset_waypoint_repository_for_tests()


async def test_startup_skips_privileged_bootstrap_when_flag_disabled(patched_postgres):
    settings = Settings(
        database_connection="postgresql://app:pw@db/waypoint",
        database_bootstrap_connection="postgresql://admin:pw@db/postgres",
        run_startup_database_bootstrap=False,
    )
    repository = await get_waypoint_repository_for_settings(settings)
    assert isinstance(repository, _FakeRepository)
    assert repository.initialized is True
    assert patched_postgres == []


async def test_startup_runs_privileged_bootstrap_by_default(patched_postgres):
    settings = Settings(
        database_connection="postgresql://app:pw@db/waypoint",
        database_bootstrap_connection="postgresql://admin:pw@db/postgres",
    )
    repository = await get_waypoint_repository_for_settings(settings)
    assert isinstance(repository, _FakeRepository)
    assert repository.initialized is True
    assert patched_postgres == [
        ("postgresql://admin:pw@db/postgres", "postgresql://app:pw@db/waypoint")
    ]
