"""Composition root for HTTP requests.

* get_db: one SQLAlchemy session per request.
* get_actor: the single authorization boundary (QA-2). Every protected router
  depends on it, so a request without a valid JWT is rejected with 401 before any
  business logic runs; role checks inside services return 403.
* Service factories: routers receive ready-made services and never touch the ORM
  (rule R2).
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.repositories.database import SessionLocal
from app.services.agent_service import AgentService
from app.services.auth_service import AuthService
from app.services.common import Actor
from app.services.coordinator import WorkflowCoordinator
from app.services.history_service import HistoryService
from app.services.knowledge.knowledge_service import KnowledgeService
from app.services.misc_services import ChatService, DemoService, NotificationService
from app.services.runtime import get_coordinator, get_llm_client
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.services.workflow_service import WorkflowService
from app.services.activity_log_service import ActivityLogService


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def get_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    return AuthService(db).resolve_token(_bearer_token(request))


def coordinator() -> WorkflowCoordinator:
    return get_coordinator()


def auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


def agent_service(db: Session = Depends(get_db)) -> AgentService:
    return AgentService(db)


def workflow_service(db: Session = Depends(get_db)) -> WorkflowService:
    return WorkflowService(db, get_coordinator())


def task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db, on_step_task_finished=get_coordinator().schedule_resume)


def history_service(db: Session = Depends(get_db)) -> HistoryService:
    return HistoryService(db)


def activity_log_service(db: Session = Depends(get_db)) -> ActivityLogService:
    return ActivityLogService(db)


def knowledge_service(db: Session = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)


def chat_service(db: Session = Depends(get_db)) -> ChatService:
    return ChatService(db, WorkflowService(db, get_coordinator()))


def notification_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def demo_service(db: Session = Depends(get_db)) -> DemoService:
    return DemoService(db, get_llm_client())


class RetryContext:
    """Bundles what UC-07 needs: the request session and the Coordinator."""

    def __init__(self, db: Session, coordinator: WorkflowCoordinator):
        self.db = db
        self.coordinator = coordinator

    def retry(self, actor: Actor, step_run_id: int):
        return self.coordinator.retry_failed_step(self.db, actor, step_run_id)


def retry_context(db: Session = Depends(get_db)) -> RetryContext:
    return RetryContext(db, get_coordinator())
