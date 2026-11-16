"""Small application services: Chat (Q&A over the knowledge base), notifications and the
demo control panel used to trigger the quality-attribute scenarios on stage."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.integrations.llm_client import FaultInjectingLLMClient, LLMClient, MockLLMClient
from app.models import WorkflowRun
from app.repositories.repos import NotificationRepository, RunRepository, WorkflowRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles
from app.services.workflow_service import WorkflowService


class ChatService:
    """The Chat screen does not call the LLM directly: every question starts a run of a
    chat workflow, so it goes through the Coordinator, automatic retry and the audit
    log like any other execution (rule R5)."""

    def __init__(self, db: Session, workflow_service: WorkflowService):
        self.db = db
        self.workflows = WorkflowRepository(db)
        self.workflow_service = workflow_service

    def ask(self, actor: Actor, workflow_id: int, question: str) -> WorkflowRun:
        workflow = self.workflows.get(workflow_id)
        if workflow is None or not workflow.is_chat:
            raise NotFound("Không tìm thấy trợ lý hỏi đáp")
        question = question.strip()
        if not question:
            raise ValidationFailed("Câu hỏi không được để trống")
        if len(question) > 2000:
            raise ValidationFailed("Câu hỏi tối đa 2000 ký tự")
        return self.workflow_service.start_run(actor, workflow_id, {"question": question})

    def history(self, actor: Actor, workflow_id: int, limit: int = 20) -> list[dict]:
        runs = RunRepository(self.db).recent_runs_for_user(workflow_id, actor.id, limit)
        return [
            {
                "run_id": r.id,
                "question": (r.initial_input or {}).get("question", ""),
                "status": r.status,
                "answer": (r.final_result or {}).get("text"),
                "sources": (r.final_result or {}).get("sources", []),
                "error_message": r.error_message,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
            }
            for r in reversed(runs)
        ]


class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationRepository(db)

    def list(self, actor: Actor) -> dict:
        rows, unread = self.repo.list_for_user(actor.id)
        return {"items": rows, "unread": unread}

    def mark_read(self, actor: Actor, notification_id: int | None) -> dict:
        count = self.repo.mark_read(actor.id, notification_id)
        self.db.commit()
        return {"updated": count}


class DemoService:
    """Admin-only controls, enabled with DEMO_MODE=true, to inject LLM faults (QA-1/QA-4)."""

    def __init__(self, db: Session, llm: LLMClient):
        self.db = db
        self.llm = llm
        self.settings = get_settings()
        self.audit = ActivityLogService(db)

    def info(self) -> dict:
        inner = self.llm.inner if isinstance(self.llm, FaultInjectingLLMClient) else self.llm
        fault = self.llm.status() if isinstance(self.llm, FaultInjectingLLMClient) else None
        return {
            "demo_mode": self.settings.demo_mode,
            "provider": inner.provider_name,
            "default_model": self.settings.gemini_model,
            "llm_timeout_seconds": self.settings.llm_timeout_seconds,
            "mock_latency_ms": inner.latency_ms if isinstance(inner, MockLLMClient) else None,
            "fault": vars(fault) if fault else None,
        }

    def set_fault(self, actor: Actor, mode: str, count: int, kind: str) -> dict:
        require_roles(actor, "admin")
        if not isinstance(self.llm, FaultInjectingLLMClient):
            raise Forbidden("DEMO_MODE đang tắt nên không thể giả lập lỗi")
        if mode not in ("none", "fail_next", "fail_always", "timeout_next"):
            raise ValidationFailed("mode phải là none | fail_next | fail_always | timeout_next")
        if kind not in ("provider_error", "rate_limit"):
            raise ValidationFailed("kind phải là provider_error | rate_limit")
        self.llm.configure(mode, count, kind)
        self.audit.record(actor.id, "demo.set_llm_fault", "system", None,
                          f"Giả lập lỗi LLM: {mode} x{count} ({kind})", {"mode": mode, "count": count, "kind": kind})
        self.db.commit()
        return self.info()

    def set_mock_latency(self, actor: Actor, latency_ms: int) -> dict:
        require_roles(actor, "admin")
        inner = self.llm.inner if isinstance(self.llm, FaultInjectingLLMClient) else self.llm
        if not isinstance(inner, MockLLMClient):
            raise ValidationFailed("Chỉ chỉnh được độ trễ khi đang dùng LLM mô phỏng")
        if not 0 <= latency_ms <= 60000:
            raise ValidationFailed("latency_ms trong khoảng 0 - 60000")
        inner.latency_ms = latency_ms
        self.audit.record(actor.id, "demo.set_mock_latency", "system", None,
                          f"Đặt độ trễ LLM mô phỏng = {latency_ms} ms")
        self.db.commit()
        return self.info()
