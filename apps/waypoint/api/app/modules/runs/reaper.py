"""Background sweeper that auto-fails stale active agent runs."""

import asyncio
import contextlib
import logging

from ...common.database import get_waypoint_repository_for_settings
from ...common.settings import Settings
from .service import RunsService

logger = logging.getLogger(__name__)


async def _sweep_once(settings: Settings) -> None:
    repository = await get_waypoint_repository_for_settings(settings)
    service = RunsService(repository)
    reaped = await service.reap_stale_runs(
        running_ttl_seconds=settings.run_reaper_ttl_seconds,
        pending_ttl_seconds=settings.run_reaper_pending_ttl_seconds,
    )
    if reaped:
        logger.info(
            "Stale-run reaper failed %d run(s) past the running=%ds/pending=%ds TTL: %s",
            len(reaped),
            settings.run_reaper_ttl_seconds,
            settings.run_reaper_pending_ttl_seconds,
            ", ".join(run.id for run in reaped),
        )


async def _reaper_loop(settings: Settings) -> None:
    interval = max(1, settings.run_reaper_sweep_interval_seconds)
    logger.info(
        "Starting stale-run reaper (running_ttl=%ds, pending_ttl=%ds, interval=%ds)",
        settings.run_reaper_ttl_seconds,
        settings.run_reaper_pending_ttl_seconds,
        interval,
    )
    while True:
        try:
            await _sweep_once(settings)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a sweep failure must never crash the app lifespan
            logger.exception("Stale-run reaper sweep failed; will retry on the next interval")
        await asyncio.sleep(interval)


def start_run_reaper(settings: Settings) -> asyncio.Task[None] | None:
    """Start the background reaper task, or return None when disabled."""

    if not settings.run_reaper_enabled:
        logger.info("Stale-run reaper disabled (APP_RUN_REAPER_ENABLED=false)")
        return None
    return asyncio.create_task(_reaper_loop(settings))


async def stop_run_reaper(task: asyncio.Task[None] | None) -> None:
    """Cancel and await the background reaper task if it is running."""

    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
