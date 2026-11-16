"""FR3/FR5 + QA-3: asynchronous start (202 + run_id within 3 s), ordered execution,
context propagation between Agents and aggregated final result."""
from __future__ import annotations

import time

from tests.conftest import WF_MARKETING, start_run, wait_run


def test_start_returns_202_quickly_while_llm_is_slow(client, tokens):
    client.put("/api/demo/mock-latency", json={"latency_ms": 1500}, headers=tokens["admin"])
    t0 = time.perf_counter()
    r = client.post(f"/api/workflows/{WF_MARKETING}/run", json={"input": {"request": "Khoá học AI"}}, headers=tokens["employee"])
    elapsed = time.perf_counter() - t0
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "running" and body["run_id"] > 0
    assert body["status_url"] == f"/api/workflow-runs/{body['run_id']}"
    # QA-3 response measure: <= 3 s excluding LLM time (3 steps x 1.5 s are NOT waited for)
    assert elapsed < 3.0, elapsed
    assert float(r.headers["X-Response-Time-ms"]) < 3000
    first = client.get(f"/api/workflow-runs/{body['run_id']}", headers=tokens["employee"]).json()
    assert first["status"] == "running"
    final = wait_run(client, tokens["employee"], body["run_id"], timeout=20)
    assert final["status"] == "completed"


def test_steps_run_in_order_and_pass_context(client, tokens):
    run_id = start_run(client, tokens["manager"], WF_MARKETING, {"request": "Ứng dụng đặt lịch khám"})
    run = wait_run(client, tokens["manager"], run_id)
    assert run["status"] == "completed"
    steps = run["steps"]
    assert [s["step_order"] for s in steps] == [1, 2, 3]
    assert all(s["status"] == "done" for s in steps)
    # sequential: each step starts after the previous one finished
    for prev, nxt in zip(steps, steps[1:]):
        assert prev["finished_at"] <= nxt["started_at"]
    # context propagation (FR5.2): output of step n is the input of step n+1
    assert steps[0]["input_context"]["previous_output"] is None
    assert steps[1]["input_context"]["previous_output"] == steps[0]["output_result"]["text"]
    assert steps[2]["input_context"]["previous_output"] == steps[1]["output_result"]["text"]
    assert steps[1]["input_context"]["initial_input"] == {"request": "Ứng dụng đặt lịch khám"}
    # aggregated final result (FR5.4)
    final = run["final_result"]
    assert len(final["steps"]) == 3
    assert final["text"] == steps[2]["output_result"]["text"]


def test_crud_is_fast(client, tokens):
    for path in ("/api/agents", "/api/workflows", "/api/tasks", "/api/me"):
        t0 = time.perf_counter()
        r = client.get(path, headers=tokens["manager"])
        assert r.status_code == 200
        assert time.perf_counter() - t0 < 2.0  # QA-3 CRUD target <= 2 s


def test_invalid_start_requests(client, tokens):
    assert client.post("/api/workflows/9999/run", json={"input": {"a": 1}}, headers=tokens["manager"]).status_code == 404
    r = client.post(f"/api/workflows/{WF_MARKETING}/run", json={"input": {}}, headers=tokens["manager"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_input"


def test_workflow_validation_rejects_bad_definitions(client, tokens):
    h = tokens["manager"]
    bad_order = {"name": "x", "steps": [
        {"step_order": 1, "step_type": "agent", "name": "a", "agent_id": 4},
        {"step_order": 3, "step_type": "agent", "name": "b", "agent_id": 5}]}
    r = client.post("/api/workflows", json=bad_order, headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_step_order"
    missing_agent = {"name": "x", "steps": [{"step_type": "agent", "name": "a", "agent_id": 999}]}
    r = client.post("/api/workflows", json=missing_agent, headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_agent"
    no_assignee = {"name": "x", "steps": [{"step_type": "approval", "name": "a"}]}
    assert client.post("/api/workflows", json=no_assignee, headers=h).status_code == 400


def test_edit_during_run_only_affects_new_runs(client, tokens):
    h = tokens["manager"]
    created = client.post("/api/workflows", json={"name": "Hai bước", "steps": [
        {"step_type": "agent", "name": "A", "agent_id": 4},
        {"step_type": "agent", "name": "B", "agent_id": 5}]}, headers=h).json()
    client.put("/api/demo/mock-latency", json={"latency_ms": 400}, headers=tokens["admin"])
    run_id = start_run(client, h, created["id"])
    client.put(f"/api/workflows/{created['id']}", json={"steps": [{"step_type": "agent", "name": "Chỉ một bước", "agent_id": 6}]}, headers=h)
    run = wait_run(client, h, run_id)
    assert run["status"] == "completed"
    assert [s["name"] for s in run["steps"]] == ["A", "B"]  # snapshot taken at start
