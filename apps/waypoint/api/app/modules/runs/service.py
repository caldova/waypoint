"""Business logic for agent run anchors."""

from datetime import timedelta
from uuid import uuid4

from ...common.repository import WaypointRepository
from ...common.tracer import trace
from ..records.service import _now
from .schemas import AgentRun, AgentRunCreate, AgentRunUpdate

ACTIVE_RUN_STATUSES: tuple[str, ...] = ("running", "pending")
REAPABLE_STATUSES: tuple[str, ...] = ("running",)
_ENRICHABLE_FIELDS: tuple[str, ...] = (
    "app_insights_operation_id",
    "foundry_agent_name",
    "foundry_conversation_id",
)


class RunsService:
    """Service boundary for agent run correlation anchors."""

    def __init__(self, repository: WaypointRepository) -> None:
        self.repository = repository

    @trace
    async def create_agent_run(
        self,
        run_create: AgentRunCreate,
        *,
        actor: str,
    ) -> AgentRun:
        run, _created = await self.create_or_reuse_agent_run(run_create, actor=actor)
        return run

    async def create_or_reuse_agent_run(
        self,
        run_create: AgentRunCreate,
        *,
        actor: str,
    ) -> tuple[AgentRun, bool]:
        """Create a run anchor or return the matching idempotent/active anchor."""

        if run_create.case_id and not await self.repository.get_case(run_create.case_id):
            raise ValueError(f"Case '{run_create.case_id}' not found.")
        now = _now()
        candidate = AgentRun(
            id=f"run-{uuid4().hex}",
            created_by=actor,
            created_at=now,
            updated_at=now,
            **run_create.model_dump(),
        )
        run, created = await self.repository.create_or_reuse_agent_run(
            candidate, ACTIVE_RUN_STATUSES
        )
        if created:
            return run, True
        return await self._reuse_run(run, run_create), False

    async def _reuse_run(self, existing: AgentRun, run_create: AgentRunCreate) -> AgentRun:
        """Return an existing anchor and backfill correlation ids that are still absent."""

        current = existing
        for _attempt in range(3):
            enrichment = {
                field: getattr(run_create, field)
                for field in _ENRICHABLE_FIELDS
                if getattr(run_create, field) and not getattr(current, field)
            }
            if not enrichment:
                return current
            enriched = current.model_copy(update={**enrichment, "updated_at": _now()})
            if await self.repository.compare_and_swap_agent_run(enriched, current):
                return enriched
            latest = await self.repository.get_agent_run(current.id)
            if latest is None:
                raise RuntimeError(f"Run '{current.id}' disappeared during correlation backfill.")
            current = latest
        raise RuntimeError(f"Run '{current.id}' changed repeatedly during correlation backfill.")

    @trace
    async def update_agent_run(
        self,
        run_id: str,
        run_update: AgentRunUpdate,
    ) -> AgentRun | None:
        existing = await self.repository.get_agent_run(run_id)
        if existing is None:
            return None
        changes = run_update.model_dump(exclude_unset=True)
        if not changes:
            return existing
        current = existing
        for _attempt in range(3):
            updated = current.model_copy(update={**changes, "updated_at": _now()})
            if await self.repository.compare_and_swap_agent_run(updated, current):
                return updated
            latest = await self.repository.get_agent_run(run_id)
            if latest is None:
                return None
            current = latest
        raise RuntimeError(f"Run '{run_id}' changed repeatedly during update.")

    @trace
    async def list_agent_runs(self, case_id: str | None = None) -> list[AgentRun]:
        return await self.repository.list_agent_runs(case_id=case_id)

    @trace
    async def reap_stale_runs(
        self,
        *,
        running_ttl_seconds: int,
        pending_ttl_seconds: int | None = None,
    ) -> list[AgentRun]:
        """Fail stale runs with a compare-and-swap write so a concurrent finalize wins."""

        reaped = await self._reap(REAPABLE_STATUSES, running_ttl_seconds)
        if pending_ttl_seconds is not None and pending_ttl_seconds > 0:
            reaped.extend(await self._reap(("pending",), pending_ttl_seconds))
        return reaped

    async def _reap(self, statuses: tuple[str, ...], ttl_seconds: int) -> list[AgentRun]:
        cutoff = _now() - timedelta(seconds=ttl_seconds)
        stale = await self.repository.list_stale_active_runs(cutoff, statuses)
        reaped: list[AgentRun] = []
        for run in stale:
            now = _now()
            metadata = {
                **run.metadata,
                "reaped": True,
                "reap_reason": (
                    f"Run stuck in '{run.status}' exceeded the {ttl_seconds}s reaper TTL "
                    "without finalizing."
                ),
                "reaped_at": now.isoformat(),
            }
            candidate = run.model_copy(
                update={"status": "failed", "metadata": metadata, "updated_at": now}
            )
            if await self.repository.reap_agent_run(candidate, cutoff, statuses):
                reaped.append(candidate)
        return reaped
