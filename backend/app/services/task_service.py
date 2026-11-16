"""Task Service (FR4): human work coordination.

Tasks come from two sources:
  * manual tasks created by a Manager/Admin;
  * user/approval steps of a workflow (created by UserApprovalStepExecutor).

When a step task is finished the Task Service hands control back to the Workflow
Coordinator through `on_step_task_finished`, a callback injected by the composition
root (app.api.deps). Task Service therefore has no import dependency on the
Coordinator, which keeps the module graph acyclic (rule R5).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.integrations.notification_adapter import NotificationAdapter
from app.models import StepRun, Task, WorkflowRun
from app.models.entities import TASK_PRIORITIES
from app.repositories.repos import AgentRepository, RunRepository, TaskRepository, UserRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles

# Allowed status transitions (409 otherwise). failed -> todo is the "re-assign/rerun"
# path of FR4.5 for manual tasks; step tasks are rerun through UC-07 instead.
_TRANSITIONS = {
    "todo": {"in_progress", "done", "failed"},
    "in_progress": {"todo", "done", "failed"},
    "done": set(),
    "failed": {"todo"},
}

StepTaskCallback = Callable[[int, int], None]


class TaskService:
    def __init__(self, db: Session, on_step_task_finished: StepTaskCallback | None = None):
        self.db = db
        self.repo = TaskRepository(db)
        self.users = UserRepository(db)
        self.agents = AgentRepository(db)
        self.runs = RunRepository(db)
        self.audit = ActivityLogService(db)
        self.notifier = NotificationAdapter(db)
        self.on_step_task_finished = on_step_task_finished

    # ---------------------------------------------------------------- queries
    def list(
        self, actor: Actor, page: int, page_size: int, status: str | None, mine: bool,
        workflow_run_id: int | None = None,
    ) -> dict:
        assigned = actor.id if (mine or not actor.is_manager_or_admin) else None
        rows, total = self.repo.list(page, page_size, assigned, status, workflow_run_id)
        return {"items": self._decorate(rows), "total": total, "page": page, "page_size": page_size}

    def get(self, actor: Actor, task_id: int) -> dict:
        task = self._require(task_id)
        if not actor.is_manager_or_admin and task.assigned_user_id != actor.id:
            raise Forbidden("Bạn chỉ được xem task được giao cho mình")
        return self._decorate([task])[0]

    # ---------------------------------------------------------------- commands
    def create_manual(self, actor: Actor, data: dict) -> dict:
        require_roles(actor, "admin", "manager")
        priority = data.get("priority") or "medium"
        if priority not in TASK_PRIORITIES:
            raise ValidationFailed("priority phải là low, medium hoặc high")
        if not (data.get("title") or "").strip():
            raise ValidationFailed("Tiêu đề task không được để trống")
        assigned_user_id = data.get("assigned_user_id")
        assigned_agent_id = data.get("assigned_agent_id")
        self._check_assignee(assigned_user_id, assigned_agent_id)
        task = self.repo.add(
            Task(
                title=data["title"].strip(),
                description=(data.get("description") or "").strip(),
                task_type="manual",
                assigned_user_id=assigned_user_id,
                assigned_agent_id=assigned_agent_id,
                created_by=actor.id,
                priority=priority,
                status="todo",
                deadline=data.get("deadline"),
            )
        )
        self.audit.record(actor.id, "task.create", "task", task.id, f"Tạo task '{task.title}'",
                          {"assigned_user_id": assigned_user_id, "priority": priority})
        self.notifier.notify(assigned_user_id, "Bạn được giao task mới", task.title, link=f"/tasks?focus={task.id}")
        self.db.commit()
        return self._decorate([task])[0]

    def create_step_task(
        self, run: WorkflowRun, step_run: StepRun, assignee_id: int, title: str,
        description: str, task_type: str, priority: str = "medium", deadline_hours: int = 24,
    ) -> Task:
        """Called by UserApprovalStepExecutor inside the Coordinator's transaction."""
        task = self.repo.add(
            Task(
                title=title,
                description=description,
                task_type=task_type,
                workflow_run_id=run.id,
                step_run_id=step_run.id,
                assigned_user_id=assignee_id,
                created_by=run.started_by,
                priority=priority if priority in TASK_PRIORITIES else "medium",
                status="todo",
                deadline=datetime.now(timezone.utc) + timedelta(hours=deadline_hours),
            )
        )
        self.audit.record(
            None, "task.create_from_step", "task", task.id,
            f"Bước {step_run.step_order} của lượt chạy #{run.id} tạo task '{title}'",
            {"workflow_run_id": run.id, "step_run_id": step_run.id, "assigned_user_id": assignee_id},
        )
        verb = "duyệt" if task_type == "approval" else "xử lý"
        self.notifier.notify(assignee_id, f"Có việc cần bạn {verb}", title, link=f"/tasks?focus={task.id}")
        return task

    def update(self, actor: Actor, task_id: int, data: dict) -> dict:
        task = self._require(task_id)
        is_assignee = task.assigned_user_id == actor.id
        if not actor.is_manager_or_admin and not is_assignee:
            raise Forbidden("Chỉ người được giao hoặc Manager/Admin mới được cập nhật task", code="not_assignee")

        changes: dict = {}
        # --- assignment / planning fields (Manager/Admin only)
        planning = {k: data[k] for k in ("assigned_user_id", "assigned_agent_id", "priority", "deadline", "title", "description") if k in data}
        if planning:
            if not actor.is_manager_or_admin:
                raise Forbidden("Nhân viên chỉ được cập nhật trạng thái và kết quả task của mình")
            if "priority" in planning and planning["priority"] not in TASK_PRIORITIES:
                raise ValidationFailed("priority phải là low, medium hoặc high")
            if "assigned_user_id" in planning or "assigned_agent_id" in planning:
                self._check_assignee(planning.get("assigned_user_id", task.assigned_user_id),
                                     planning.get("assigned_agent_id", task.assigned_agent_id))
            for key, value in planning.items():
                if value != getattr(task, key):
                    changes[key] = [str(getattr(task, key)), str(value)]
                    setattr(task, key, value)
            if "assigned_user_id" in changes:
                self.notifier.notify(task.assigned_user_id, "Bạn được giao lại một task", task.title,
                                     link=f"/tasks?focus={task.id}")
                if task.step_run_id:
                    self.runs.update_step_run(task.step_run_id, assigned_user_id=task.assigned_user_id)

        if "result" in data and data["result"] is not None:
            task.result = data["result"]
            changes["result"] = data["result"]

        # --- status transition (conditional update => 409 on races)
        new_status = data.get("status")
        finished_step_task = False
        if new_status and new_status != task.status:
            allowed = _TRANSITIONS.get(task.status, set())
            if new_status not in allowed:
                raise Conflict(f"Không thể chuyển task từ '{task.status}' sang '{new_status}'",
                               code="invalid_transition")
            if task.status == "failed" and task.step_run_id:
                raise Conflict("Task của workflow bị từ chối/thất bại: hãy retry bước đó (UC-07)",
                               code="invalid_transition")
            if task.task_type == "approval" and new_status == "done":
                decision = (task.result or {}).get("decision")
                if decision not in ("approved", "rejected"):
                    raise ValidationFailed("Task phê duyệt cần result.decision = approved | rejected")
            old_status = task.status
            self.db.flush()
            if not self.repo.change_status(task.id, old_status, new_status):
                raise Conflict("Task vừa được người khác cập nhật, hãy tải lại", code="concurrent_update")
            self.db.refresh(task)
            changes["status"] = [old_status, new_status]
            finished_step_task = bool(task.step_run_id) and new_status in ("done", "failed")

        if changes:
            action = "task.complete" if changes.get("status", [None, None])[1] == "done" else "task.update"
            if (task.result or {}).get("decision") == "approved" and action == "task.complete":
                action = "task.approve"
            elif (task.result or {}).get("decision") == "rejected" and action == "task.complete":
                action = "task.reject"
            self.audit.record(actor.id, action, "task", task.id, f"Cập nhật task '{task.title}'", _jsonable(changes))
        self.db.commit()

        if finished_step_task and self.on_step_task_finished:
            self.on_step_task_finished(task.step_run_id, task.id)
        return self._decorate([task])[0]

    # ---------------------------------------------------------------- helpers
    def _require(self, task_id: int) -> Task:
        task = self.repo.get(task_id)
        if task is None:
            raise NotFound("Không tìm thấy task")
        return task

    def _check_assignee(self, user_id: int | None, agent_id: int | None) -> None:
        if user_id is not None:
            user = self.users.get(user_id)
            if user is None or not user.is_active:
                raise ValidationFailed("Người được giao không tồn tại hoặc đã bị vô hiệu hoá")
        if agent_id is not None:
            agent = self.agents.get(agent_id)
            if agent is None or not agent.is_active:
                raise ValidationFailed("Agent được giao không tồn tại hoặc đã bị vô hiệu hoá")

    def _decorate(self, tasks: list[Task]) -> list[dict]:
        names = self.users.names({t.assigned_user_id for t in tasks if t.assigned_user_id}
                                 | {t.created_by for t in tasks if t.created_by})
        now = datetime.now(timezone.utc)
        out = []
        for t in tasks:
            out.append({
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "task_type": t.task_type,
                "workflow_run_id": t.workflow_run_id,
                "step_run_id": t.step_run_id,
                "assigned_user_id": t.assigned_user_id,
                "assigned_user_name": names.get(t.assigned_user_id),
                "assigned_agent_id": t.assigned_agent_id,
                "created_by": t.created_by,
                "created_by_name": names.get(t.created_by),
                "priority": t.priority,
                "status": t.status,
                "deadline": t.deadline,
                "is_overdue": bool(t.deadline and t.deadline < now and t.status in ("todo", "in_progress")),
                "result": t.result,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            })
        return out


def _jsonable(changes: dict) -> dict:
    return {k: (v if isinstance(v, (list, dict, str, int, float, bool, type(None))) else str(v))
            for k, v in changes.items()}
