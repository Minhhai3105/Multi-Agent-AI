"""UC-03 Manage Agents, UC-04 Manage Workflows, UC-05 Execute Workflow, UC-07 Retry."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import RetryContext, agent_service, get_actor, history_service, retry_context, workflow_service
from app.schemas.dto import (
    AgentIn,
    AgentUpdateIn,
    RunAcceptedOut,
    RunStartIn,
    StepRetryOut,
    WorkflowIn,
    WorkflowUpdateIn,
)
from app.services.agent_service import AgentService
from app.services.common import Actor
from app.services.history_service import HistoryService
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/api", tags=["agents & workflows"])


# ------------------------------------------------------------------ agents
@router.get("/agents")
def list_agents(actor: Actor = Depends(get_actor), svc: AgentService = Depends(agent_service)):
    return svc.list(actor)


@router.post("/agents", status_code=201)
def create_agent(body: AgentIn, actor: Actor = Depends(get_actor), svc: AgentService = Depends(agent_service)):
    return svc.create(actor, body.model_dump())


@router.get("/agents/{agent_id}")
def get_agent(agent_id: int, actor: Actor = Depends(get_actor), svc: AgentService = Depends(agent_service)):
    return svc.get(agent_id)


@router.put("/agents/{agent_id}")
def update_agent(
    agent_id: int, body: AgentUpdateIn, actor: Actor = Depends(get_actor), svc: AgentService = Depends(agent_service)
):
    return svc.update(actor, agent_id, body.model_dump(exclude_unset=True))


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: int, actor: Actor = Depends(get_actor), svc: AgentService = Depends(agent_service)):
    return svc.delete(actor, agent_id)


# ------------------------------------------------------------------ workflows
@router.get("/workflows")
def list_workflows(
    chat_only: bool = False, actor: Actor = Depends(get_actor), svc: WorkflowService = Depends(workflow_service)
):
    return svc.list(actor, chat_only=chat_only)


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowIn, actor: Actor = Depends(get_actor), svc: WorkflowService = Depends(workflow_service)):
    return svc.create(actor, body.model_dump())


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: int, actor: Actor = Depends(get_actor), svc: WorkflowService = Depends(workflow_service)):
    return svc.get(actor, workflow_id)


@router.put("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int, body: WorkflowUpdateIn, actor: Actor = Depends(get_actor),
    svc: WorkflowService = Depends(workflow_service),
):
    return svc.update(actor, workflow_id, body.model_dump(exclude_unset=True))


@router.post("/workflows/{workflow_id}/run", status_code=status.HTTP_202_ACCEPTED, response_model=RunAcceptedOut)
def run_workflow(
    workflow_id: int, body: RunStartIn, actor: Actor = Depends(get_actor),
    svc: WorkflowService = Depends(workflow_service),
):
    run = svc.start_run(actor, workflow_id, body.input)
    return RunAcceptedOut(run_id=run.id, status=run.status, status_url=f"/api/workflow-runs/{run.id}")


# ------------------------------------------------------------------ runs
@router.get("/workflow-runs/{run_id}")
def get_run(run_id: int, actor: Actor = Depends(get_actor), svc: HistoryService = Depends(history_service)):
    return svc.run_detail(actor, run_id)


@router.post("/step-runs/{step_run_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=StepRetryOut)
def retry_step(step_run_id: int, actor: Actor = Depends(get_actor), ctx: RetryContext = Depends(retry_context)):
    step = ctx.retry(actor, step_run_id)
    return StepRetryOut(step_run_id=step.id, workflow_run_id=step.workflow_run_id, status=step.status)


@router.get("/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),  # QA-5: page size <= 50
    workflow_id: int | None = None,
    status: str | None = None,
    date_from: datetime | None = Query(None, description="ISO date/time"),
    date_to: datetime | None = Query(None, description="ISO date/time"),
    mine: bool = False,
    actor: Actor = Depends(get_actor),
    svc: HistoryService = Depends(history_service),
):
    return svc.list_runs(actor, page, page_size, workflow_id, status, date_from, date_to, mine)


@router.get("/dashboard/summary")
def dashboard(actor: Actor = Depends(get_actor), svc: HistoryService = Depends(history_service)):
    return svc.dashboard(actor)
