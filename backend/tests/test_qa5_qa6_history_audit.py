"""QA-5 history/dashboard performance on ~10,000 step records and QA-6 auditability."""
from __future__ import annotations

import io
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, insert, select

from app.models import ActivityLog, StepRun, WorkflowRun
from app.repositories.database import SessionLocal
from tests.conftest import WF_LEAVE, WF_MARKETING, start_run, wait_run

MARKER = "qa5-bulk"
N_RUNS = 3400  # x 3 steps = 10,200 step_runs (QA-5 demo scale)


@pytest.fixture(scope="module")
def bulk_history(client):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        runs = [
            {
                "workflow_id": WF_MARKETING if i % 3 else WF_LEAVE,
                "started_by": 2 if i % 4 else 3,
                "status": "completed" if i % 5 else "failed",
                "current_step_order": 3,
                "initial_input": {"request": f"bulk {i}", "bulk_marker": MARKER},
                "error_message": None if i % 5 else "Bước 2 thất bại – rate_limit",
                "started_at": now - timedelta(minutes=i * 7),
                "finished_at": now - timedelta(minutes=i * 7 - 1),
            }
            for i in range(N_RUNS)
        ]
        ids = db.execute(insert(WorkflowRun).returning(WorkflowRun.id), runs).scalars().all()
        steps = [
            {"workflow_run_id": rid, "step_order": o, "step_type": "agent", "status": "done", "retry_count": 0,
             "step_snapshot": {"name": f"Bước {o}"}, "agent_id": 3 + o,
             "output_result": {"text": "kết quả mẫu"}, "started_at": now, "finished_at": now}
            for rid in ids for o in (1, 2, 3)
        ]
        db.execute(insert(StepRun), steps)
        db.commit()
    yield len(steps)
    with SessionLocal() as db:
        bulk_ids = select(WorkflowRun.id).where(WorkflowRun.initial_input["bulk_marker"].as_string() == MARKER)
        db.execute(delete(StepRun).where(StepRun.workflow_run_id.in_(bulk_ids)))
        db.execute(delete(WorkflowRun).where(WorkflowRun.initial_input["bulk_marker"].as_string() == MARKER))
        db.commit()


def timed_get(client, url, headers):
    t0 = time.perf_counter()
    r = client.get(url, headers=headers)
    return r, time.perf_counter() - t0


def test_history_queries_under_2s_on_10k_records(client, tokens, bulk_history):
    assert bulk_history >= 10_000
    h = tokens["manager"]
    for url in (
        "/api/history?page=1&page_size=50",
        "/api/history?page=40&page_size=50",
        f"/api/history?workflow_id={WF_MARKETING}&status=failed&page_size=50",
        "/api/history?date_from=2026-01-01T00:00:00&page_size=50",
        "/api/dashboard/summary",
    ):
        r, elapsed = timed_get(client, url, h)
        assert r.status_code == 200, r.text
        assert elapsed < 2.0, f"{url} took {elapsed:.2f}s"  # QA-5 response measure
    page = client.get("/api/history?page_size=50", headers=h).json()
    assert len(page["items"]) == 50 and page["total"] >= N_RUNS


def test_page_size_is_bounded(client, tokens):
    assert client.get("/api/history?page_size=51", headers=tokens["manager"]).status_code == 422


def test_employee_only_sees_own_history(client, tokens, bulk_history):
    data = client.get("/api/history?page_size=50", headers=tokens["employee"]).json()
    assert data["items"] and all(i["started_by"] == 3 for i in data["items"])
    dash = client.get("/api/dashboard/summary", headers=tokens["employee"]).json()
    assert dash["scope"] == "mine" and dash["agents"] == []


def audit_rows(entity_type: str, entity_id: int) -> list[ActivityLog]:
    with SessionLocal() as db:
        return list(db.scalars(select(ActivityLog).where(
            ActivityLog.entity_type == entity_type, ActivityLog.entity_id == entity_id)).all())


def assert_audited(entity_type, entity_id, action, actor_id):
    rows = [r for r in audit_rows(entity_type, entity_id) if r.action == action]
    assert rows, f"no {action} audit for {entity_type}#{entity_id}"
    row = rows[-1]
    assert row.user_id == actor_id and row.created_at is not None and row.message


def test_management_and_execution_actions_are_audited(client, tokens):
    mgr, admin, emp = tokens["manager"], tokens["admin"], tokens["employee"]
    agent = client.post("/api/agents", json={"name": "Agent kiểm toán", "role_name": "Tester", "instruction": "Kiểm tra"}, headers=mgr).json()
    assert_audited("agent", agent["id"], "agent.create", 2)
    client.put(f"/api/agents/{agent['id']}", json={"temperature": 0.9}, headers=mgr)
    assert_audited("agent", agent["id"], "agent.update", 2)
    wf = client.post("/api/workflows", json={"name": "WF kiểm toán", "steps": [{"step_type": "agent", "name": "A", "agent_id": agent["id"]}]}, headers=mgr).json()
    assert_audited("workflow", wf["id"], "workflow.create", 2)
    client.put(f"/api/workflows/{wf['id']}", json={"description": "mô tả mới"}, headers=mgr)
    assert_audited("workflow", wf["id"], "workflow.update", 2)
    run_id = start_run(client, emp, wf["id"])
    wait_run(client, emp, run_id)
    assert_audited("workflow_run", run_id, "workflow_run.start", 3)
    assert any(r.action == "workflow_run.complete" for r in audit_rows("workflow_run", run_id))
    # deleting an Agent with history deactivates it instead (D10) and is audited
    r = client.delete(f"/api/agents/{agent['id']}", headers=mgr).json()
    assert r == {"deleted": False, "deactivated": True}
    assert_audited("agent", agent["id"], "agent.deactivate", 2)
    user = client.post("/api/users", json={"email": "audit.user@company.local", "full_name": "Audit", "role": "employee", "password": "Password@1"}, headers=admin).json()
    assert_audited("user", user["id"], "user.create", 1)
    doc = client.post("/api/knowledge/documents", data={"collection": "audit-test"},
                      files={"file": ("quy-dinh.txt", io.BytesIO("Quy định thử nghiệm về kiểm toán nội bộ hằng năm.".encode()), "text/plain")},
                      headers=mgr).json()
    assert_audited("knowledge_document", doc["id"], "knowledge.upload", 2)
    task = client.post("/api/tasks", json={"title": "Task kiểm toán", "assigned_user_id": 3}, headers=mgr).json()
    assert_audited("task", task["id"], "task.create", 2)
    client.put(f"/api/tasks/{task['id']}", json={"status": "done", "result": {"text": "xong"}}, headers=emp)
    assert_audited("task", task["id"], "task.complete", 3)


def test_rejected_request_leaves_no_audit_record(client, tokens):
    with SessionLocal() as db:
        before = db.query(ActivityLog).count()
    r = client.post("/api/workflows", json={"name": "x", "steps": [{"step_type": "agent", "name": "a", "agent_id": 999}]}, headers=tokens["manager"])
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.query(ActivityLog).count() == before


def test_admin_can_query_activity_logs(client, tokens):
    data = client.get("/api/activity-logs?entity_type=workflow_run&page_size=20", headers=tokens["admin"]).json()
    assert data["total"] > 0
    item = data["items"][0]
    assert {"user_name", "action", "entity_type", "entity_id", "created_at"} <= item.keys()
