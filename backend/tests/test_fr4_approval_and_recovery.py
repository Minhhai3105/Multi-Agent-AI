"""FR4 user/approval steps (decision D06) and startup recovery (risk R01)."""
from __future__ import annotations

from app.repositories.database import SessionLocal
from app.repositories.repos import RunRepository
from app.services import runtime
from app.services.common import Actor
from app.services.workflow_service import WorkflowService
from tests.conftest import WF_LEAVE, WF_MARKETING, start_run, wait_run

LEAVE = {"nhan_vien": "Nguyễn Nhân Viên", "loai_nghi": "Phép năm", "tu_ngay": "2026-12-01",
         "den_ngay": "2026-12-03", "ly_do": "Về quê", "ngay_gui_don": "2026-11-16"}


def waiting(d):
    return d.get("is_waiting") is True


def manager_task_for(client, tokens, run_id):
    tasks = client.get(f"/api/tasks?workflow_run_id={run_id}", headers=tokens["manager"]).json()["items"]
    assert len(tasks) == 1
    return tasks[0]


def test_approval_step_waits_then_resumes(client, tokens):
    emp, mgr = tokens["employee"], tokens["manager"]
    run_id = start_run(client, emp, WF_LEAVE, LEAVE)
    run = wait_run(client, emp, run_id, waiting)
    assert run["status"] == "running"
    assert [s["status"] for s in run["steps"]] == ["done", "in_progress", "pending"]

    task = manager_task_for(client, tokens, run_id)
    assert task["task_type"] == "approval" and task["status"] == "todo" and task["priority"] == "high"
    assert task["deadline"] is not None
    assert "Kết quả từ bước trước" in task["description"]
    # the manager got an in-app notification
    notes = client.get("/api/notifications", headers=mgr).json()
    assert any("duyệt" in n["title"] for n in notes["items"])

    # only the assignee (or manager/admin) may act; approval needs a decision
    assert client.put(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=tokens["employee2"]).status_code == 403
    assert client.put(f"/api/tasks/{task['id']}", json={"status": "done"}, headers=mgr).status_code == 400

    r = client.put(f"/api/tasks/{task['id']}",
                   json={"status": "done", "result": {"decision": "approved", "comment": "Đồng ý, bàn giao trước khi nghỉ"}},
                   headers=mgr)
    assert r.status_code == 200
    # a finished task cannot be changed again
    assert client.put(f"/api/tasks/{task['id']}", json={"status": "todo"}, headers=mgr).status_code == 409

    run = wait_run(client, emp, run_id)
    assert run["status"] == "completed"
    approval, final_step = run["steps"][1], run["steps"][2]
    assert approval["output_result"]["decision"] == "approved"
    assert "phê duyệt" in final_step["input_context"]["previous_output"]
    emp_notes = client.get("/api/notifications", headers=emp).json()["items"]
    assert any(n["title"] == "Workflow đã hoàn thành" for n in emp_notes)


def test_rejection_fails_the_run_and_can_be_retried(client, tokens):
    emp, mgr = tokens["employee"], tokens["manager"]
    run_id = start_run(client, emp, WF_LEAVE, LEAVE)
    wait_run(client, emp, run_id, waiting)
    task = manager_task_for(client, tokens, run_id)
    client.put(f"/api/tasks/{task['id']}", json={"status": "done", "result": {"decision": "rejected", "comment": "Trùng lịch dự án"}}, headers=mgr)
    run = wait_run(client, emp, run_id)
    assert run["status"] == "failed"
    assert "Trùng lịch dự án" in run["steps"][1]["error_message"]
    # retrying the approval step creates a NEW task (re-approval)
    r = client.post(f"/api/step-runs/{run['steps'][1]['id']}/retry", headers=emp)
    assert r.status_code == 202
    run = wait_run(client, emp, run_id, waiting)
    tasks = client.get(f"/api/tasks?workflow_run_id={run_id}", headers=mgr).json()["items"]
    assert len(tasks) == 2 and sum(t["status"] == "todo" for t in tasks) == 1


def test_startup_recovery_fails_interrupted_agent_steps_only(client, tokens):
    with SessionLocal() as db:
        svc = WorkflowService(db, coordinator=None)  # create runs without executing them
        manager = Actor(id=2, email="manager@company.local", full_name="M", role="manager")
        interrupted = svc.start_run(manager, WF_MARKETING, {"request": "bị gián đoạn"})
        between = svc.start_run(manager, WF_MARKETING, {"request": "dừng giữa hai bước"})
        waiting_run = svc.start_run(manager, WF_LEAVE, LEAVE)
        runs = RunRepository(db)
        s = runs.step_runs_of(interrupted.id)
        runs.update_step_run(s[0].id, status="in_progress")  # thread died mid-call
        s = runs.step_runs_of(between.id)
        runs.update_step_run(s[0].id, status="done", output_result={"text": "bước 1 xong"})
        s = runs.step_runs_of(waiting_run.id)
        runs.update_step_run(s[0].id, status="done", output_result={"text": "hợp lệ"})
        runs.update_step_run(s[1].id, status="in_progress")  # legitimately waiting for a task
        db.commit()
        ids = interrupted.id, between.id, waiting_run.id

    report = runtime.get_coordinator().recover_interrupted_runs()
    assert report["runs_failed"] >= 2

    h = tokens["manager"]
    a = client.get(f"/api/workflow-runs/{ids[0]}", headers=h).json()
    assert a["status"] == "failed" and a["steps"][0]["error_message"].startswith("interrupted")
    b = client.get(f"/api/workflow-runs/{ids[1]}", headers=h).json()
    assert b["status"] == "failed" and b["steps"][0]["status"] == "done" and b["steps"][1]["status"] == "failed"
    c = client.get(f"/api/workflow-runs/{ids[2]}", headers=h).json()
    assert c["status"] == "running"  # approval wait is NOT treated as interrupted

    # the interrupted step can be retried and the run completes
    assert client.post(f"/api/step-runs/{a['steps'][0]['id']}/retry", headers=h).status_code == 202
    assert wait_run(client, h, ids[0])["status"] == "completed"
    assert client.post(f"/api/step-runs/{b['steps'][1]['id']}/retry", headers=h).status_code == 202
    b = wait_run(client, h, ids[1])
    assert b["status"] == "completed" and b["steps"][0]["output_result"]["text"] == "bước 1 xong"
