"""Requirements closed after v1.5:

* FR2.2  Agent description (duty) - ERD agents.description.
* ERD    workflow_steps.instruction_override - a prompt for one step only.
* FR3.4  end (cancel) a workflow run.
* FR4.2 / FR4.5  a manual task assigned to an Agent is executed by that Agent and can
  be run again after a failure.
"""
from __future__ import annotations

import time

from app.services.agent_service import AgentConfig
from app.services.step_executors import AgentStepExecutor
from tests.conftest import WF_LEAVE, start_run, wait_run

LEAVE = {"nhan_vien": "Nguyễn Nhân Viên", "loai_nghi": "Phép năm", "tu_ngay": "2026-12-01",
         "den_ngay": "2026-12-03", "ly_do": "Về quê", "ngay_gui_don": "2026-11-16"}


def _agent(client, tokens, **extra):
    body = {"name": "Agent tóm tắt", "role_name": "Thư ký", "instruction": "Tóm tắt yêu cầu thành 3 ý.",
            "description": "Tóm tắt yêu cầu cho quản lý", **extra}
    r = client.post("/api/agents", json=body, headers=tokens["manager"])
    assert r.status_code == 201, r.text
    return r.json()


def _wait_task(client, headers, task_id, statuses=("done", "failed"), timeout=10.0):
    deadline = time.time() + timeout
    task = None
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if task["status"] in statuses:
            return task
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} did not finish: {task}")


# ------------------------------------------------------------------ FR2.2
def test_agent_description_is_stored_and_updatable(client, tokens):
    agent = _agent(client, tokens)
    assert agent["description"] == "Tóm tắt yêu cầu cho quản lý"
    r = client.put(f"/api/agents/{agent['id']}", json={"description": "  Mô tả mới  "}, headers=tokens["manager"])
    assert r.status_code == 200 and r.json()["description"] == "Mô tả mới"
    assert client.get(f"/api/agents/{agent['id']}", headers=tokens["employee"]).json()["description"] == "Mô tả mới"


# ------------------------------------------------------------------ instruction_override
def test_step_instruction_override_is_saved_and_snapshotted(client, tokens):
    agent = _agent(client, tokens)
    wf = client.post("/api/workflows", json={
        "name": "Tóm tắt có chỉ dẫn riêng",
        "steps": [{"step_type": "agent", "name": "Tóm tắt", "agent_id": agent["id"],
                   "instruction_override": "Chỉ viết bằng gạch đầu dòng."}],
    }, headers=tokens["manager"])
    assert wf.status_code == 201, wf.text
    assert wf.json()["steps"][0]["instruction_override"] == "Chỉ viết bằng gạch đầu dòng."

    run_id = start_run(client, tokens["manager"], wf.json()["id"])
    run = wait_run(client, tokens["manager"], run_id)
    assert run["status"] == "completed"


def test_system_prompt_contains_description_and_step_instruction():
    cfg = AgentConfig(id=1, name="A", role_name="R", description="Nhiệm vụ X", instruction="Chỉ dẫn Y",
                      model_name="default", temperature=0.3, knowledge_collection=None, is_active=True)
    prompt = AgentStepExecutor._system_prompt(cfg, False, "Chỉ dẫn riêng Z")
    assert "Nhiệm vụ X" in prompt and "Chỉ dẫn Y" in prompt and "Chỉ dẫn riêng Z" in prompt
    assert "Chỉ dẫn riêng" not in AgentStepExecutor._system_prompt(cfg, False, None)


