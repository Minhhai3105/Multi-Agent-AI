"""FastAPI application - modular monolith entry point (decision D01).

Startup sequence:
  1. create the schema (MVP; 11 tables),
  2. seed demo data when the database is empty,
  3. recover runs interrupted by a previous shutdown (risk R01),
  4. serve the built React SPA from STATIC_DIR (allocation view: one application host).
"""
from __future__ import annotations

import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import agents_workflows, auth_users, tasks_misc
from app.core.config import get_settings
from app.core.errors import AppError
from app.repositories.database import create_schema
from app.services import runtime

# On Windows, Python reads MIME types from the registry, where .js is often mapped to
# text/plain; browsers then refuse the SPA's module scripts (blank page). Constraint C1
# allows running directly on a personal computer, so pin the types explicitly.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    create_schema()
    if settings.seed_on_startup:
        from app.seed import seed_if_empty

        seed_if_empty()
    if settings.effective_llm_provider == "openai_compatible" and not (settings.llm_base_url and settings.llm_api_key):
        log.warning("LLM_PROVIDER=openai_compatible but LLM_BASE_URL or LLM_API_KEY is empty - Agent steps will fail with config_error")
    repaired = runtime.get_coordinator().recover_interrupted_runs()
    target = settings.llm_base_url if settings.effective_llm_provider == "openai_compatible" else ""
    log.info("LLM provider: %s %s| startup recovery: %s", settings.effective_llm_provider, f"({target}) " if target else "", repaired)
    yield
    runtime.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.4.0",
        description="Multi-Agent AI Platform for Business Process Automation and Work Coordination",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Response-Time-ms"],
    )

    @app.middleware("http")
    async def response_time(request: Request, call_next):
        # Makes QA-3 / QA-5 response measures visible in the browser dev tools.
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, **({"details": exc.details} if exc.details else {})}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_failed", "message": "Dữ liệu không hợp lệ", "details": errors}},
        )

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "llm_provider": settings.effective_llm_provider}

    app.include_router(auth_users.public)
    app.include_router(auth_users.router)
    app.include_router(agents_workflows.router)
    app.include_router(tasks_misc.router)

    static_dir = Path(settings.static_dir)
    if (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found"}})
            root = static_dir.resolve()
            candidate = (static_dir / full_path).resolve()
            if full_path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
