"""Workflow Service (FR3): workflow definitions, validation and run initiation.

start_run() persists the run, schedules background execution and returns
immediately so the API can answer 202 Accepted + run_id (QA-3, decision D05).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models import StepRun, Workflow, WorkflowRun, WorkflowStep
from app.models.entities import ROLES, STEP_TYPES, WORKFLOW_STATUSES
from app.repositories.repos import AgentRepository, RunRepository, UserRepository, WorkflowRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles
from app.services.coordinator import WorkflowCoordinator

MAX_STEPS = 10


class WorkflowService:
    def __init__(self, db: Session, coordinator: WorkflowCoordinator | None = None):
        self.db = db
        self.repo = WorkflowRepository(db)
        self.agents = AgentRepository(db)
        self.users = UserRepository(db)
        self.runs = RunRepository(db)
        self.audit = ActivityLogService(db)
        self.coordinator = coordinator

    # ---------------------------------------------------------------- queries
    def list(self, actor: Actor, chat_only: bool = False) -> list[dict]:
        status = None if actor.is_manager_or_admin else "active"
        return [self._serialize(w) for w in self.repo.list(status=status, chat_only=chat_only)]

    def get(self, actor: Actor, workflow_id: int) -> dict:
        workflow = self._require(workflow_id)
        if not actor.is_manager_or_admin and workflow.status != "active":
            raise NotFound("Không tìm thấy workflow")
        return self._serialize(workflow)

    # ---------------------------------------------------------------- commands
    def create(self, actor: Actor, data: dict) -> dict:
        require_roles(actor, "admin", "manager")
        steps = self._validate(data)
        workflow = Workflow(
            name=data["name"].strip(),
            description=(data.get("description") or "").strip(),
            status=data.get("status") or "active",
            is_chat=bool(data.get("is_chat", False)),
            created_by=actor.id,
        )
        workflow.steps = steps
        self.repo.add(workflow)
        self.audit.record(actor.id, "workflow.create", "workflow", workflow.id,
                          f"Tạo workflow '{workflow.name}'", {"steps": len(steps)})
        self.db.commit()
        return self._serialize(self._require(workflow.id))

    def update(self, actor: Actor, workflow_id: int, data: dict) -> dict:
        require_roles(actor, "admin", "manager")
        workflow = self._require(workflow_id)
        merged = {
            "name": data.get("name", workflow.name),
            "status": data.get("status", workflow.status),
            "steps": data.get("steps"),
        }
        changes: dict = {}
        for key in ("name", "description", "status", "is_chat"):
            if key in data and data[key] is not None and data[key] != getattr(workflow, key):
                changes[key] = [str(getattr(workflow, key))[:80], str(data[key])[:80]]
                setattr(workflow, key, data[key].strip() if isinstance(data[key], str) else data[key])
        if data.get("steps") is not None:
            steps = self._validate(merged)
            # Running runs keep their step snapshot (6.1.7); only new runs see the new steps.
            workflow.steps.clear()
            self.db.flush()
            workflow.steps.extend(steps)
            changes["steps"] = len(steps)
        elif merged["status"] == "active" and not workflow.steps:
            raise ValidationFailed("Workflow đang hoạt động phải có ít nhất một bước")
        if changes:
            self.audit.record(actor.id, "workflow.update", "workflow", workflow.id,
                              f"Cập nhật workflow '{workflow.name}'", changes)
            self.db.commit()
        return self._serialize(self._require(workflow.id))

    def start_run(self, actor: Actor, workflow_id: int, initial_input: dict) -> WorkflowRun:
        workflow = self._require(workflow_id)
        if workflow.status != "active":
            raise ValidationFailed("Workflow không ở trạng thái active nên không thể chạy", code="workflow_not_active")
        if not workflow.steps:
            raise ValidationFailed("Workflow chưa có bước nào", code="empty_workflow")
        if not isinstance(initial_input, dict) or not initial_input:
            raise ValidationFailed("Cần nhập dữ liệu đầu vào cho workflow", code="empty_input")

        run = WorkflowRun(
            workflow_id=workflow.id,
            started_by=actor.id,
            status="running",
            current_step_order=0,
            initial_input=initial_input,
        )
        step_runs = [
            StepRun(
                workflow_step_id=s.id,
                step_order=s.step_order,
                step_type=s.step_type,
                agent_id=s.agent_id,
                status="pending",
                retry_count=0,
                step_snapshot={
                    "name": s.name,
                    "step_type": s.step_type,
                    "agent_id": s.agent_id,
                    "assignee_role": s.assignee_role,
                    "assignee_user_id": s.assignee_user_id,
                    "instruction_override": s.instruction_override,
                    "config_json": s.config_json or {},
                },
            )
            for s in workflow.steps
        ]
        self.runs.create_run(run, step_runs)
        self.audit.record(actor.id, "workflow_run.start", "workflow_run", run.id,
                          f"Khởi chạy workflow '{workflow.name}'", {"workflow_id": workflow.id})
        self.db.commit()
        if self.coordinator is not None:
            self.coordinator.schedule_run(run.id)
        return run

    # ---------------------------------------------------------------- helpers
    def _require(self, workflow_id: int) -> Workflow:
        workflow = self.repo.get(workflow_id)
        if workflow is None:
            raise NotFound("Không tìm thấy workflow")
        return workflow

    def _validate(self, data: dict) -> list[WorkflowStep]:
        if not (data.get("name") or "").strip():
            raise ValidationFailed("Tên workflow không được để trống")
        status = data.get("status") or "active"
        if status not in WORKFLOW_STATUSES:
            raise ValidationFailed(f"Trạng thái workflow không hợp lệ: {status}")
        raw_steps = data.get("steps") or []
        if status == "active" and not raw_steps:
            raise ValidationFailed("Workflow đang hoạt động phải có ít nhất một bước")
        if len(raw_steps) > MAX_STEPS:
            raise ValidationFailed(f"Tối đa {MAX_STEPS} bước mỗi workflow (MVP tuần tự 3-5 bước)")

        orders = [s.get("step_order") or (i + 1) for i, s in enumerate(raw_steps)]
        if sorted(orders) != list(range(1, len(raw_steps) + 1)):
            raise ValidationFailed("step_order phải liên tục từ 1 và không trùng lặp", code="invalid_step_order")

        steps: list[WorkflowStep] = []
        for order, s in sorted(zip(orders, raw_steps), key=lambda x: x[0]):
            step_type = s.get("step_type")
            if step_type not in STEP_TYPES:
                raise ValidationFailed(f"Bước {order}: step_type phải là agent, user hoặc approval")
            name = (s.get("name") or "").strip()
            if not name:
                raise ValidationFailed(f"Bước {order}: cần đặt tên bước")
            agent_id = s.get("agent_id")
            assignee_role = s.get("assignee_role")
            assignee_user_id = s.get("assignee_user_id")
            instruction_override = (s.get("instruction_override") or "").strip() or None
            if step_type == "agent":
                agent = self.agents.get(agent_id) if agent_id else None
                if agent is None:
                    raise ValidationFailed(f"Bước {order}: Agent không tồn tại", code="invalid_agent")
                if not agent.is_active:
                    raise ValidationFailed(f"Bước {order}: Agent '{agent.name}' đang bị vô hiệu hoá", code="invalid_agent")
                assignee_role = assignee_user_id = None
            else:
                agent_id = None
                if assignee_user_id:
                    user = self.users.get(assignee_user_id)
                    if user is None or not user.is_active:
                        raise ValidationFailed(f"Bước {order}: người được giao không hợp lệ")
                elif assignee_role not in ROLES:
                    raise ValidationFailed(f"Bước {order}: cần chọn vai trò hoặc người phụ trách")
            steps.append(
                WorkflowStep(
                    step_order=order,
                    step_type=step_type,
                    name=name,
                    agent_id=agent_id,
                    assignee_role=assignee_role,
                    assignee_user_id=assignee_user_id,
                    instruction_override=instruction_override,
                    config_json=s.get("config_json") or {},
                )
            )
        return steps

    def _serialize(self, w: Workflow) -> dict:
        agent_names = {a.id: a.name for a in self.agents.list()}
        return {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "status": w.status,
            "is_chat": w.is_chat,
            "created_by": w.created_by,
            "created_at": w.created_at,
            "updated_at": w.updated_at,
            "steps": [
                {
                    "id": s.id,
                    "step_order": s.step_order,
                    "step_type": s.step_type,
                    "name": s.name,
                    "agent_id": s.agent_id,
                    "agent_name": agent_names.get(s.agent_id),
                    "assignee_role": s.assignee_role,
                    "assignee_user_id": s.assignee_user_id,
                    "instruction_override": s.instruction_override,
                    "config_json": s.config_json or {},
                }
                for s in w.steps
            ],
        }
