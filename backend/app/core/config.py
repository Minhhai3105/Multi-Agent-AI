"""Application settings.

Rule R6 (Architecture Design 6.2.8): secrets and environment configuration are read
ONLY here. No other module may touch os.environ. The architecture conformance check
(scripts/check_architecture.py) enforces this rule.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int

    # LLM (C2: one configured provider at a time, C6: limited calls/tokens)
    llm_provider: str  # "auto" | "gemini" | "openai_compatible" | "mock"
    gemini_api_key: str | None
    gemini_model: str
    gemini_base_url: str
    # OpenAI-compatible gateway, e.g. CLIProxyAPI (http://host.docker.internal:8317/v1)
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str
    llm_timeout_seconds: float
    llm_max_output_tokens: int
    llm_max_prompt_chars: int
    mock_llm_latency_ms: int

    # RAG / knowledge base
    rag_top_k: int
    rag_chunk_size: int
    rag_chunk_overlap: int
    max_upload_mb: int

    # Runtime
    executor_workers: int
    demo_mode: bool
    seed_on_startup: bool
    cors_origins: tuple[str, ...]
    static_dir: str

    # Optional e-mail notification (FR6.3)
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_sender: str | None

    @property
    def effective_llm_provider(self) -> str:
        """openai_compatible and mock are explicit choices; otherwise Gemini is used only
        when a Gemini key is configured and the offline mock provider is the fallback."""
        if self.llm_provider in ("mock", "openai_compatible"):
            return self.llm_provider
        if self.gemini_api_key:
            return "gemini"
        return "mock"


@lru_cache
def get_settings() -> Settings:
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8000")
    return Settings(
        app_name=os.environ.get("APP_NAME", "Multi-Agent AI Platform"),
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/maap"
        ),
        jwt_secret=os.environ.get("JWT_SECRET", "dev-only-change-me-in-env-file-0123456789"),
        jwt_algorithm="HS256",
        jwt_expire_minutes=_int("JWT_EXPIRE_MINUTES", 480),
        llm_provider=os.environ.get("LLM_PROVIDER", "auto").strip().lower(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash",
        gemini_base_url=os.environ.get(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ),
        llm_base_url=os.environ.get("LLM_BASE_URL") or None,
        llm_api_key=os.environ.get("LLM_API_KEY") or None,
        # No silent default: a gateway exposes its own model ids (GET /v1/models).
        llm_model=(os.environ.get("LLM_MODEL") or "").strip(),
        llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 30.0),
        llm_max_output_tokens=_int("LLM_MAX_OUTPUT_TOKENS", 2048),
        llm_max_prompt_chars=_int("LLM_MAX_PROMPT_CHARS", 12000),
        mock_llm_latency_ms=_int("MOCK_LLM_LATENCY_MS", 800),
        rag_top_k=_int("RAG_TOP_K", 4),
        rag_chunk_size=_int("RAG_CHUNK_SIZE", 900),
        rag_chunk_overlap=_int("RAG_CHUNK_OVERLAP", 150),
        max_upload_mb=_int("MAX_UPLOAD_MB", 5),
        executor_workers=_int("EXECUTOR_WORKERS", 4),
        demo_mode=_bool("DEMO_MODE", True),
        seed_on_startup=_bool("SEED_ON_STARTUP", True),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        static_dir=os.environ.get("STATIC_DIR", "static"),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=_int("SMTP_PORT", 587),
        smtp_user=os.environ.get("SMTP_USER") or None,
        smtp_password=os.environ.get("SMTP_PASSWORD") or None,
        smtp_sender=os.environ.get("SMTP_SENDER") or None,
    )
