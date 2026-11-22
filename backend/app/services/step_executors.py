"""Step executors (strategy pattern, Architecture Design 6.2.9 - C4 Level 4).

The Coordinator selects an executor by step_type and depends only on the
StepExecutor interface, so a new step type (e.g. condition or tool step) is a new
class and the Coordinator stays unchanged (extension point 6.2.10).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFound
from app.integrations.llm_client import LLMClient, LLMError, LLMRequest
from app.models import StepRun, WorkflowRun
from app.repositories.repos import RunRepository, UserRepository
from app.services.agent_service import AgentService
from app.services.knowledge.knowledge_service import KnowledgeService
from app.services.task_service import TaskService

log = logging.getLogger(__name__)

DONE, FAILED, WAITING = "done", "failed", "waiting"
_TRANSIENT = {"timeout", "rate_limit", "provider_error"}


@dataclass
class StepResult:
    status: str
    output: dict | None = None
    error: str | None = None
    retry_count: int = 0
    meta: dict = field(default_factory=dict)


class StepExecutor(Protocol):
    def execute(self, db: Session, run: WorkflowRun, step_run: StepRun, context: dict) -> StepResult: ...


def format_input(initial_input: dict | None) -> str:
    if not initial_input:
        return "(không có)"
    for key in ("question", "request", "text", "input", "content"):
        if key in initial_input and len(initial_input) == 1:
            return str(initial_input[key])
    return "\n".join(f"- {k}: {v}" for k, v in initial_input.items() if k != "bulk_marker")


class AgentStepExecutor:
    """Loads the Agent configuration, optionally retrieves knowledge (RAG), and calls the
    LLM Client with exactly one automatic retry for transient failures (QA-1)."""

    def __init__(self, llm: LLMClient, settings: Settings):
        self.llm = llm
        self.settings = settings

    def execute(self, db: Session, run: WorkflowRun, step_run: StepRun, context: dict) -> StepResult:
        cfg, error = self.load_config(db, step_run.agent_id)
        if cfg is None:
            return StepResult(FAILED, error=error)
        snap = step_run.step_snapshot or {}
        return self.run_agent(
            db, cfg, format_input(context.get("initial_input")), context,
            step_instruction=snap.get("instruction_override"),
            log_ref=f"run {run.id} step {step_run.step_order}",
        )

    @staticmethod
    def load_config(db: Session, agent_id: int | None):
        """Returns (AgentConfig, None) or (None, error) - Agent Service is the only source."""
        try:
            cfg = AgentService(db).get_config(agent_id) if agent_id else None
        except NotFound:
            cfg = None
        if cfg is None:
            return None, "config_error: Agent không còn tồn tại"
        if not cfg.is_active:
            return None, f"config_error: Agent '{cfg.name}' đang bị vô hiệu hoá"
        return cfg, None

    def run_agent(
        self, db: Session, cfg, task_text: str, context: dict,
        step_instruction: str | None = None, log_ref: str = "",
    ) -> StepResult:
        """One Agent invocation: optional RAG retrieval, prompt building and the LLM call
        with exactly one automatic retry. Shared by workflow steps and Agent tasks (FR4.2)."""
        previous = context.get("previous_output") or ""
        sources: list[dict] = []
        knowledge_block = ""
        if cfg.knowledge_collection:
            query = f"{task_text}\n{previous[:600]}"
            hits = KnowledgeService(db).retrieve(cfg.knowledge_collection, query)
            for n, hit in enumerate(hits, start=1):
                c = hit.chunk
                sources.append({
                    "ref": n,
                    "document": c.document_title,
                    "heading": c.heading,
                    "chunk_index": c.chunk_index,
                    "score": hit.score,
                    "excerpt": c.content[:300],
                })
                knowledge_block += f"[Nguồn {n}] {c.document_title} – {c.heading or 'đoạn ' + str(c.chunk_index + 1)}\n{c.content}\n\n"
            if not hits:
                knowledge_block = "(Không tìm thấy đoạn tài liệu nào liên quan trong bộ tri thức.)"

        request = LLMRequest(
            system_prompt=self._system_prompt(cfg, bool(cfg.knowledge_collection), step_instruction),
            user_prompt=self._user_prompt(task_text, context, previous, knowledge_block),
            model=cfg.model_name,
            temperature=cfg.temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
        )

        attempts: list[dict] = []
        for attempt in (0, 1):  # first call + exactly ONE automatic retry
            try:
                result = self.llm.generate(request, timeout=self.settings.llm_timeout_seconds)
            except LLMError as exc:
                attempts.append({"attempt": attempt + 1, "error": exc.kind, "message": exc.message})
                log.warning("%s attempt %s failed: %s", log_ref, attempt + 1, exc)
                if exc.kind not in _TRANSIENT:
                    break  # configuration errors are not retried (C6: do not waste quota)
                continue
            attempts.append({"attempt": attempt + 1, "ok": True, "latency_ms": result.latency_ms})
            return StepResult(
                DONE,
                output={
                    "text": result.text,
                    "agent_id": cfg.id,
                    "agent_name": cfg.name,
                    "role_name": cfg.role_name,
                    "model": result.model,
                    "provider": result.provider,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage,
                    "sources": sources,
                    "attempts": attempts,
                },
                retry_count=attempt,
            )
        last = attempts[-1]
        return StepResult(
            FAILED,
            output={"attempts": attempts, "sources": sources},
            error=f"{last['error']}: {last['message']}",
            retry_count=1 if len(attempts) > 1 else 0,
        )

    @staticmethod
    def _system_prompt(cfg, has_knowledge: bool, step_instruction: str | None = None) -> str:
        rules = [
            "Trả lời bằng tiếng Việt, rõ ràng, đúng vai trò được giao.",
            "Kết quả của bạn sẽ được chuyển cho bước tiếp theo trong quy trình, hãy trình bày có cấu trúc.",
        ]
        if has_knowledge:
            rules.append(
                "Với thông tin về quy định/nội quy, CHỈ dựa vào phần 'Tri thức tham khảo' và ghi "
                "trích dẫn dạng [Nguồn n]. Nếu tài liệu không đề cập, hãy nói rõ là không tìm thấy "
                "trong tài liệu, không tự suy đoán."
            )
        duty = f"Nhiệm vụ: {cfg.description}\n" if cfg.description else ""
        step = f"\nChỉ dẫn riêng cho bước này:\n{step_instruction.strip()}\n" if step_instruction else ""
        return (
            "Bạn là một AI Agent trong nền tảng đa tác tử tự động hoá quy trình doanh nghiệp.\n"
            f"Tên Agent: {cfg.name}\nVai trò: {cfg.role_name}\n{duty}\n"
            f"Chỉ dẫn:\n{cfg.instruction}\n{step}\nQuy tắc:\n- " + "\n- ".join(rules)
        )

    def _user_prompt(self, task_text: str, context: dict, previous: str, knowledge: str) -> str:
        parts = [f"### Yêu cầu ban đầu\n{task_text}"]
        if previous:
            prev = context.get("previous_step") or {}
            parts.append(f"### Kết quả của bước trước\n(Bước {prev.get('order')}: {prev.get('name')})\n{previous}")
        if knowledge:
            parts.append(f"### Tri thức tham khảo\n{knowledge.strip()}")
        prompt = "\n\n".join(parts)
        limit = self.settings.llm_max_prompt_chars  # C6 / risk R04: bound the context size
        return prompt if len(prompt) <= limit else prompt[:limit] + "\n…(đã cắt bớt)"


class UserApprovalStepExecutor:
    """Creates a task for a user/approval step and returns WAITING without blocking a
    thread (decision D06). Task Service resumes the run when the task is finished."""

    def execute(self, db: Session, run: WorkflowRun, step_run: StepRun, context: dict) -> StepResult:
        snap = step_run.step_snapshot or {}
        users = UserRepository(db)
        assignee_id = snap.get("assignee_user_id")
        if assignee_id:
            user = users.get(assignee_id)
            if user is None or not user.is_active:
                assignee_id = None
        if not assignee_id:
            role = snap.get("assignee_role") or "manager"
            user = users.least_loaded_active_user(role)
            if user is None:
                return StepResult(FAILED, error=f"config_error: Không có người dùng hoạt động với vai trò '{role}'")
            assignee_id = user.id

        config = snap.get("config_json") or {}
        is_approval = step_run.step_type == "approval"
        previous = context.get("previous_output") or "(chưa có kết quả trước đó)"
        title = config.get("task_title") or (
            f"{'Phê duyệt' if is_approval else 'Xử lý'}: {snap.get('name', 'bước ' + str(step_run.step_order))} (lượt chạy #{run.id})"
        )
        description = (
            f"{config.get('instructions') or snap.get('instruction_override') or ''}\n\n"
            f"Yêu cầu ban đầu:\n{format_input(run.initial_input)}\n\n"
            f"Kết quả từ bước trước:\n{previous}"
        ).strip()
        TaskService(db).create_step_task(
            run, step_run, assignee_id, title[:250], description, step_run.step_type,
            priority=config.get("priority", "medium"), deadline_hours=int(config.get("deadline_hours", 24)),
        )
        RunRepository(db).update_step_run(step_run.id, assigned_user_id=assignee_id)
        return StepResult(WAITING, meta={"assigned_user_id": assignee_id})
