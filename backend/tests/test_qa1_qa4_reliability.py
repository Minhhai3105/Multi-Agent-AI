"""QA-1 Reliability and QA-4 Recoverability.

QA-1: an LLM call fails/times out -> exactly one automatic retry; persistent failure is
stored with error_message; completed steps are never lost.
QA-4: only the failed step is re-run from its persisted input_context (UC-07); a second
concurrent retry gets 409 (risk R03).
"""
from __future__ import annotations

import threading

from app.services import runtime
from tests.conftest import WF_MARKETING, start_run, wait_run


def mock_calls() -> int:
    return runtime.get_llm_client().inner.calls


def fault(client, tokens, **body):
    r = client.put("/api/demo/llm-fault", json=body, headers=tokens["admin"])
    assert r.status_code == 200, r.text
    return r.json()


def test_one_transient_failure_is_retried_automatically(client, tokens):
    fault(client, tokens, mode="fail_next", count=1)
    run = wait_run(client, tokens["manager"], start_run(client, tokens["manager"], WF_MARKETING))
    assert run["status"] == "completed"
    first = run["steps"][0]
    assert first["retry_count"] == 1
    attempts = first["output_result"]["attempts"]
    assert attempts[0]["error"] == "provider_error" and attempts[1]["ok"] is True
    assert all(s["retry_count"] == 0 for s in run["steps"][1:])


def test_persistent_failure_keeps_completed_steps(client, tokens):
    # step 1 succeeds (skip=1), step 2 fails on the first call AND on the automatic retry
    fault(client, tokens, mode="fail_always", skip=1, kind="rate_limit")
    run = wait_run(client, tokens["manager"], start_run(client, tokens["manager"], WF_MARKETING))
    assert run["status"] == "failed"
    s1, s2, s3 = run["steps"]
    assert s1["status"] == "done" and s1["output_result"]["text"]
    assert s2["status"] == "failed" and s2["retry_count"] == 1
    assert s2["error_message"].startswith("rate_limit")
    assert len(s2["output_result"]["attempts"]) == 2  # exactly one automatic retry
    assert s3["status"] == "pending"
    assert "Bước 2" in run["error_message"]


def test_timeout_is_normalised_and_retried_once(client, tokens):
    fault(client, tokens, mode="timeout_next", count=2)
    run = wait_run(client, tokens["manager"], start_run(client, tokens["manager"], WF_MARKETING))
    assert run["status"] == "failed"
    step = run["steps"][0]
    assert step["error_message"].startswith("timeout")
    assert step["retry_count"] == 1


def test_manual_retry_reruns_only_the_failed_step(client, tokens):
    h = tokens["manager"]
    fault(client, tokens, mode="fail_always", skip=1)
    run = wait_run(client, h, start_run(client, h, WF_MARKETING))
    s1_before, s2_failed = run["steps"][0], run["steps"][1]
    assert s2_failed["status"] == "failed"

    fault(client, tokens, mode="none", count=0)
    client.put("/api/demo/mock-latency", json={"latency_ms": 500}, headers=tokens["admin"])
    calls_before = mock_calls()
    r = client.post(f"/api/step-runs/{s2_failed['id']}/retry", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "in_progress"
    # R03: a second retry while the first is running -> 409
    second = client.post(f"/api/step-runs/{s2_failed['id']}/retry", headers=h)
    assert second.status_code == 409 and second.json()["error"]["code"] == "step_not_failed"

    run = wait_run(client, h, run["id"])
    assert run["status"] == "completed"
    s1_after, s2_after, s3_after = run["steps"]
    # completed work is not repeated
    assert s1_after["finished_at"] == s1_before["finished_at"]
    assert s1_after["output_result"] == s1_before["output_result"]
    # the failed step re-used its persisted input_context
    assert s2_after["input_context"] == s2_failed["input_context"]
    assert s2_after["status"] == "done" and s3_after["status"] == "done"
    assert mock_calls() - calls_before == 2  # step 2 + step 3 only


def test_concurrent_manual_retries_only_one_wins(client, tokens):
    h = tokens["manager"]
    fault(client, tokens, mode="fail_always")
    run = wait_run(client, h, start_run(client, h, WF_MARKETING))
    step_id = run["steps"][0]["id"]
    fault(client, tokens, mode="none", count=0)
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(client.post(f"/api/step-runs/{step_id}/retry", headers=h).status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [202, 409]
    assert wait_run(client, h, run["id"])["status"] == "completed"


def test_retry_rules(client, tokens):
    h = tokens["manager"]
    run = wait_run(client, h, start_run(client, h, WF_MARKETING))
    done_step = run["steps"][0]["id"]
    assert client.post(f"/api/step-runs/{done_step}/retry", headers=h).status_code == 409
    assert client.post("/api/step-runs/999999/retry", headers=h).status_code == 404
    # an employee cannot retry a run started by somebody else
    fault(client, tokens, mode="fail_always")
    failed = wait_run(client, h, start_run(client, h, WF_MARKETING))
    r = client.post(f"/api/step-runs/{failed['steps'][0]['id']}/retry", headers=tokens["employee"])
    assert r.status_code == 403
