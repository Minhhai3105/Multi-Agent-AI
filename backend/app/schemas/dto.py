"""Pydantic request/response DTOs (validation at the HTTP boundary)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "manager", "employee"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth / users
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserOut


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    current_password: str | None = None
    new_password: str | None = Field(default=None, max_length=200)


class UserCreateIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    role: Role
    password: str = Field(min_length=8, max_length=200)


class UserUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    is_active: bool | None = None


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


# ------------------------------------------------------------------ agents
class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    role_name: str = Field(min_length=1, max_length=150)
    instruction: str = Field(min_length=1, max_length=8000)
    model_name: str = Field(default="gemini-2.5-flash", max_length=100)
    temperature: float = Field(default=0.3, ge=0, le=2)
    knowledge_collection: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class AgentUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    role_name: str | None = Field(default=None, max_length=150)
    instruction: str | None = Field(default=None, max_length=8000)
    model_name: str | None = Field(default=None, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    knowledge_collection: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


# ------------------------------------------------------------------ workflows
class WorkflowStepIn(BaseModel):
    step_order: int | None = Field(default=None, ge=1)
    step_type: Literal["agent", "user", "approval"]
    name: str = Field(min_length=1, max_length=200)
    agent_id: int | None = None
    assignee_role: Role | None = None
    assignee_user_id: int | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    status: Literal["draft", "active", "inactive"] = "active"
    is_chat: bool = False
    steps: list[WorkflowStepIn] = Field(default_factory=list)


class WorkflowUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "active", "inactive"] | None = None
    is_chat: bool | None = None
    steps: list[WorkflowStepIn] | None = None


class RunStartIn(BaseModel):
    input: dict[str, Any] = Field(description="Initial input passed to the first step")


class RunAcceptedOut(BaseModel):
    run_id: int
    status: str
    status_url: str


class StepRetryOut(BaseModel):
    step_run_id: int
    workflow_run_id: int
    status: str


# ------------------------------------------------------------------ tasks
class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=8000)
    assigned_user_id: int | None = None
    assigned_agent_id: int | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    deadline: datetime | None = None


class TaskUpdateIn(BaseModel):
    status: Literal["todo", "in_progress", "done", "failed"] | None = None
    result: dict[str, Any] | None = None
    assigned_user_id: int | None = None
    assigned_agent_id: int | None = None
    priority: Literal["low", "medium", "high"] | None = None
    deadline: datetime | None = None
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=8000)


# ------------------------------------------------------------------ misc
class NotificationOut(ORMModel):
    id: int
    title: str
    message: str
    channel: str
    is_read: bool
    link: str | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class KnowledgeDocumentOut(ORMModel):
    id: int
    collection: str
    title: str
    filename: str
    content_type: str
    char_count: int
    chunk_count: int
    created_at: datetime


class ChatAskIn(BaseModel):
    workflow_id: int
    question: str = Field(min_length=1, max_length=2000)


class FaultIn(BaseModel):
    mode: Literal["none", "fail_next", "fail_always", "timeout_next"]
    count: int = Field(default=1, ge=0, le=10)
    kind: Literal["provider_error", "rate_limit"] = "provider_error"


class LatencyIn(BaseModel):
    latency_ms: int = Field(ge=0, le=60000)
