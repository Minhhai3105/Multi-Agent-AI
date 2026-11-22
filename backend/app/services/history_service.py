"""History & Monitoring (FR7, FR8, QA-5): read-only, paginated, indexed queries.

It never receives pushed events; it reads the persisted run/step/task state.
Employees only see their own runs (UC-08: unauthorized data is not returned).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.repositories.repos import (
    AgentRepository,
    HistoryRepository,
    RunRepository,
    TaskRepository,
    UserRepository,
    WorkflowRepository,
)
from app.services.common import Actor


class HistoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = HistoryRepository(db)
        self.runs = RunRepository(db)
        self.tasks = TaskRepository(db)
        self.users = UserRepository(db)
        self.agents = AgentRepository(db)
        self.workflows = WorkflowRepository(db)

    def list_runs(
        self,
        actor: Actor,
        page: int,
        page_size: int,
        workflow_id: int | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        mine: bool = False,
    ) -> dict:
        started_by = actor.id if (mine or not actor.is_manager_or_admin) else None
        rows, total = self.repo.list_runs(page, page_size, workflow_id, status, started_by, date_from, date_to)
        items = [
            {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "workflow_name": r.workflow_name,
                "status": r.status,
                "current_step_order": r.current_step_order,
                "started_by": r.started_by,
                "started_by_name": r.started_by_name,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "error_message": r.error_message,
                "input_preview": _preview(r.initial_input),
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def run_detail(self, actor: Actor, run_id: int) -> dict:
        run = self.runs.get_run(run_id)
        if run is None:
            raise NotFound("Không tìm thấy lượt chạy")
        tasks = self.tasks.by_run(run_id)
        if not actor.is_manager_or_admin and run.started_by != actor.id and not any(
            t.assigned_user_id == actor.id for t in tasks
        ):
            raise Forbidden("Bạn không có quyền xem lượt chạy này")
        workflow_name = self.workflows.names({run.workflow_id}).get(run.workflow_id)
        agent_names = {a.id: a.name for a in self.agents.list()}
        user_ids = {run.started_by} | {s.assigned_user_id for s in run.step_runs if s.assigned_user_id}
        user_ids |= {t.assigned_user_id for t in tasks if t.assigned_user_id}
        names = self.users.names(user_ids)
        return {
            "id": run.id,
            "workflow_id": run.workflow_id,
            "workflow_name": workflow_name,
            "status": run.status,
            "current_step_order": run.current_step_order,
            "started_by": run.started_by,
            "started_by_name": names.get(run.started_by),
            "initial_input": run.initial_input,
            "final_result": run.final_result,
            "error_message": run.error_message,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "is_waiting": run.status == "running" and any(
                s.status == "in_progress" and s.step_type in ("user", "approval") for s in run.step_runs
            ),
            "steps": [
                {
                    "id": s.id,
                    "step_order": s.step_order,
                    "step_type": s.step_type,
                    "name": (s.step_snapshot or {}).get("name"),
                    "agent_id": s.agent_id,
                    "agent_name": agent_names.get(s.agent_id),
                    "assigned_user_id": s.assigned_user_id,
                    "assigned_user_name": names.get(s.assigned_user_id),
                    "status": s.status,
                    "retry_count": s.retry_count,
                    "input_context": s.input_context,
                    "output_result": s.output_result,
                    "error_message": s.error_message,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                }
                for s in run.step_runs
            ],
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "task_type": t.task_type,
                    "status": t.status,
                    "step_run_id": t.step_run_id,
                    "assigned_user_id": t.assigned_user_id,
                    "assigned_user_name": names.get(t.assigned_user_id),
                    "result": t.result,
                    "deadline": t.deadline,
                }
                for t in tasks
            ],
        }

    def dashboard(self, actor: Actor) -> dict:
        scope = None if actor.is_manager_or_admin else actor.id
        counts = self.repo.run_status_counts(scope)
        completed, failed = counts.get("completed", 0), counts.get("failed", 0)
        finished = completed + failed
        agent_stats = []
        if actor.is_manager_or_admin:
            stats = self.agents.stats()
            for a in self.agents.list():
                s = stats.get(a.id, {})
                agent_stats.append({
                    "id": a.id, "name": a.name, "is_active": a.is_active,
                    "total_runs": s.get("total_runs", 0), "done": s.get("done", 0),
                    "failed": s.get("failed", 0), "last_status": s.get("last_status"),
                    "last_run_at": s.get("last_run_at"),
                })
        return {
            "scope": "all" if scope is None else "mine",
            "runs": {
                "total": sum(counts.values()),
                "running": counts.get("running", 0),
                "waiting_for_human": self.repo.waiting_runs(scope),
                "completed": completed,
                "failed": failed,
                "cancelled": counts.get("cancelled", 0),
                "success_rate": round(completed / finished * 100, 1) if finished else None,
            },
            "steps": self.repo.step_counts() if scope is None else None,
            "tasks": {
                **{k: 0 for k in ("todo", "in_progress", "done", "failed")},
                **self.repo.task_counts(scope),
                "overdue": self.repo.overdue_tasks(scope),
            },
            "runs_per_day": [
                {"day": str(r.day), "completed": int(r.completed or 0), "failed": int(r.failed or 0), "total": int(r.total)}
                for r in self.repo.runs_per_day(14, scope)
            ],
            "workflows": [
                {"id": r.id, "name": r.name, "total": int(r.total), "completed": int(r.completed or 0), "failed": int(r.failed or 0)}
                for r in (self.repo.workflow_stats() if scope is None else [])
            ],
            "agents": agent_stats,
            "recent_failures": [
                {"run_id": r.id, "workflow_name": r.name, "error_message": r.error_message, "finished_at": r.finished_at}
                for r in self.repo.recent_failures(5, scope)
            ],
        }


def _preview(initial_input: dict | None) -> str:
    if not initial_input:
        return ""
    values = [str(v) for k, v in initial_input.items() if k != "bulk_marker"]
    text = " | ".join(values)
    return text[:140] + ("…" if len(text) > 140 else "")