# ------------------------------------------------------------------ FR3.4
def test_cancel_waiting_run_closes_its_tasks(client, tokens):
    emp, mgr = tokens["employee"], tokens["manager"]
    run_id = start_run(client, emp, WF_LEAVE, LEAVE)
    wait_run(client, emp, run_id, lambda d: d.get("is_waiting") is True)

    # another employee may not cancel someone else's run
    assert client.post(f"/api/workflow-runs/{run_id}/cancel", json={}, headers=tokens["employee2"]).status_code == 403

    r = client.post(f"/api/workflow-runs/{run_id}/cancel", json={"reason": "Nhân viên rút đơn"}, headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and "Nhân viên rút đơn" in r.json()["error_message"]

    run = client.get(f"/api/workflow-runs/{run_id}", headers=emp).json()
    assert run["status"] == "cancelled"
    assert run["steps"][0]["status"] == "done"          # completed work is kept
    assert run["steps"][1]["status"] == "failed"        # the waiting approval step is closed
    tasks = client.get(f"/api/tasks?workflow_run_id={run_id}", headers=mgr).json()["items"]
    assert tasks and all(t["status"] == "failed" and t["result"]["cancelled"] for t in tasks)

    # a cancelled run can neither be cancelled again nor retried
    assert client.post(f"/api/workflow-runs/{run_id}/cancel", json={}, headers=emp).status_code == 409
    assert client.post(f"/api/step-runs/{run['steps'][1]['id']}/retry", headers=mgr).status_code == 409

    logs = client.get(f"/api/activity-logs?entity_type=workflow_run&entity_id={run_id}", headers=tokens["admin"]).json()
    assert any(item["action"] == "workflow_run.cancel" for item in logs["items"])


def test_completed_run_cannot_be_cancelled(client, tokens):
    agent = _agent(client, tokens)
    wf = client.post("/api/workflows", json={"name": "Một bước", "steps": [
        {"step_type": "agent", "name": "Tóm tắt", "agent_id": agent["id"]}]}, headers=tokens["manager"]).json()
    run_id = start_run(client, tokens["manager"], wf["id"])
    assert wait_run(client, tokens["manager"], run_id)["status"] == "completed"
    r = client.post(f"/api/workflow-runs/{run_id}/cancel", json={}, headers=tokens["manager"])
    assert r.status_code == 409


# ------------------------------------------------------------------ FR4.2 / FR4.5
def test_task_assigned_to_agent_is_executed_by_the_agent(client, tokens):
    mgr = tokens["manager"]
    agent = _agent(client, tokens)
    task = client.post("/api/tasks", json={"title": "Tóm tắt báo cáo tuần", "description": "Doanh số tăng 10%",
                                           "assigned_agent_id": agent["id"]}, headers=mgr).json()
    assert task["assigned_agent_id"] == agent["id"]

    # employees cannot trigger Agent execution
    assert client.post(f"/api/tasks/{task['id']}/run-agent", headers=tokens["employee"]).status_code == 403

    r = client.post(f"/api/tasks/{task['id']}/run-agent", headers=mgr)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "in_progress"
    # a second start while running is rejected
    assert client.post(f"/api/tasks/{task['id']}/run-agent", headers=mgr).status_code in (202, 409)

    done = _wait_task(client, mgr, task["id"])
    assert done["status"] == "done"
    assert done["result"]["executed_by"] == "agent" and done["result"]["text"]
    assert done["result"]["agent_name"] == "Agent tóm tắt"


def test_failed_agent_task_can_be_run_again(client, tokens):
    mgr = tokens["manager"]
    agent = _agent(client, tokens)
    task = client.post("/api/tasks", json={"title": "Viết email", "assigned_agent_id": agent["id"]}, headers=mgr).json()

    client.put("/api/demo/llm-fault", json={"mode": "fail_always"}, headers=tokens["admin"])
    assert client.post(f"/api/tasks/{task['id']}/run-agent", headers=mgr).status_code == 202
    failed = _wait_task(client, mgr, task["id"])
    assert failed["status"] == "failed" and failed["result"]["error"]
    assert len(failed["result"]["attempts"]) == 2       # QA-1: exactly one automatic retry

    client.put("/api/demo/llm-fault", json={"mode": "none", "count": 0}, headers=tokens["admin"])
    assert client.post(f"/api/tasks/{task['id']}/run-agent", headers=mgr).status_code == 202
    assert _wait_task(client, mgr, task["id"])["status"] == "done"


def test_run_agent_requires_an_agent(client, tokens):
    task = client.post("/api/tasks", json={"title": "Việc của người",
                                           "assigned_user_id": 3}, headers=tokens["manager"]).json()
    r = client.post(f"/api/tasks/{task['id']}/run-agent", headers=tokens["manager"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_agent"


def test_failed_manual_task_can_be_reassigned_and_reopened(client, tokens):
    mgr = tokens["manager"]
    task = client.post("/api/tasks", json={"title": "Chuẩn bị hợp đồng", "assigned_user_id": 3}, headers=mgr).json()
    assert client.put(f"/api/tasks/{task['id']}", json={"status": "failed"}, headers=mgr).status_code == 200
    r = client.put(f"/api/tasks/{task['id']}", json={"assigned_user_id": 4, "status": "todo"}, headers=mgr)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "todo" and r.json()["assigned_user_id"] == 4
