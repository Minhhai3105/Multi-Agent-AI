"""Demo seed data: users for the three roles, Agents, workflows and the sample
company-policy knowledge base used by the RAG Agents.

Runs only when the users table is empty (SEED_ON_STARTUP=true) or via
`python -m app.seed`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.security import hash_password
from app.models import Agent, KnowledgeChunk, KnowledgeDocument, User, Workflow, WorkflowStep
from app.repositories.database import SessionLocal, create_schema
from app.repositories.repos import KnowledgeRepository, UserRepository
from app.services.knowledge.text_processing import chunk_text
from app.core.config import get_settings

log = logging.getLogger(__name__)
SAMPLE_POLICY = Path(__file__).resolve().parent.parent / "sample_data" / "noi_quy_cong_ty.md"

DEMO_USERS = [
    ("admin@company.local", "Quản trị hệ thống", "admin", "Admin@123"),
    ("manager@company.local", "Trần Quản Lý", "manager", "Manager@123"),
    ("employee@company.local", "Nguyễn Nhân Viên", "employee", "Employee@123"),
    ("employee2@company.local", "Lê Nhân Viên Hai", "employee", "Employee@123"),
]


def seed_if_empty() -> bool:
    create_schema()
    with SessionLocal() as db:
        if UserRepository(db).count() > 0:
            return False
        settings = get_settings()
        model = "default"  # follow the provider model configured in .env (LLM_MODEL / GEMINI_MODEL)

        users = {}
        for email, name, role, password in DEMO_USERS:
            user = User(email=email, full_name=name, role=role, password_hash=hash_password(password), is_active=True)
            db.add(user)
            users[role] = users.get(role) or user
        db.flush()
        admin, manager = users["admin"], users["manager"]

        # Knowledge base (RAG)
        text = SAMPLE_POLICY.read_text(encoding="utf-8")
        pieces = chunk_text(text, settings.rag_chunk_size, settings.rag_chunk_overlap)
        KnowledgeRepository(db).add_document(
            KnowledgeDocument(
                collection="noi-quy", title="Nội quy lao động Công ty Demo", filename=SAMPLE_POLICY.name,
                content_type="text/markdown", char_count=len(text), chunk_count=len(pieces), uploaded_by=admin.id,
            ),
            [KnowledgeChunk(chunk_index=p.index, heading=p.heading, content=p.content) for p in pieces],
        )

        def agent(name, role, instruction, collection=None, temperature=0.3):
            # FR2.2: the duty shown to users is the first sentence of the instruction.
            duty = instruction.split(". ")[0].rstrip(".") + "."
            a = Agent(name=name, role_name=role, description=duty, instruction=instruction, model_name=model,
                      temperature=temperature, knowledge_collection=collection, created_by=admin.id)
            db.add(a)
            return a

        qa = agent(
            "Trợ lý Nội quy", "Chuyên viên Nhân sự hỏi đáp nội quy",
            "Trả lời câu hỏi của nhân viên về nội quy công ty. Trả lời ngắn gọn, nêu rõ con số/điều kiện "
            "và trích dẫn nguồn. Nếu tài liệu không đề cập, đề nghị nhân viên liên hệ bộ phận Nhân sự.",
            collection="noi-quy", temperature=0.1,
        )
        checker = agent(
            "Kiểm tra đơn nghỉ phép", "Chuyên viên Nhân sự kiểm tra tính hợp lệ",
            "Đối chiếu đơn xin nghỉ với nội quy (thời gian báo trước, số ngày, loại nghỉ). Kết luận "
            "HỢP LỆ / CẦN BỔ SUNG / KHÔNG HỢP LỆ, liệt kê lý do và điều khoản áp dụng.",
            collection="noi-quy", temperature=0.1,
        )
        writer = agent(
            "Soạn thông báo", "Thư ký hành chính",
            "Dựa trên kết quả kiểm tra và quyết định phê duyệt, soạn email thông báo kết quả gửi nhân viên: "
            "lịch sự, có tiêu đề, nêu quyết định, lưu ý bàn giao công việc nếu được duyệt.",
            temperature=0.4,
        )
        researcher = agent(
            "Nghiên cứu thị trường", "Chuyên viên nghiên cứu",
            "Phân tích chủ đề được giao: khách hàng mục tiêu, nhu cầu, 3 thông điệp chính. Trình bày gạch đầu dòng.",
            temperature=0.5,
        )
        copywriter = agent(
            "Viết nội dung", "Copywriter",
            "Từ kết quả nghiên cứu, viết một bài đăng mạng xã hội khoảng 150 chữ, có lời kêu gọi hành động.",
            temperature=0.7,
        )
        reviewer = agent(
            "Biên tập & kiểm duyệt", "Biên tập viên",
            "Rà soát bài viết: chính tả, giọng văn, tính chính xác. Trả về bản cuối cùng kèm 2-3 nhận xét đã sửa.",
            temperature=0.2,
        )
        db.flush()

        def workflow(name, description, steps, is_chat=False):
            w = Workflow(name=name, description=description, status="active", is_chat=is_chat, created_by=manager.id)
            w.steps = [WorkflowStep(step_order=i + 1, **s) for i, s in enumerate(steps)]
            db.add(w)
            return w

        workflow(
            "Hỏi đáp Nội quy công ty",
            "Trợ lý trả lời câu hỏi về nội quy dựa trên tài liệu nội bộ (RAG).",
            [{"step_type": "agent", "name": "Trả lời câu hỏi", "agent_id": qa.id}],
            is_chat=True,
        )
        workflow(
            "Xử lý đơn xin nghỉ phép",
            "Agent kiểm tra đơn theo nội quy → Manager phê duyệt → Agent soạn thông báo.",
            [
                {"step_type": "agent", "name": "Kiểm tra theo nội quy", "agent_id": checker.id},
                {"step_type": "approval", "name": "Quản lý phê duyệt", "assignee_role": "manager",
                 "config_json": {"instructions": "Xem kết quả kiểm tra của Agent và quyết định duyệt/từ chối.",
                                 "deadline_hours": 24, "priority": "high"}},
                {"step_type": "agent", "name": "Soạn email thông báo", "agent_id": writer.id},
            ],
        )
        workflow(
            "Soạn nội dung marketing",
            "Ba Agent nối tiếp: nghiên cứu → viết → biên tập (minh hoạ truyền ngữ cảnh giữa các Agent).",
            [
                {"step_type": "agent", "name": "Nghiên cứu", "agent_id": researcher.id},
                {"step_type": "agent", "name": "Viết bài", "agent_id": copywriter.id},
                {"step_type": "agent", "name": "Biên tập", "agent_id": reviewer.id},
            ],
        )
        db.commit()
        log.info("Seeded demo data (%s users, %s policy chunks)", len(DEMO_USERS), len(pieces))
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("seeded" if seed_if_empty() else "database already has users - skipped")
