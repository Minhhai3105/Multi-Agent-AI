"""Knowledge Service (RAG extension): ingest documents and retrieve relevant chunks.

Ingestion: parse file -> chunk -> persist knowledge_documents / knowledge_chunks.
Retrieval: BM25 over the chunks of one collection, cached in memory and invalidated
when the collection changes.
"""
from __future__ import annotations

import re
import threading

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.integrations.document_parser import DocumentParseError, extract_text
from app.models import KnowledgeChunk, KnowledgeDocument
from app.repositories.repos import KnowledgeRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles
from app.services.knowledge.text_processing import BM25Index, Hit, IndexedChunk, chunk_text

_COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,60}$")
_index_cache: dict[str, tuple[tuple[int, int], BM25Index]] = {}
_cache_lock = threading.Lock()


class KnowledgeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = KnowledgeRepository(db)
        self.audit = ActivityLogService(db)
        self.settings = get_settings()

    # ---------------------------------------------------------------- ingestion
    def upload(
        self, actor: Actor, collection: str, title: str | None, filename: str, data: bytes,
        content_type: str | None = None,
    ) -> KnowledgeDocument:
        require_roles(actor, "admin", "manager")
        collection = collection.strip().lower()
        if not _COLLECTION_RE.match(collection):
            raise ValidationFailed(
                "Tên bộ tri thức chỉ gồm chữ thường không dấu, số, '-' hoặc '_' (2-60 ký tự)"
            )
        if len(data) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValidationFailed(f"File vượt quá {self.settings.max_upload_mb} MB")
        try:
            text = extract_text(filename, data)
        except DocumentParseError as exc:
            raise ValidationFailed(str(exc), code="unsupported_document") from exc
        if len(text.strip()) < 20:
            raise ValidationFailed("Không trích xuất được nội dung từ file (file rỗng hoặc ảnh scan)")
        pieces = chunk_text(text, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap)
        doc = KnowledgeDocument(
            collection=collection,
            title=(title or filename).strip()[:250],
            filename=filename[:250],
            content_type=content_type or "application/octet-stream",
            char_count=len(text),
            chunk_count=len(pieces),
            uploaded_by=actor.id,
        )
        chunks = [KnowledgeChunk(chunk_index=p.index, heading=p.heading, content=p.content) for p in pieces]
        self.repo.add_document(doc, chunks)
        self.audit.record(
            actor.id, "knowledge.upload", "knowledge_document", doc.id,
            f"Nạp tài liệu '{doc.title}' vào bộ tri thức {collection}",
            {"chunks": len(chunks), "chars": len(text), "filename": filename},
        )
        self.db.commit()
        _invalidate(collection)
        return doc

    def delete(self, actor: Actor, doc_id: int) -> None:
        require_roles(actor, "admin", "manager")
        doc = self.repo.get_document(doc_id)
        if doc is None or not doc.is_active:
            raise NotFound("Không tìm thấy tài liệu")
        doc.is_active = False
        self.audit.record(
            actor.id, "knowledge.delete", "knowledge_document", doc.id, f"Gỡ tài liệu '{doc.title}'"
        )
        self.db.commit()
        _invalidate(doc.collection)

    # ---------------------------------------------------------------- queries
    def list_documents(self, collection: str | None = None) -> list[KnowledgeDocument]:
        return self.repo.list_documents(collection)

    def collections(self) -> list[dict]:
        return [
            {"name": name, "documents": docs, "chunks": chunks}
            for name, docs, chunks in self.repo.collections()
        ]

    def document_detail(self, doc_id: int) -> dict:
        doc = self.repo.get_document(doc_id)
        if doc is None:
            raise NotFound("Không tìm thấy tài liệu")
        chunks = self.repo.chunks_of_document(doc_id)
        return {
            "document": doc,
            "chunks": [
                {"chunk_index": c.chunk_index, "heading": c.heading, "content": c.content} for c in chunks
            ],
        }

    def retrieve(self, collection: str, query: str, top_k: int | None = None) -> list[Hit]:
        index = self._index(collection)
        return index.search(query, top_k or self.settings.rag_top_k)

    def _index(self, collection: str) -> BM25Index:
        version = self.repo.collection_version(collection)
        with _cache_lock:
            cached = _index_cache.get(collection)
            if cached and cached[0] == version:
                return cached[1]
        rows = self.repo.chunks_of_collection(collection)
        index = BM25Index(
            [
                IndexedChunk(
                    chunk_id=c.id, document_title=title, chunk_index=c.chunk_index,
                    heading=c.heading, content=c.content,
                )
                for c, title in rows
            ]
        )
        with _cache_lock:
            _index_cache[collection] = (version, index)
        return index


def _invalidate(collection: str) -> None:
    with _cache_lock:
        _index_cache.pop(collection, None)
