"""Waypoint repository selection and lifecycle."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psycopg
from fastapi import Depends
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .settings import Settings, get_settings

if TYPE_CHECKING:
    from ..modules.records.service import WaypointService
    from .repository import WaypointRepository

logger = logging.getLogger(__name__)


async def get_waypoint_repository(
    settings: Settings = Depends(get_settings),
) -> "WaypointRepository":
    """Return the configured Waypoint repository."""

    return await get_waypoint_repository_for_settings(settings)


async def get_waypoint_repository_for_settings(settings: Settings) -> "WaypointRepository":
    """Return a singleton repository for the current database configuration."""

    from ..modules.records.service import WaypointService
    from .repository import InMemoryWaypointRepository, PostgresWaypointRepository

    global _repository, _repository_connection
    repository_key = (
        f"{settings.database_connection}|"
        f"{settings.database_bootstrap_connection}|"
        f"{settings.ledgerfield_seed_path}|"
        f"{settings.ledgerfield_seed_uri}|"
        f"{settings.default_seed_enabled}"
    )
    if _repository is not None and _repository_connection == repository_key:
        return _repository

    if settings.database_connection:
        run_privileged_bootstrap = (
            bool(settings.database_bootstrap_connection) and settings.run_startup_database_bootstrap
        )
        if run_privileged_bootstrap:
            await _bootstrap_postgres_application_role(
                settings.database_bootstrap_connection,
                settings.database_connection,
            )
        postgres_repository = PostgresWaypointRepository(
            settings.database_connection,
            min_pool_size=settings.database_pool_min_size,
            max_pool_size=settings.database_pool_max_size,
        )
        await postgres_repository.initialize(
            load_default_seed=settings.default_seed_enabled
            and not _has_configured_seed_source(settings)
        )
        if settings.fabric_mirror_enabled and run_privileged_bootstrap:
            await _bootstrap_fabric_mirroring_role(
                settings.database_bootstrap_connection,
                settings.database_connection,
                settings,
            )
        await _import_configured_seed(postgres_repository, settings, WaypointService)
        _repository = postgres_repository
        _repository_connection = repository_key
        logger.info("Configured PostgreSQL Waypoint repository")
        return postgres_repository

    memory_repository = InMemoryWaypointRepository()
    await memory_repository.initialize(
        load_default_seed=settings.default_seed_enabled
        and not _has_configured_seed_source(settings)
    )
    await _import_configured_seed(memory_repository, settings, WaypointService)
    _repository = memory_repository
    _repository_connection = repository_key
    logger.info("Configured in-memory Waypoint repository")
    return memory_repository


async def bootstrap_database(settings: Settings) -> None:
    """Run the privileged, idempotent database and role bootstrap out of band.

    This is the deploy-owned counterpart to request-serving startup: it holds the privileged
    ``database_bootstrap_connection`` and performs the operations the least-privilege API runtime
    must not do -- creating the application database and login role, applying the schema, and
    (when enabled) provisioning the Fabric Mirroring role. It is invoked by ``python -m
    app.bootstrap`` before the API starts. Every step is guarded or naturally idempotent, so the
    command is safe to re-run. Failures propagate to the caller and are never swallowed.
    """

    from .repository import PostgresWaypointRepository

    if not settings.database_connection:
        raise ValueError("APP_DATABASE_CONNECTION must be configured to bootstrap the database")
    if not settings.database_bootstrap_connection:
        raise ValueError(
            "APP_DATABASE_BOOTSTRAP_CONNECTION must be configured to bootstrap the database"
        )

    await _bootstrap_postgres_application_role(
        settings.database_bootstrap_connection,
        settings.database_connection,
    )

    repository = PostgresWaypointRepository(
        settings.database_connection,
        min_pool_size=settings.database_pool_min_size,
        max_pool_size=settings.database_pool_max_size,
    )
    try:
        await repository.initialize(load_default_seed=False)
    finally:
        await repository.close()

    if settings.fabric_mirror_enabled:
        await _bootstrap_fabric_mirroring_role(
            settings.database_bootstrap_connection,
            settings.database_connection,
            settings,
        )

    logger.info("Completed out-of-band database bootstrap")


def _has_configured_seed_source(settings: Settings) -> bool:
    """Return True when an explicit Ledgerfield seed path or blob URI is configured."""

    return bool(settings.ledgerfield_seed_path or settings.ledgerfield_seed_uri)


async def _import_configured_seed(
    repository: "WaypointRepository",
    settings: Settings,
    service_type: type["WaypointService"],
) -> None:
    """Import a Ledgerfield seed artifact from a local path or Azure Blob when configured.

    This runs during repository initialization (API startup). It is best-effort: any failure
    (missing/unreadable OneLake seed, blob auth error, malformed JSON) is logged and swallowed so a
    seed problem can never crash the API lifespan. The seed-import deploy job and any rows already
    present in the database remain the source of truth.
    """

    try:
        seed_text = _load_configured_seed_text(settings)
        if seed_text is None:
            return

        from ..modules.records.schemas import LedgerfieldSeedImport

        await repository.remove_default_seed()
        seed = LedgerfieldSeedImport.model_validate(json.loads(seed_text))
        result = await service_type(repository).import_ledgerfield_seed(seed)
        logger.info("Imported configured Ledgerfield seed: %s", result.model_dump())
    except Exception:  # noqa: BLE001 - startup seed import must never crash the API lifespan
        logger.exception(
            "Configured Ledgerfield seed import failed at startup; continuing with existing "
            "database contents. The seed-import deploy job can re-seed via the admin endpoint."
        )


def _load_configured_seed_text(settings: Settings) -> str | None:
    """Return the raw seed JSON from OneLake, a blob URI, or a local file path.

    Precedence: an ``onelake://`` seed URI (read from the corpus lake) takes priority, then an Azure
    Blob URL, then a local file path. Anything else returns ``None`` so default seeding can apply.
    """

    seed_uri = settings.ledgerfield_seed_uri
    if seed_uri:
        if seed_uri.startswith("onelake://"):
            return _download_onelake_seed_text(settings, seed_uri)
        return _download_blob_seed_text(seed_uri)

    if not settings.ledgerfield_seed_path:
        return None

    seed_path = Path(settings.ledgerfield_seed_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Configured Ledgerfield seed path does not exist: {seed_path}")
    return seed_path.read_text()


def _download_onelake_seed_text(settings: Settings, seed_uri: str) -> str:
    """Read the seed JSON from the OneLake corpus lake using a managed identity."""

    from .onelake import get_onelake_client

    client = get_onelake_client(settings)
    if not client.configured:
        raise RuntimeError(
            "APP_LEDGERFIELD_SEED_URI uses the onelake:// scheme but APP_ONELAKE_WORKSPACE/"
            "APP_ONELAKE_LAKEHOUSE are not configured."
        )
    lakehouse_relative_path = seed_uri[len("onelake://") :].lstrip("/")
    seed_text = client.read_text(lakehouse_relative_path)
    if seed_text is None:
        raise FileNotFoundError(
            f"Configured OneLake Ledgerfield seed was not found or unreadable: {seed_uri}"
        )
    return seed_text


def _download_blob_seed_text(blob_uri: str) -> str:
    """Download the seed JSON from Azure Blob Storage using a managed identity."""

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobClient
    except ImportError as exc:  # pragma: no cover - exercised only in Azure deployments
        raise RuntimeError(
            "APP_LEDGERFIELD_SEED_URI is set but azure-identity/azure-storage-blob are not "
            "installed. Install the 'azure' optional dependencies to fetch blob seeds."
        ) from exc

    credential = DefaultAzureCredential()
    blob_client = BlobClient.from_blob_url(blob_uri, credential=credential)
    downloaded = blob_client.download_blob()
    return downloaded.readall().decode("utf-8")


async def _bootstrap_postgres_application_role(
    bootstrap_connection: str,
    application_connection: str,
) -> None:
    """Create the application database and least-privilege PostgreSQL login."""

    from .repository import _normalize_postgres_connection_string

    normalized_bootstrap_connection = _normalize_postgres_connection_string(bootstrap_connection)
    normalized_application_connection = _normalize_postgres_connection_string(
        application_connection
    )
    app_info = conninfo_to_dict(normalized_application_connection)
    raw_database_name = app_info.get("dbname")
    raw_application_user = app_info.get("user")
    raw_application_password = app_info.get("password")
    if not raw_database_name or not raw_application_user or not raw_application_password:
        raise ValueError(
            "APP_DATABASE_CONNECTION must include dbname, user, and password when "
            "APP_DATABASE_BOOTSTRAP_CONNECTION is configured"
        )
    database_name = cast(str, raw_database_name)
    application_user = cast(str, raw_application_user)
    application_password = cast(str, raw_application_password)

    async with await psycopg.AsyncConnection.connect(
        normalized_bootstrap_connection,
        autocommit=True,
    ) as connection:
        database_exists = await _postgres_exists(
            connection,
            "select 1 from pg_database where datname = %s",
            database_name,
        )
        if not database_exists:
            await connection.execute(
                sql.SQL("create database {}").format(sql.Identifier(database_name))
            )

        role_exists = await _postgres_exists(
            connection,
            "select 1 from pg_roles where rolname = %s",
            application_user,
        )
        if role_exists:
            await connection.execute(
                sql.SQL("alter role {} with login password {}").format(
                    sql.Identifier(application_user),
                    sql.Literal(application_password),
                )
            )
        else:
            await connection.execute(
                sql.SQL("create role {} with login password {}").format(
                    sql.Identifier(application_user),
                    sql.Literal(application_password),
                )
            )

        await connection.execute(
            sql.SQL("grant connect, create on database {} to {}").format(
                sql.Identifier(database_name),
                sql.Identifier(application_user),
            )
        )

    database_bootstrap_connection = make_conninfo(
        normalized_bootstrap_connection,
        dbname=database_name,
    )
    async with await psycopg.AsyncConnection.connect(
        database_bootstrap_connection,
        autocommit=True,
    ) as connection:
        await connection.execute("revoke create on schema public from public")
        await connection.execute(
            sql.SQL("grant usage, create on schema public to {}").format(
                sql.Identifier(application_user)
            )
        )

    logger.info("Bootstrapped PostgreSQL-compatible database and application role")


async def _bootstrap_fabric_mirroring_role(
    bootstrap_connection: str,
    application_connection: str,
    settings: Settings,
) -> None:
    """Provision the Fabric Mirroring PostgreSQL role using the privileged bootstrap login.

    This is the idempotent, platform-native replacement for running fabric-mirror-role.sql via
    psql on the CI runner. Because the API already holds the admin bootstrap connection, folding
    the role bootstrap in here means the deploy pipeline needs neither an admin connection string
    nor psql -- only the shared mirror password (sourced from the keystone Key Vault). Fabric
    Mirroring connects as a dedicated role that must have LOGIN/CREATEDB/CREATEROLE/REPLICATION,
    the azure_cdc_admin role, and OWN the mirrored tables (a CREATE PUBLICATION requirement).
    Every step is guarded or naturally idempotent, so this is safe to re-run on every startup.
    """

    from .repository import _normalize_postgres_connection_string

    fabric_user = (settings.fabric_mirror_user or "fabric_user").strip()
    fabric_password = settings.fabric_mirror_password
    if not fabric_password:
        logger.warning(
            "APP_FABRIC_MIRROR_ENABLED is set but APP_FABRIC_MIRROR_PASSWORD is empty; "
            "skipping Fabric mirroring role bootstrap"
        )
        return

    normalized_bootstrap_connection = _normalize_postgres_connection_string(bootstrap_connection)
    normalized_application_connection = _normalize_postgres_connection_string(
        application_connection
    )
    app_info = conninfo_to_dict(normalized_application_connection)
    database_name = cast(str, app_info.get("dbname") or "")
    application_user = cast(str, app_info.get("user") or "")
    if not database_name or not application_user:
        raise ValueError(
            "APP_DATABASE_CONNECTION must include dbname and user to bootstrap the "
            "Fabric mirroring role"
        )

    mirrored_tables = [
        table.strip() for table in (settings.fabric_mirror_tables or "").split(",") if table.strip()
    ]

    # Connect with the privileged login but against the application database so the CREATE ROLE
    # (cluster-wide), the database/schema grants, and the per-table ownership transfers all apply
    # in one place.
    database_bootstrap_connection = make_conninfo(
        normalized_bootstrap_connection,
        dbname=database_name,
    )
    async with await psycopg.AsyncConnection.connect(
        database_bootstrap_connection,
        autocommit=True,
    ) as connection:
        # 1) Create (or realign) the mirroring login role with the required attributes.
        role_exists = await _postgres_exists(
            connection,
            "select 1 from pg_roles where rolname = %s",
            fabric_user,
        )
        role_action = "alter role" if role_exists else "create role"
        await connection.execute(
            sql.SQL(
                "{action} {role} with login createdb createrole replication password {password}"
            ).format(
                action=sql.SQL(role_action),
                role=sql.Identifier(fabric_user),
                password=sql.Literal(fabric_password),
            )
        )

        # 2) Grant the Azure CDC management role when present (Azure Database for PostgreSQL only).
        azure_cdc_admin_exists = await _postgres_exists(
            connection,
            "select 1 from pg_roles where rolname = %s",
            "azure_cdc_admin",
        )
        if azure_cdc_admin_exists:
            await connection.execute(
                sql.SQL("grant azure_cdc_admin to {role}").format(role=sql.Identifier(fabric_user))
            )
        else:
            logger.info("azure_cdc_admin role not present (non-Azure PostgreSQL); skipping grant")

        # 3) Allow the mirroring role to create publications/objects in the mirrored database.
        await connection.execute(
            sql.SQL("grant create on database {db} to {role}").format(
                db=sql.Identifier(database_name),
                role=sql.Identifier(fabric_user),
            )
        )
        await connection.execute(
            sql.SQL("grant usage, create on schema public to {role}").format(
                role=sql.Identifier(fabric_user)
            )
        )

        # 4) Transfer ownership of each mirrored table to the mirroring role (required for
        #    CREATE PUBLICATION), then re-grant the application role full DML so writes continue.
        for table_name in mirrored_tables:
            table_exists = await _postgres_exists(
                connection,
                "select 1 from information_schema.tables "
                "where table_schema = 'public' and table_name = %s",
                table_name,
            )
            if not table_exists:
                logger.info(
                    "Mirrored table public.%s does not exist yet; skipping ownership transfer",
                    table_name,
                )
                continue
            await connection.execute(
                sql.SQL("alter table public.{table} owner to {role}").format(
                    table=sql.Identifier(table_name),
                    role=sql.Identifier(fabric_user),
                )
            )
            await connection.execute(
                sql.SQL("grant select, insert, update, delete on public.{table} to {app}").format(
                    table=sql.Identifier(table_name),
                    app=sql.Identifier(application_user),
                )
            )

    logger.info("Bootstrapped Fabric Mirroring PostgreSQL role '%s'", fabric_user)


async def _postgres_exists(
    connection: psycopg.AsyncConnection[object],
    query: str,
    value: str,
) -> bool:
    cursor = await connection.execute(query, (value,))
    return await cursor.fetchone() is not None


async def close_waypoint_repository() -> None:
    """Close the repository singleton and any persistent resources."""

    global _repository, _repository_connection
    repository = _repository
    if repository is not None and hasattr(repository, "close"):
        await repository.close()
    _repository = None
    _repository_connection = None


def reset_waypoint_repository_for_tests() -> None:
    """Reset the repository singleton for tests."""

    global _repository, _repository_connection
    _repository = None
    _repository_connection = None


_repository: "WaypointRepository | None" = None
_repository_connection: str | None = None
