"""API routes for agent run anchors."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...common.auth import UserContext, require_reader, require_writer
from ...common.database import get_waypoint_repository
from ...common.repository import WaypointRepository
from ...common.tracer import trace_span
from .schemas import AgentRun, AgentRunCreate, AgentRunUpdate
from .service import RunsService

router = APIRouter(prefix="", tags=["runs"])


async def get_runs_service(
    repository: Annotated[WaypointRepository, Depends(get_waypoint_repository)],
) -> RunsService:
    return RunsService(repository)


@router.get("/runs", response_model=list[AgentRun])
async def list_agent_runs(
    _user: Annotated[UserContext, Depends(require_reader)],
    service: Annotated[RunsService, Depends(get_runs_service)],
    case_id: str | None = Query(default=None),
) -> list[AgentRun]:
    with trace_span("list_agent_runs_endpoint", attributes={"case_id": case_id or ""}):
        return await service.list_agent_runs(case_id=case_id)


@router.post("/runs", response_model=AgentRun, status_code=201)
async def create_agent_run(
    run: AgentRunCreate,
    user: Annotated[UserContext, Depends(require_writer)],
    service: Annotated[RunsService, Depends(get_runs_service)],
) -> AgentRun:
    with trace_span("create_agent_run_endpoint"):
        try:
            return await service.create_agent_run(run, actor=_actor(user))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/runs/{run_id}", response_model=AgentRun)
async def update_agent_run(
    run_id: str,
    run_update: AgentRunUpdate,
    _user: Annotated[UserContext, Depends(require_writer)],
    service: Annotated[RunsService, Depends(get_runs_service)],
) -> AgentRun:
    with trace_span("update_agent_run_endpoint", attributes={"run_id": run_id}):
        updated = await service.update_agent_run(run_id, run_update)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
        return updated


def _actor(user: UserContext) -> str:
    assert user.email is not None
    return user.email
