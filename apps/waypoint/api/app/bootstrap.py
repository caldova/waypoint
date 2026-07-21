"""Deploy-owned database bootstrap entry point.

Separates privileged PostgreSQL role/database provisioning from ordinary request-serving
startup. The API runtime connects only as the least-privilege application role; this command
holds the privileged ``APP_DATABASE_BOOTSTRAP_CONNECTION`` and performs the one-time (but
idempotent) provisioning the runtime must not do: creating the application database and login
role, applying the schema, and optionally provisioning the Fabric Mirroring role.

Run it before starting the API::

    python -m app.bootstrap

It is idempotent and safe to re-run. Any failure propagates and exits non-zero -- schema or
bootstrap failures are never silently swallowed. When the deploy pipeline runs this command it
should also set ``APP_RUN_STARTUP_DATABASE_BOOTSTRAP=false`` so the API startup skips the
privileged path entirely.
"""

import asyncio
import logging

from .common.database import bootstrap_database
from .common.settings import Settings, get_settings

logger = logging.getLogger(__name__)


async def run(settings: Settings | None = None) -> None:
    """Run the idempotent privileged database bootstrap."""

    await bootstrap_database(settings or get_settings())


def main() -> None:
    """CLI entry point: ``python -m app.bootstrap`` / ``waypoint-bootstrap``."""

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
