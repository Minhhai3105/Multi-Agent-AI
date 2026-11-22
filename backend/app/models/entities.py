"""SQLAlchemy entities.

The nine MVP tables from Architecture Design 6.2.6 plus two tables for the
knowledge base (RAG extension, Architecture Design v1.4):

users, agents, workflows, workflow_steps, workflow_runs, step_runs, tasks,
activity_logs, notifications, knowledge_documents, knowledge_chunks.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BigId, JsonType, utcnow

ROLES = ("admin", "manager", "employee")
WORKFLOW_STATUSES = ("draft", "active", "inactive")
STEP_TYPES = ("agent", "user", "approval")
RUN_STATUSES = ("running", "completed", "failed", "cancelled")
STEP_RUN_STATUSES = ("pending", "in_progress", "done", "failed")
TASK_STATUSES = ("todo", "in_progress", "done", "failed")
TASK_PRIORITIES = ("low", "medium", "high")


def _in(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join("'{}'".format(v) for v in values))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_users_role"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("temperature >= 0 AND temperature <= 2", name="ck_agents_temperature"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150))
    role_name: Mapped[str] = mapped_column(String(150))
    # FR2.2: the Agent's duty/mission in plain words (shown to users; ERD agents.description).
    description: Mapped[str] = mapped_column(Text, default="")
    instruction: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(100))
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    # RAG extension: when set, the Agent retrieves context from this knowledge collection.
    knowledge_collection: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Workflow(TimestampMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (CheckConstraint(_in("status", WORKFLOW_STATUSES), name="ck_workflows_status"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Marks workflows offered on the Chat screen (Q&A over the knowledge base).
    is_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow",
        order_by="WorkflowStep.step_order",
        cascade="all, delete-orphan",
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_order", name="uq_workflow_steps_order"),
        CheckConstraint(_in("step_type", STEP_TYPES), name="ck_workflow_steps_type"),
        CheckConstraint("step_order >= 1", name="ck_workflow_steps_order_positive"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    assignee_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # ERD workflow_steps.instruction_override: extra prompt for this step only (agent steps).
    instruction_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict] = mapped_column(JsonType, default=dict)

    workflow: Mapped[Workflow] = relationship(back_populates="steps")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_workflow_runs_status"),
        Index("ix_workflow_runs_wf_status_started", "workflow_id", "status", "started_at"),
        Index("ix_workflow_runs_started_by_started", "started_by", "started_at"),
        Index("ix_workflow_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="running")
    current_step_order: Mapped[int] = mapped_column(Integer, default=0)
    initial_input: Mapped[dict] = mapped_column(JsonType, default=dict)
    final_result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    step_runs: Mapped[list["StepRun"]] = relationship(
        back_populates="workflow_run", order_by="StepRun.step_order"
    )


class StepRun(Base):
    __tablename__ = "step_runs"
    __table_args__ = (
        CheckConstraint(_in("status", STEP_RUN_STATUSES), name="ck_step_runs_status"),
        CheckConstraint("retry_count >= 0 AND retry_count <= 1", name="ck_step_runs_retry"),
        Index("ix_step_runs_run_status", "workflow_run_id", "status"),
        Index("ix_step_runs_agent_finished", "agent_id", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    # SET NULL keeps run history when a workflow definition is edited later.
    workflow_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="SET NULL"), nullable=True
    )
    step_order: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(20))
    # Snapshot of the step definition taken when the run starts (6.1.7: later edits
    # of a workflow affect only new runs).
    step_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    input_context: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    output_result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="step_runs")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="ck_tasks_status"),
        CheckConstraint(_in("priority", TASK_PRIORITIES), name="ck_tasks_priority"),
        Index("ix_tasks_assignee_status", "assigned_user_id", "status"),
        Index(
            "ix_tasks_deadline",
            "deadline",
            postgresql_where=text("deadline IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(20), default="manual")  # manual|user|approval
    workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    step_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("step_runs.id", ondelete="SET NULL"), nullable=True
    )
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_activity_logs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigId, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(_in("channel", ("in_app", "email")), name="ck_notifications_channel"),
        Index("ix_notifications_user_read", "user_id", "is_read", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_knowledge_documents_collection", "collection", "is_active"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    collection: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_index"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
