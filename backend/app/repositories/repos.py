"""Repository / ORM layer (Architecture Design 6.2, rule R3).

Every SQL query of the application lives in this module. Services receive a
Session and use these repositories; routers never see the ORM.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ActivityLog,
    Agent,
    KnowledgeChunk,
    KnowledgeDocument,
    Notification,
    StepRun,
    Task,
    User,
    Workflow,
    WorkflowRun,
    WorkflowStep,
)
from app.models.base import utcnow


def _page(stmt, page: int, page_size: int):
    return stmt.offset((page - 1) * page_size).limit(page_size)


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def list(self, page: int, page_size: int, role: str | None = None) -> tuple[list[User], int]:
        stmt = select(User)
        if role:
            stmt = stmt.where(User.role == role)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(_page(stmt.order_by(User.id), page, page_size)).all()
        return list(rows), total

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user

    def count(self) -> int:
        return self.db.scalar(select(func.count(User.id))) or 0

    def least_loaded_active_user(self, role: str) -> User | None:
        """Work coordination: pick the active user of a role with the fewest open tasks."""
        open_tasks = (
            select(Task.assigned_user_id, func.count(Task.id).label("open_count"))
            .where(Task.status.in_(("todo", "in_progress")))
            .group_by(Task.assigned_user_id)
            .subquery()
        )
        stmt = (
            select(User)
            .outerjoin(open_tasks, open_tasks.c.assigned_user_id == User.id)
            .where(User.role == role, User.is_active.is_(True))
            .order_by(func.coalesce(open_tasks.c.open_count, 0), User.id)
            .limit(1)
        )
        return self.db.scalar(stmt)

    def names(self, ids: set[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = self.db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all()
        return {r.id: r.full_name for r in rows}


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, agent_id: int) -> Agent | None:
        return self.db.get(Agent, agent_id)

    def list(self, include_inactive: bool = True) -> list[Agent]:
        stmt = select(Agent).order_by(Agent.id)
        if not include_inactive:
            stmt = stmt.where(Agent.is_active.is_(True))
        return list(self.db.scalars(stmt).all())

    def add(self, agent: Agent) -> Agent:
        self.db.add(agent)
        self.db.flush()
        return agent

    def delete(self, agent: Agent) -> None:
        self.db.delete(agent)

    def has_history(self, agent_id: int) -> bool:
        used_in_runs = self.db.scalar(
            select(func.count(StepRun.id)).where(StepRun.agent_id == agent_id)
        )
        used_in_steps = self.db.scalar(
            select(func.count(WorkflowStep.id)).where(WorkflowStep.agent_id == agent_id)
        )
        return bool(used_in_runs) or bool(used_in_steps)

    def stats(self) -> dict[int, dict]:
        """FR2.5 / FR7.1: latest status and success/failure counts per Agent."""
        counts = self.db.execute(
            select(
                StepRun.agent_id,
                func.count(StepRun.id).label("total"),
                func.sum(case((StepRun.status == "done", 1), else_=0)).label("done"),
                func.sum(case((StepRun.status == "failed", 1), else_=0)).label("failed"),
                func.max(StepRun.finished_at).label("last_at"),
            )
            .where(StepRun.agent_id.is_not(None))
            .group_by(StepRun.agent_id)
        ).all()
        result = {
            r.agent_id: {
                "total_runs": int(r.total or 0),
                "done": int(r.done or 0),
                "failed": int(r.failed or 0),
                "last_run_at": r.last_at,
                "last_status": None,
            }
            for r in counts
        }
        if result:
            latest = (
                select(StepRun.agent_id, func.max(StepRun.id).label("max_id"))
                .where(StepRun.agent_id.in_(result.keys()))
                .group_by(StepRun.agent_id)
                .subquery()
            )
            rows = self.db.execute(
                select(StepRun.agent_id, StepRun.status).join(latest, StepRun.id == latest.c.max_id)
            ).all()
            for r in rows:
                result[r.agent_id]["last_status"] = r.status
        return result


class WorkflowRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, workflow_id: int) -> Workflow | None:
        return self.db.scalar(
            select(Workflow).options(selectinload(Workflow.steps)).where(Workflow.id == workflow_id)
        )

    def list(self, status: str | None = None, chat_only: bool = False) -> list[Workflow]:
        stmt = select(Workflow).options(selectinload(Workflow.steps)).order_by(Workflow.id)
        if status:
            stmt = stmt.where(Workflow.status == status)
        if chat_only:
            stmt = stmt.where(Workflow.is_chat.is_(True))
        return list(self.db.scalars(stmt).all())

    def add(self, workflow: Workflow) -> Workflow:
        self.db.add(workflow)
        self.db.flush()
        return workflow

    def names(self, ids: set[int]) -> dict[int, str]:
        if not ids:
            return {}
        rows = self.db.execute(select(Workflow.id, Workflow.name).where(Workflow.id.in_(ids))).all()
        return {r.id: r.name for r in rows}


class RunRepository:
    """Persists workflow_runs and step_runs (QA-1, QA-4)."""

    def __init__(self, db: Session):
        self.db = db

    def create_run(self, run: WorkflowRun, step_runs: list[StepRun]) -> WorkflowRun:
        self.db.add(run)
        self.db.flush()
        for sr in step_runs:
            sr.workflow_run_id = run.id
            self.db.add(sr)
        self.db.flush()
        return run

    def get_run(self, run_id: int) -> WorkflowRun | None:
        return self.db.scalar(
            select(WorkflowRun)
            .options(selectinload(WorkflowRun.step_runs))
            .where(WorkflowRun.id == run_id)
        )

    def get_step_run(self, step_run_id: int) -> StepRun | None:
        return self.db.get(StepRun, step_run_id)

    def step_runs_of(self, run_id: int) -> list[StepRun]:
        return list(
            self.db.scalars(
                select(StepRun).where(StepRun.workflow_run_id == run_id).order_by(StepRun.step_order)
            ).all()
        )

    def claim_step_run(self, step_run_id: int, expected_status: str, new_status: str, **values) -> bool:
        """Conditional update (R03): succeeds only if the current status matches."""
        result = self.db.execute(
            update(StepRun)
            .where(StepRun.id == step_run_id, StepRun.status == expected_status)
            .values(status=new_status, **values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def claim_run(self, run_id: int, expected_statuses: tuple[str, ...], new_status: str, **values) -> bool:
        """Conditional run status change: a cancelled run is never overwritten by a
        background job that finishes later (FR3.4)."""
        result = self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status.in_(expected_statuses))
            .values(status=new_status, **values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def update_run(self, run_id: int, **values) -> None:
        self.db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    def update_step_run(self, step_run_id: int, **values) -> None:
        self.db.execute(
            update(StepRun)
            .where(StepRun.id == step_run_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    def recent_runs_for_user(self, workflow_id: int, user_id: int, limit: int) -> list[WorkflowRun]:
        return list(
            self.db.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.workflow_id == workflow_id, WorkflowRun.started_by == user_id)
                .order_by(WorkflowRun.id.desc())
                .limit(limit)
            ).all()
        )

    def interrupted_agent_steps(self) -> list[StepRun]:
        """Agent steps left in_progress (their thread died with the process)."""
        return list(
            self.db.scalars(
                select(StepRun)
                .join(WorkflowRun, WorkflowRun.id == StepRun.workflow_run_id)
                .where(
                    WorkflowRun.status == "running",
                    StepRun.status == "in_progress",
                    StepRun.step_type == "agent",
                )
            ).all()
        )

    def running_runs_without_active_step(self) -> list[WorkflowRun]:
        """Runs still 'running' but with no step in progress (crash between two steps)."""
        active = select(StepRun.workflow_run_id).where(StepRun.status == "in_progress")
        return list(
            self.db.scalars(
                select(WorkflowRun).where(
                    WorkflowRun.status == "running", WorkflowRun.id.not_in(active)
                )
            ).all()
        )


class TaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, task_id: int) -> Task | None:
        return self.db.get(Task, task_id)

    def add(self, task: Task) -> Task:
        self.db.add(task)
        self.db.flush()
        return task

    def change_status(self, task_id: int, expected: str, new: str, **values) -> bool:
        result = self.db.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == expected)
            .values(status=new, updated_at=utcnow(), **values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def list(
        self,
        page: int,
        page_size: int,
        assigned_user_id: int | None = None,
        status: str | None = None,
        workflow_run_id: int | None = None,
    ) -> tuple[list[Task], int]:
        stmt = select(Task)
        if assigned_user_id is not None:
            stmt = stmt.where(Task.assigned_user_id == assigned_user_id)
        if status:
            stmt = stmt.where(Task.status == status)
        if workflow_run_id:
            stmt = stmt.where(Task.workflow_run_id == workflow_run_id)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        order = case((Task.status.in_(("todo", "in_progress")), 0), else_=1)
        rows = self.db.scalars(_page(stmt.order_by(order, Task.id.desc()), page, page_size)).all()
        return list(rows), total

    def interrupted_agent_tasks(self) -> list[Task]:
        """Manual tasks left in_progress by an Agent whose background thread died.

        Only tasks started through run-agent (result.agent_running) qualify; a task a
        person moved to in_progress by hand is legitimate work and is left alone.
        """
        rows = self.db.scalars(
            select(Task).where(
                Task.task_type == "manual",
                Task.assigned_agent_id.is_not(None),
                Task.status == "in_progress",
            )
        ).all()
        return [t for t in rows if (t.result or {}).get("agent_running")]

    def by_step_run(self, step_run_id: int) -> list[Task]:
        return list(self.db.scalars(select(Task).where(Task.step_run_id == step_run_id)).all())

    def by_run(self, run_id: int) -> list[Task]:
        return list(
            self.db.scalars(select(Task).where(Task.workflow_run_id == run_id).order_by(Task.id)).all()
        )


class ActivityLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, log: ActivityLog) -> None:
        self.db.add(log)

    def list(
        self,
        page: int,
        page_size: int,
        entity_type: str | None = None,
        entity_id: int | None = None,
        user_id: int | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[ActivityLog], int]:
        stmt = select(ActivityLog)
        if entity_type:
            stmt = stmt.where(ActivityLog.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(ActivityLog.entity_id == entity_id)
        if user_id is not None:
            stmt = stmt.where(ActivityLog.user_id == user_id)
        if action:
            stmt = stmt.where(ActivityLog.action == action)
        if date_from:
            stmt = stmt.where(ActivityLog.created_at >= date_from)
        if date_to:
            stmt = stmt.where(ActivityLog.created_at <= date_to)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(
            _page(stmt.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()), page, page_size)
        ).all()
        return list(rows), total


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, notification: Notification) -> Notification:
        self.db.add(notification)
        self.db.flush()
        return notification

    def list_for_user(self, user_id: int, limit: int = 30) -> tuple[list[Notification], int]:
        rows = self.db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        ).all()
        unread = self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        )
        return list(rows), int(unread or 0)

    def mark_read(self, user_id: int, notification_id: int | None = None) -> int:
        stmt = update(Notification).where(Notification.user_id == user_id)
        if notification_id is not None:
            stmt = stmt.where(Notification.id == notification_id)
        result = self.db.execute(stmt.values(is_read=True).execution_options(synchronize_session=False))
        return result.rowcount


class KnowledgeRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_document(self, doc: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> KnowledgeDocument:
        self.db.add(doc)
        self.db.flush()
        for c in chunks:
            c.document_id = doc.id
            self.db.add(c)
        self.db.flush()
        return doc

    def get_document(self, doc_id: int) -> KnowledgeDocument | None:
        return self.db.get(KnowledgeDocument, doc_id)

    def list_documents(self, collection: str | None = None) -> list[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.is_active.is_(True))
        if collection:
            stmt = stmt.where(KnowledgeDocument.collection == collection)
        return list(self.db.scalars(stmt.order_by(KnowledgeDocument.id.desc())).all())

    def collections(self) -> list[tuple[str, int, int]]:
        rows = self.db.execute(
            select(
                KnowledgeDocument.collection,
                func.count(KnowledgeDocument.id),
                func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0),
            )
            .where(KnowledgeDocument.is_active.is_(True))
            .group_by(KnowledgeDocument.collection)
            .order_by(KnowledgeDocument.collection)
        ).all()
        return [(r[0], int(r[1]), int(r[2])) for r in rows]

    def chunks_of_collection(self, collection: str) -> list[tuple[KnowledgeChunk, str]]:
        rows = self.db.execute(
            select(KnowledgeChunk, KnowledgeDocument.title)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeDocument.collection == collection, KnowledgeDocument.is_active.is_(True))
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
        ).all()
        return [(r[0], r[1]) for r in rows]

    def chunks_of_document(self, doc_id: int) -> list[KnowledgeChunk]:
        return list(
            self.db.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == doc_id)
                .order_by(KnowledgeChunk.chunk_index)
            ).all()
        )

    def collection_version(self, collection: str) -> tuple[int, int]:
        """Cheap fingerprint used to invalidate the in-memory BM25 index."""
        row = self.db.execute(
            select(func.count(KnowledgeDocument.id), func.coalesce(func.max(KnowledgeDocument.id), 0))
            .where(KnowledgeDocument.collection == collection, KnowledgeDocument.is_active.is_(True))
        ).one()
        return int(row[0]), int(row[1])


class HistoryRepository:
    """Read-only query path for History & Monitoring (QA-5)."""

    def __init__(self, db: Session):
        self.db = db

    def list_runs(
        self,
        page: int,
        page_size: int,
        workflow_id: int | None = None,
        status: str | None = None,
        started_by: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[tuple], int]:
        conditions = []
        if workflow_id:
            conditions.append(WorkflowRun.workflow_id == workflow_id)
        if status:
            conditions.append(WorkflowRun.status == status)
        if started_by is not None:
            conditions.append(WorkflowRun.started_by == started_by)
        if date_from:
            conditions.append(WorkflowRun.started_at >= date_from)
        if date_to:
            conditions.append(WorkflowRun.started_at <= date_to)
        where = and_(*conditions) if conditions else None

        count_stmt = select(func.count(WorkflowRun.id))
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = self.db.scalar(count_stmt) or 0

        stmt = (
            select(
                WorkflowRun.id,
                WorkflowRun.workflow_id,
                Workflow.name.label("workflow_name"),
                WorkflowRun.status,
                WorkflowRun.current_step_order,
                WorkflowRun.started_by,
                User.full_name.label("started_by_name"),
                WorkflowRun.started_at,
                WorkflowRun.finished_at,
                WorkflowRun.error_message,
                WorkflowRun.initial_input,
            )
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
            .join(User, User.id == WorkflowRun.started_by)
        )
        if where is not None:
            stmt = stmt.where(where)
        stmt = _page(stmt.order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc()), page, page_size)
        return list(self.db.execute(stmt).all()), int(total)

    def run_status_counts(self, started_by: int | None = None) -> dict[str, int]:
        stmt = select(WorkflowRun.status, func.count(WorkflowRun.id)).group_by(WorkflowRun.status)
        if started_by is not None:
            stmt = stmt.where(WorkflowRun.started_by == started_by)
        return {r[0]: int(r[1]) for r in self.db.execute(stmt).all()}

    def waiting_runs(self, started_by: int | None = None) -> int:
        stmt = (
            select(func.count(func.distinct(WorkflowRun.id)))
            .join(StepRun, StepRun.workflow_run_id == WorkflowRun.id)
            .where(
                WorkflowRun.status == "running",
                StepRun.status == "in_progress",
                StepRun.step_type.in_(("user", "approval")),
            )
        )
        if started_by is not None:
            stmt = stmt.where(WorkflowRun.started_by == started_by)
        return int(self.db.scalar(stmt) or 0)

    def runs_per_day(self, days: int, started_by: int | None = None) -> list[tuple]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        day = func.date(WorkflowRun.started_at)
        stmt = (
            select(
                day.label("day"),
                func.sum(case((WorkflowRun.status == "completed", 1), else_=0)).label("completed"),
                func.sum(case((WorkflowRun.status == "failed", 1), else_=0)).label("failed"),
                func.count(WorkflowRun.id).label("total"),
            )
            .where(WorkflowRun.started_at >= since)
            .group_by(day)
            .order_by(day)
        )
        if started_by is not None:
            stmt = stmt.where(WorkflowRun.started_by == started_by)
        return list(self.db.execute(stmt).all())

    def workflow_stats(self, limit: int = 8) -> list[tuple]:
        stmt = (
            select(
                Workflow.id,
                Workflow.name,
                func.count(WorkflowRun.id).label("total"),
                func.sum(case((WorkflowRun.status == "completed", 1), else_=0)).label("completed"),
                func.sum(case((WorkflowRun.status == "failed", 1), else_=0)).label("failed"),
            )
            .join(WorkflowRun, WorkflowRun.workflow_id == Workflow.id)
            .group_by(Workflow.id, Workflow.name)
            .order_by(func.count(WorkflowRun.id).desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).all())

    def step_counts(self) -> dict[str, int]:
        rows = self.db.execute(select(StepRun.status, func.count(StepRun.id)).group_by(StepRun.status)).all()
        return {r[0]: int(r[1]) for r in rows}

    def task_counts(self, assigned_user_id: int | None = None) -> dict[str, int]:
        stmt = select(Task.status, func.count(Task.id)).group_by(Task.status)
        if assigned_user_id is not None:
            stmt = stmt.where(Task.assigned_user_id == assigned_user_id)
        return {r[0]: int(r[1]) for r in self.db.execute(stmt).all()}

    def overdue_tasks(self, assigned_user_id: int | None = None) -> int:
        stmt = select(func.count(Task.id)).where(
            Task.deadline.is_not(None),
            Task.deadline < datetime.now(timezone.utc),
            Task.status.in_(("todo", "in_progress")),
        )
        if assigned_user_id is not None:
            stmt = stmt.where(Task.assigned_user_id == assigned_user_id)
        return int(self.db.scalar(stmt) or 0)

    def recent_failures(self, limit: int = 5, started_by: int | None = None) -> list[tuple]:
        stmt = (
            select(
                WorkflowRun.id,
                Workflow.name,
                WorkflowRun.error_message,
                WorkflowRun.finished_at,
            )
            .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
            .where(WorkflowRun.status == "failed")
            .order_by(WorkflowRun.finished_at.desc().nulls_last(), WorkflowRun.id.desc())
            .limit(limit)
        )
        if started_by is not None:
            stmt = stmt.where(WorkflowRun.started_by == started_by)
        return list(self.db.execute(stmt).all())

