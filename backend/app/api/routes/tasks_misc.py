"""UC-06 Tasks, UC-09 Activity logs, notifications, knowledge base (RAG), chat, demo."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import (
    activity_log_service,
    chat_service,
    demo_service,
    get_actor,
    knowledge_service,
    notification_service,
    task_service,
)
from app.schemas.dto import (
    ChatAskIn,
    FaultIn,
    KnowledgeDocumentOut,
    LatencyIn,
    NotificationList,
    RunAcceptedOut,
    TaskCreateIn,
    TaskUpdateIn,
)
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles
from app.services.knowledge.knowledge_service import KnowledgeService
from app.services.misc_services import ChatService, DemoService, NotificationService
from app.services.task_service import TaskService

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ tasks
@router.get("/tasks", tags=["tasks"])
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    status: str | None = None,
    mine: bool = False,
    workflow_run_id: int | None = None,
    actor: Actor = Depends(get_actor),
    svc: TaskService = Depends(task_service),
):
    return svc.list(actor, page, page_size, status, mine, workflow_run_id)


@router.post("/tasks", status_code=201, tags=["tasks"])
def create_task(body: TaskCreateIn, actor: Actor = Depends(get_actor), svc: TaskService = Depends(task_service)):
    return svc.create_manual(actor, body.model_dump())


@router.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: int, actor: Actor = Depends(get_actor), svc: TaskService = Depends(task_service)):
    return svc.get(actor, task_id)


@router.put("/tasks/{task_id}", tags=["tasks"])
def update_task(
    task_id: int, body: TaskUpdateIn, actor: Actor = Depends(get_actor), svc: TaskService = Depends(task_service)
):
    return svc.update(actor, task_id, body.model_dump(exclude_unset=True))


# ------------------------------------------------------------------ audit
@router.get("/activity-logs", tags=["audit"])
def activity_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=50),
    entity_type: str | None = None,
    entity_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    actor: Actor = Depends(get_actor),
    svc: ActivityLogService = Depends(activity_log_service),
):
    require_roles(actor, "admin")  # UC-09 is an Admin use case
    return svc.list(page, page_size, entity_type, entity_id, user_id, action, date_from, date_to)


# ------------------------------------------------------------------ notifications
@router.get("/notifications", response_model=NotificationList, tags=["notifications"])
def notifications(actor: Actor = Depends(get_actor), svc: NotificationService = Depends(notification_service)):
    return svc.list(actor)


@router.post("/notifications/{notification_id}/read", tags=["notifications"])
def read_notification(
    notification_id: int, actor: Actor = Depends(get_actor), svc: NotificationService = Depends(notification_service)
):
    return svc.mark_read(actor, notification_id)


@router.post("/notifications/read-all", tags=["notifications"])
def read_all(actor: Actor = Depends(get_actor), svc: NotificationService = Depends(notification_service)):
    return svc.mark_read(actor, None)


# ------------------------------------------------------------------ knowledge base (RAG)
@router.get("/knowledge/collections", tags=["knowledge"])
def collections(actor: Actor = Depends(get_actor), svc: KnowledgeService = Depends(knowledge_service)):
    return svc.collections()


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentOut], tags=["knowledge"])
def documents(
    collection: str | None = None, actor: Actor = Depends(get_actor),
    svc: KnowledgeService = Depends(knowledge_service),
):
    return svc.list_documents(collection)


@router.get("/knowledge/documents/{doc_id}", tags=["knowledge"])
def document_detail(doc_id: int, actor: Actor = Depends(get_actor), svc: KnowledgeService = Depends(knowledge_service)):
    detail = svc.document_detail(doc_id)
    return {"document": KnowledgeDocumentOut.model_validate(detail["document"]), "chunks": detail["chunks"]}


@router.post("/knowledge/documents", status_code=201, response_model=KnowledgeDocumentOut, tags=["knowledge"])
async def upload_document(
    file: UploadFile = File(...),
    collection: str = Form(...),
    title: str | None = Form(None),
    actor: Actor = Depends(get_actor),
    svc: KnowledgeService = Depends(knowledge_service),
):
    data = await file.read()
    return svc.upload(actor, collection, title, file.filename or "document.txt", data, file.content_type)


@router.delete("/knowledge/documents/{doc_id}", tags=["knowledge"])
def delete_document(doc_id: int, actor: Actor = Depends(get_actor), svc: KnowledgeService = Depends(knowledge_service)):
    svc.delete(actor, doc_id)
    return {"deleted": True}


@router.get("/knowledge/search", tags=["knowledge"])
def search_knowledge(
    collection: str, q: str = Query(min_length=1, max_length=500), top_k: int = Query(4, ge=1, le=10),
    actor: Actor = Depends(get_actor), svc: KnowledgeService = Depends(knowledge_service),
):
    hits = svc.retrieve(collection, q, top_k)
    return [
        {"document": h.chunk.document_title, "heading": h.chunk.heading, "chunk_index": h.chunk.chunk_index,
         "score": h.score, "content": h.chunk.content}
        for h in hits
    ]


# ------------------------------------------------------------------ chat
@router.post("/chat/ask", status_code=status.HTTP_202_ACCEPTED, response_model=RunAcceptedOut, tags=["chat"])
def chat_ask(body: ChatAskIn, actor: Actor = Depends(get_actor), svc: ChatService = Depends(chat_service)):
    run = svc.ask(actor, body.workflow_id, body.question)
    return RunAcceptedOut(run_id=run.id, status=run.status, status_url=f"/api/workflow-runs/{run.id}")


@router.get("/chat/history", tags=["chat"])
def chat_history(
    workflow_id: int, limit: int = Query(20, ge=1, le=50), actor: Actor = Depends(get_actor),
    svc: ChatService = Depends(chat_service),
):
    return svc.history(actor, workflow_id, limit)


# ------------------------------------------------------------------ demo control (Admin)
@router.get("/demo/info", tags=["demo"])
def demo_info(actor: Actor = Depends(get_actor), svc: DemoService = Depends(demo_service)):
    return svc.info()


@router.put("/demo/llm-fault", tags=["demo"])
def demo_fault(body: FaultIn, actor: Actor = Depends(get_actor), svc: DemoService = Depends(demo_service)):
    return svc.set_fault(actor, body.mode, body.count, body.kind, body.skip)


@router.put("/demo/mock-latency", tags=["demo"])
def demo_latency(body: LatencyIn, actor: Actor = Depends(get_actor), svc: DemoService = Depends(demo_service)):
    return svc.set_mock_latency(actor, body.latency_ms)
