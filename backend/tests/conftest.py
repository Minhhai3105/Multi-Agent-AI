"""Test configuration: a dedicated PostgreSQL database, the mock LLM with fault injection,
and helpers to log in and poll workflow runs (the same way the React app does)."""
from __future__ import annotations

import os
import time

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/maap_test")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["DEMO_MODE"] = "true"
os.environ["SEED_ON_STARTUP"] = "true"
os.environ["MOCK_LLM_LATENCY_MS"] = "30"
os.environ["EXECUTOR_WORKERS"] = "4"
os.environ["LLM_TIMEOUT_SECONDS"] = "5"
os.environ["STATIC_DIR"] = "/nonexistent"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.repositories.database import drop_schema  # noqa: E402

PASSWORDS = {
    "admin": ("admin@company.local", "Admin@123"),
    "manager": ("manager@company.local", "Manager@123"),
    "employee": ("employee@company.local", "Employee@123"),
    "employee2": ("employee2@company.local", "Employee@123"),
}
WF_CHAT, WF_LEAVE, WF_MARKETING = 1, 2, 3


@pytest.fixture(scope="session")
def client():
    drop_schema()
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for role, (email, password) in PASSWORDS.items():
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        out[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


@pytest.fixture(autouse=True)
def reset_llm(client, tokens):
    """Every test starts with no injected fault and a fast mock provider."""
    client.put("/api/demo/llm-fault", json={"mode": "none", "count": 0}, headers=tokens["admin"])
    client.put("/api/demo/mock-latency", json={"latency_ms": 30}, headers=tokens["admin"])
    yield
    client.put("/api/demo/llm-fault", json={"mode": "none", "count": 0}, headers=tokens["admin"])


def start_run(client, headers, workflow_id, payload=None):
    r = client.post(f"/api/workflows/{workflow_id}/run", json={"input": payload or {"request": "Ra mắt ứng dụng quản lý công việc"}}, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def wait_run(client, headers, run_id, predicate=None, timeout=15.0):
    """Poll GET /api/workflow-runs/{id} until the predicate holds (default: final status)."""
    predicate = predicate or (lambda d: d["status"] in ("completed", "failed"))
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data = client.get(f"/api/workflow-runs/{run_id}", headers=headers).json()
        if predicate(data):
            return data
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not reach the expected state: {data}")
