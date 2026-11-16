"""Activity Log Service (QA-6, decision D09).

`record()` adds the audit row to the SAME database transaction as the business change,
so a management action is either committed together with its audit record or not at all.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ActivityLog
from app.repositories.repos import ActivityLogRepository, UserRepository


class ActivityLogService:
    def __init__(self, db: Session):
        self.repo = ActivityLogRepository(db)
        self.users = UserRepository(db)

    def record(
        self,
        actor_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int | None,
        message: str = "",
        detail: dict | None = None,
    ) -> None:
        self.repo.add(
            ActivityLog(
                user_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                message=message,
                detail_json=detail or {},
            )
        )

    def list(
        self,
        page: int,
        page_size: int,
        entity_type: str | None = None,
        entity_id: int | None = None,
        user_id: int | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        rows, total = self.repo.list(
            page, page_size, entity_type, entity_id, user_id, action, date_from, date_to
        )
        names = self.users.names({r.user_id for r in rows if r.user_id})
        items = [
            {
                "id": r.id,
                "user_id": r.user_id,
                "user_name": names.get(r.user_id, "Hệ thống") if r.user_id else "Hệ thống",
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "message": r.message,
                "detail": r.detail_json,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
