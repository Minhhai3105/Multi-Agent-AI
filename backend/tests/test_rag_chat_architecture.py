"""RAG knowledge base, Chat screen backend and architecture conformance (R1-R6)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

from app.services.knowledge.text_processing import BM25Index, IndexedChunk, chunk_text, tokenize
from tests.conftest import WF_CHAT, WF_MARKETING, wait_run

POLICY = Path(__file__).resolve().parent.parent / "sample_data" / "noi_quy_cong_ty.md"


def policy_index() -> BM25Index:
    chunks = chunk_text(POLICY.read_text(encoding="utf-8"), 900, 150)
    return BM25Index([IndexedChunk(i, "Nội quy", c.index, c.heading, c.content) for i, c in enumerate(chunks)])


def test_chunker_keeps_article_headings():
    chunks = chunk_text(POLICY.read_text(encoding="utf-8"), 900, 150)
    headings = {c.heading for c in chunks}
    assert "Điều 6. Nghỉ phép năm" in headings and "Điều 10. Làm thêm giờ" in headings
    assert all(len(c.content) <= 1100 for c in chunks)


def test_bm25_finds_the_right_article_with_and_without_accents():
    index = policy_index()
    assert index.search("Nhân viên được nghỉ phép năm bao nhiêu ngày?")[0].chunk.heading == "Điều 6. Nghỉ phép năm"
    assert index.search("nghi phep nam bao nhieu ngay")[0].chunk.heading == "Điều 6. Nghỉ phép năm"
    assert index.search("tiền làm thêm giờ ngày lễ")[0].chunk.heading == "Điều 10. Làm thêm giờ"
    assert index.search("mất thiết bị thì báo cho ai")[0].chunk.heading.startswith("Điều 13")
    # Known BM25 limitation (lexical): a synonym such as "laptop" is not matched to "thiết bị".
    # An embedding retriever can replace BM25 behind the same interface (extension point).
    assert "nghi_phep" in tokenize("Nghỉ phép")


def test_chat_answer_cites_knowledge_sources(client, tokens):
    h = tokens["employee"]
    chats = client.get("/api/workflows?chat_only=true", headers=h).json()
    assert [w["id"] for w in chats] == [WF_CHAT]
    r = client.post("/api/chat/ask", json={"workflow_id": WF_CHAT, "question": "Đi công tác được phụ cấp bao nhiêu một ngày?"}, headers=h)
    assert r.status_code == 202
    run = wait_run(client, h, r.json()["run_id"])
    assert run["status"] == "completed"
    sources = run["final_result"]["sources"]
    assert sources and sources[0]["heading"] == "Điều 11. Công tác phí"
    assert "[Nguồn 1]" in run["final_result"]["text"]
    history = client.get(f"/api/chat/history?workflow_id={WF_CHAT}", headers=h).json()
    assert history[-1]["question"].startswith("Đi công tác") and history[-1]["answer"]


def test_chat_rejects_non_chat_workflow(client, tokens):
    r = client.post("/api/chat/ask", json={"workflow_id": WF_MARKETING, "question": "hi"}, headers=tokens["employee"])
    assert r.status_code == 404


def test_upload_and_search_new_document(client, tokens):
    mgr = tokens["manager"]
    content = "# Quy định gửi xe\n\n## Điều 1. Bãi xe\nNhân viên được gửi xe máy miễn phí tại tầng hầm B2. Ô tô gửi tại tầng B3 với phí 1.000.000 đồng mỗi tháng."
    r = client.post("/api/knowledge/documents", data={"collection": "hanh-chinh", "title": "Quy định gửi xe"},
                    files={"file": ("gui-xe.md", io.BytesIO(content.encode()), "text/markdown")}, headers=mgr)
    assert r.status_code == 201, r.text
    assert r.json()["chunk_count"] >= 1
    hits = client.get("/api/knowledge/search?collection=hanh-chinh&q=gửi ô tô bao nhiêu tiền", headers=mgr).json()
    assert hits and "1.000.000" in hits[0]["content"]
    # role and format checks
    assert client.post("/api/knowledge/documents", data={"collection": "hanh-chinh"},
                       files={"file": ("a.txt", io.BytesIO(b"noi dung du dai de kiem tra quyen"), "text/plain")},
                       headers=tokens["employee"]).status_code == 403
    bad = client.post("/api/knowledge/documents", data={"collection": "hanh-chinh"},
                      files={"file": ("a.exe", io.BytesIO(b"MZ binary content here"), "application/octet-stream")}, headers=mgr)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unsupported_document"
    names = [c["name"] for c in client.get("/api/knowledge/collections", headers=mgr).json()]
    assert "noi-quy" in names and "hanh-chinh" in names


def test_architecture_rules_hold_in_code():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import check_architecture

    modules = check_architecture.collect()
    assert check_architecture.check(modules) == []


def test_architecture_checker_detects_violations():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import check_architecture

    fake = {
        "app.api.routes.bad": {"path": Path("app/api/routes/bad.py"), "env_reads": [3], "run_status_updates": [],
                               "imports": [("sqlalchemy", ["select"], 1), ("app.repositories.repos", ["RunRepository"], 2)]},
        "app.services.agent_service": {"path": Path("app/services/agent_service.py"), "env_reads": [], "run_status_updates": [9],
                                       "imports": [("httpx", [], 1), ("app.integrations.llm_client", ["LLMClient"], 2)]},
    }
    rules = {v.split("]")[0].strip("[") for v in check_architecture.check(fake)}
    assert {"R2", "R3", "R4", "R5", "R6"} <= rules
