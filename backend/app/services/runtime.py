"""Process-wide singletons: the LLM client, the background scheduler and the Coordinator.

There is exactly one instance of each per backend process (C3: single host,
no multi-instance), created lazily and shut down with the application.
"""
from __future__ import annotations

import threading

from app.core.config import get_settings
from app.integrations.llm_client import LLMClient, build_llm_client
from app.repositories.database import SessionLocal
from app.services.coordinator import RunScheduler, WorkflowCoordinator

_lock = threading.Lock()
_llm: LLMClient | None = None
_scheduler: RunScheduler | None = None
_coordinator: WorkflowCoordinator | None = None


def get_llm_client() -> LLMClient:
    global _llm
    with _lock:
        if _llm is None:
            _llm = build_llm_client(get_settings())
        return _llm


def get_coordinator() -> WorkflowCoordinator:
    global _scheduler, _coordinator
    llm = get_llm_client()
    with _lock:
        if _coordinator is None:
            settings = get_settings()
            _scheduler = RunScheduler(settings.executor_workers)
            _coordinator = WorkflowCoordinator(SessionLocal, llm, _scheduler, settings)
        return _coordinator


def shutdown() -> None:
    global _scheduler, _coordinator, _llm
    with _lock:
        if _scheduler is not None:
            _scheduler.shutdown()
        _scheduler = None
        _coordinator = None
        _llm = None
