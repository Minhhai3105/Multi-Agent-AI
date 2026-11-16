"""Measure the QA-3 and QA-5 response measures against a running backend.

    python scripts/qa_benchmark.py                      # measure only
    python scripts/qa_benchmark.py --seed-bulk 3400     # first add 3,400 runs x 3 steps (~10k step_runs)

Environment: BASE_URL (default http://localhost:8000). The bulk seed writes directly to
the database configured by DATABASE_URL (same as the backend).
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _step_status(i: int, order: int) -> str:
    """Failed runs (every 5th) fail at step 2; step 3 never ran."""
    if i % 5:
        return "done"
    return {1: "done", 2: "failed", 3: "pending"}[order]


def seed_bulk(n_runs: int) -> int:
    from sqlalchemy import insert

    from app.models import StepRun, WorkflowRun
    from app.repositories.database import SessionLocal

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        runs = [{
            "workflow_id": 3 if i % 3 else 2, "started_by": 2 if i % 4 else 3,
            "status": "completed" if i % 5 else "failed", "current_step_order": 3,
            "initial_input": {"request": f"Dữ liệu lịch sử mẫu #{i}", "bulk_marker": "benchmark"},
            "error_message": None if i % 5 else "Bước 2 (Viết bài) thất bại – rate_limit: Injected HTTP 429",
            "started_at": now - timedelta(minutes=i * 7), "finished_at": now - timedelta(minutes=i * 7 - 1),
        } for i in range(n_runs)]
        ids = db.execute(insert(WorkflowRun).returning(WorkflowRun.id), runs).scalars().all()
        i_of = {rid: i for i, rid in enumerate(ids)}
        db.execute(insert(StepRun), [{
            "workflow_run_id": rid, "step_order": o, "step_type": "agent", "status": _step_status(i_of[rid], o), "retry_count": 1 if _step_status(i_of[rid], o) == "failed" else 0,
            "step_snapshot": {"name": f"Bước {o}"}, "agent_id": 3 + o, "output_result": {"text": "kết quả mẫu"} if _step_status(i_of[rid], o) == "done" else None,
            "started_at": now, "finished_at": now,
        } for rid in ids for o in (1, 2, 3)])
        db.commit()
    return n_runs * 3


def measure(client: httpx.Client, method: str, url: str, headers: dict, repeat: int = 5, **kw) -> dict:
    times, status = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        r = client.request(method, url, headers=headers, **kw)
        times.append((time.perf_counter() - t0) * 1000)
        status = r.status_code
    return {"url": url, "status": status, "median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1)}


def main() -> None:
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-bulk", type=int, default=0)
    args = parser.parse_args()
    if args.seed_bulk:
        print(f"Inserted {seed_bulk(args.seed_bulk)} step_runs")

    base = os.environ.get("BASE_URL", "http://localhost:8000")
    with httpx.Client(base_url=base, timeout=30) as client:
        token = client.post("/api/auth/login", json={"email": "manager@company.local", "password": "Manager@123"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        results = [
            measure(client, "POST", "/api/workflows/3/run", h, repeat=3, json={"input": {"request": "Benchmark QA-3"}}),
            measure(client, "GET", "/api/agents", h),
            measure(client, "GET", "/api/workflows", h),
            measure(client, "GET", "/api/history?page=1&page_size=50", h),
            measure(client, "GET", "/api/history?page=50&page_size=50", h),
            measure(client, "GET", "/api/history?workflow_id=3&status=failed&page_size=50", h),
            measure(client, "GET", "/api/dashboard/summary", h),
        ]
        total = client.get("/api/history?page_size=1", headers=h).json()["total"]
    print(f"\nworkflow_runs in database: {total}")
    print(f"{'Endpoint':58} {'HTTP':>4} {'median ms':>10} {'max ms':>8}")
    for r in results:
        print(f"{r['url']:58} {r['status']:>4} {r['median_ms']:>10} {r['max_ms']:>8}")
    print("\nTargets: workflow start <= 3000 ms (QA-3), CRUD <= 2000 ms (QA-3), history/dashboard <= 2000 ms (QA-5)")


if __name__ == "__main__":
    main()
