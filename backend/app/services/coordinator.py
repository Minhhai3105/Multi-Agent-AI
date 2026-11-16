"""Workflow Coordinator - the single orchestrator of workflow runs (rule R5).

Responsibilities (Architecture Design 6.2.9):
    execute_run(run_id)                 run the ordered steps in the background
    resume_after_task(step_run_id, ..)  continue after a user/approval task is finished
    retry_failed_step(actor, id)        UC-07: re-run only the failed step (claim => 409)
    recover_interrupted_runs()          risk R01: repair runs interrupted by a restart

Only this class changes workflow_runs.status after creation. State is persisted after
every step, so a failure never loses completed work (QA-1) and a failed step can be
re-executed alone from its persisted input_context (QA-4).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import Conflict, Forbidden, NotFound
from app.integrations.llm_client import LLMClient
from app.integrations.notification_adapter import NotificationAdapter
from app.models import StepRun, WorkflowRun
from app.models.base import utcnow
from app.repositories.repos import RunRepository, TaskRepository, UserRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor
from app.services.step_executors import (
    DONE,
    FAILED,
    WAITING,
    AgentStepExecutor,
    StepExecutor,
    StepResult,
    UserApprovalStepExecutor,
)

log = logging.getLogger(__name__)
INTERRUPTED = "interrupted: tiến trình backend dừng khi bước đang chạy (khởi động lại để retry)"


class RunScheduler:
    """In-process background execution (decision D05). Extension point: replace with a
    worker queue (e.g. Celery) without changing the run/step state model."""

    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="workflow")

    def submit(self, fn: Callable, *args) -> None:
        self._pool.submit(self._safe, fn, *args)

    @staticmethod
    def _safe(fn: Callable, *args) -> None:
        try:
            fn(*args)
        except Exception:  # never let a background failure disappear silently
            log.exception("Background workflow job failed")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class WorkflowCoordinator:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        llm: LLMClient,
        scheduler: RunScheduler,
        settings: Settings,
    ):
        self.session_factory = session_factory
        self.scheduler = scheduler
        self.executors: dict[str, StepExecutor] = {
            "agent": AgentStepExecutor(llm, settings),
            "user": UserApprovalStepExecutor(),
            "approval": UserApprovalStepExecutor(),
        }
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ================================================================ public API
    def schedule_run(self, run_id: int) -> None:
        self.scheduler.submit(self.execute_run, run_id)

    def schedule_resume(self, step_run_id: int, task_id: int) -> None:
        self.scheduler.submit(self.resume_after_task, step_run_id, task_id)

    def execute_run(self, run_id: int, start_step_run_id: int | None = None) -> None:
        with self._run_lock(run_id), self.session_factory() as db:
            self._advance(db, run_id, start_step_run_id)

    def resume_after_task(self, step_run_id: int, task_id: int) -> None:
        with self.session_factory() as db:
            step = RunRepository(db).get_step_run(step_run_id)
            if step is None:
                return
            run_id = step.workflow_run_id
        with self._run_lock(run_id), self.session_factory() as db:
            runs = RunRepository(db)
            step = runs.get_step_run(step_run_id)
            task = TaskRepository(db).get(task_id)
            if step is None or task is None or step.status != "in_progress":
                return  # idempotent: already handled
            result = task.result or {}
            actor_name = UserRepository(db).names({task.assigned_user_id}).get(task.assigned_user_id, "người dùng")
            rejected = task.status == "failed" or result.get("decision") == "rejected"
            if rejected:
                reason = result.get("comment") or "không có lý do"
                error = f"rejected: {actor_name} từ chối ở bước {step.step_order} – {reason}"
                if runs.claim_step_run(step.id, "in_progress", "failed", error_message=error, finished_at=utcnow()):
                    self._fail_run(db, step.workflow_run_id, step, error)
                    db.commit()
                return
            previous_text = (step.input_context or {}).get("previous_output") or ""
            output = {
                "text": result.get("text") or result.get("comment") or previous_text,
                "decision": result.get("decision", "done"),
                "comment": result.get("comment"),
                "completed_by": actor_name,
                "task_id": task.id,
                "passed_through": previous_text if step.step_type == "approval" else None,
            }
            if step.step_type == "approval" and result.get("decision") == "approved":
                # Approval passes the approved content forward, plus the reviewer's note.
                note = f"\n\n[Đã được {actor_name} phê duyệt" + (f": {result.get('comment')}]" if result.get("comment") else "]")
                output["text"] = (previous_text or "") + note
            if not runs.claim_step_run(step.id, "in_progress", "done", output_result=output, finished_at=utcnow()):
                return
            runs.update_run(step.workflow_run_id, current_step_order=step.step_order)
            db.commit()
            self._advance(db, step.workflow_run_id)

    def retry_failed_step(self, db: Session, actor: Actor, step_run_id: int) -> StepRun:
        """Synchronous part of UC-07: authorise and claim; execution continues in the background."""
        runs = RunRepository(db)
        step = runs.get_step_run(step_run_id)
        if step is None:
            raise NotFound("Không tìm thấy bước cần retry")
        run = runs.get_run(step.workflow_run_id)
        if not actor.is_manager_or_admin and run.started_by != actor.id:
            raise Forbidden("Bạn chỉ được retry lượt chạy do chính mình khởi động", code="not_run_owner")
        claimed = runs.claim_step_run(
            step.id, "failed", "in_progress", error_message=None, started_at=utcnow(), finished_at=None
        )
        if not claimed:
            raise Conflict("Bước này không ở trạng thái failed hoặc đang được retry", code="step_not_failed")
        runs.update_run(run.id, status="running", error_message=None, finished_at=None)
        ActivityLogService(db).record(
            actor.id, "step_run.manual_retry", "step_run", step.id,
            f"Retry thủ công bước {step.step_order} của lượt chạy #{run.id}",
            {"workflow_run_id": run.id, "previous_error": step.error_message},
        )
        db.commit()
        self.scheduler.submit(self.execute_run, run.id, step.id)
        db.refresh(step)
        return step

    def recover_interrupted_runs(self) -> dict:
        """Risk R01 / 6.1.7. Called once at startup.

        Refinement of v1.3: only *agent* steps left in_progress are interrupted work.
        A user/approval step in_progress is a legitimate wait on a persisted task, so
        its run keeps waiting instead of being failed.
        """
        repaired = {"interrupted_steps": 0, "runs_failed": 0}
        with self.session_factory() as db:
            runs = RunRepository(db)
            for step in runs.interrupted_agent_steps():
                if runs.claim_step_run(step.id, "in_progress", "failed", error_message=INTERRUPTED, finished_at=utcnow()):
                    self._fail_run(db, step.workflow_run_id, step, INTERRUPTED, notify=False)
                    repaired["interrupted_steps"] += 1
                    repaired["runs_failed"] += 1
            for run in runs.running_runs_without_active_step():
                pending = [s for s in runs.step_runs_of(run.id) if s.status == "pending"]
                if not pending:
                    self._complete_run(db, run.id)
                    continue
                first = pending[0]
                msg = "interrupted: backend dừng giữa hai bước, bước này chưa được thực thi"
                runs.update_step_run(first.id, status="failed", error_message=msg, finished_at=utcnow())
                self._fail_run(db, run.id, first, msg, notify=False)
                repaired["runs_failed"] += 1
            db.commit()
        if repaired["runs_failed"]:
            log.warning("Startup recovery: %s", repaired)
        return repaired

    # ================================================================ internals
    def _advance(self, db: Session, run_id: int, start_step_run_id: int | None = None) -> None:
        runs = RunRepository(db)
        while True:
            db.expire_all()
            run = runs.get_run(run_id)
            if run is None or run.status != "running":
                return
            steps = runs.step_runs_of(run_id)
            target: StepRun | None = None
            for step in steps:
                if step.status == "done":
                    continue
                if step.status == "in_progress":
                    if step.id == start_step_run_id:
                        target = step
                        break
                    return  # waiting for a human task (or handled by another job)
                if step.status == "failed":
                    return
                # pending -> claim it with the context built from the previous step
                context = self._build_context(run, steps, step)
                if not runs.claim_step_run(step.id, "pending", "in_progress", input_context=context, started_at=utcnow()):
                    return
                db.commit()
                db.refresh(step)
                target = step
                break
            if target is None:
                self._complete_run(db, run_id)
                db.commit()
                return

            if target.id == start_step_run_id:
                # Manual retry: reuse the persisted input_context (QA-4).
                context = target.input_context or self._build_context(run, steps, target)
                if not target.input_context:
                    runs.update_step_run(target.id, input_context=context)
                    db.commit()
                start_step_run_id = None
            else:
                context = target.input_context or {}

            result = self._execute(db, run, target, context)

            if result.status == DONE:
                runs.update_step_run(
                    target.id, status="done", output_result=result.output, error_message=None,
                    retry_count=result.retry_count, finished_at=utcnow(),
                )
                runs.update_run(run_id, current_step_order=target.step_order)
                db.commit()
                continue
            if result.status == WAITING:
                runs.update_run(run_id, current_step_order=target.step_order)
                db.commit()
                return
            # FAILED: keep completed steps, persist the error, stop the run.
            runs.update_step_run(
                target.id, status="failed", error_message=result.error, output_result=result.output,
                retry_count=result.retry_count, finished_at=utcnow(),
            )
            self._fail_run(db, run_id, target, result.error or "unknown error")
            db.commit()
            return

    def _execute(self, db: Session, run: WorkflowRun, step: StepRun, context: dict) -> StepResult:
        executor = self.executors.get(step.step_type)
        if executor is None:
            return StepResult(FAILED, error=f"config_error: step_type '{step.step_type}' chưa được hỗ trợ")
        try:
            return executor.execute(db, run, step, context)
        except Exception as exc:  # a bug must not leave the run 'running' forever
            log.exception("Executor crashed on run %s step %s", run.id, step.step_order)
            db.rollback()
            return StepResult(FAILED, error=f"internal_error: {type(exc).__name__}")

    @staticmethod
    def _build_context(run: WorkflowRun, steps: list[StepRun], target: StepRun) -> dict:
        """Risk R04: pass only the initial input and the previous step's output."""
        previous = None
        for s in steps:
            if s.step_order < target.step_order and s.status == "done":
                previous = s
        return {
            "initial_input": run.initial_input,
            "previous_step": (
                {"order": previous.step_order, "name": (previous.step_snapshot or {}).get("name"), "type": previous.step_type}
                if previous else None
            ),
            "previous_output": (previous.output_result or {}).get("text") if previous else None,
        }

    def _complete_run(self, db: Session, run_id: int) -> None:
        runs = RunRepository(db)
        run = runs.get_run(run_id)
        steps = runs.step_runs_of(run_id)
        sources, summary = [], []
        for s in steps:
            out = s.output_result or {}
            summary.append({
                "order": s.step_order,
                "name": (s.step_snapshot or {}).get("name"),
                "type": s.step_type,
                "agent_name": out.get("agent_name"),
                "decision": out.get("decision"),
                "text": out.get("text"),
            })
            for src in out.get("sources") or []:
                sources.append({**src, "step_order": s.step_order})
        final_text = next((x["text"] for x in reversed(summary) if x.get("text")), "")
        runs.update_run(
            run_id, status="completed", finished_at=utcnow(),
            current_step_order=steps[-1].step_order if steps else 0,
            final_result={"text": final_text, "steps": summary, "sources": sources},
        )
        ActivityLogService(db).record(
            None, "workflow_run.complete", "workflow_run", run_id, f"Lượt chạy #{run_id} hoàn thành"
        )
        NotificationAdapter(db).notify(
            run.started_by, "Workflow đã hoàn thành", f"Lượt chạy #{run_id} đã hoàn thành.",
            link=f"/runs/{run_id}",
        )

    def _fail_run(self, db: Session, run_id: int, step: StepRun, error: str, notify: bool = True) -> None:
        runs = RunRepository(db)
        name = (step.step_snapshot or {}).get("name") or f"bước {step.step_order}"
        message = f"Bước {step.step_order} ({name}) thất bại – {error}"
        runs.update_run(run_id, status="failed", error_message=message, finished_at=utcnow())
        ActivityLogService(db).record(
            None, "workflow_run.fail", "workflow_run", run_id, message,
            {"step_run_id": step.id, "step_order": step.step_order},
        )
        if notify:
            run = runs.get_run(run_id)
            NotificationAdapter(db).notify(
                run.started_by, "Workflow thất bại", f"Lượt chạy #{run_id}: {message}", link=f"/runs/{run_id}"
            )

    def _run_lock(self, run_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())
