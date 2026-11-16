"""Agent Service (FR2): Agents are configuration rows, not code (C2).

The Agent Service never calls the LLM (rule R4); it only provides configuration
to the Workflow Coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models import Agent
from app.repositories.repos import AgentRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles

_EDITABLE = ("name", "role_name", "instruction", "model_name", "temperature", "knowledge_collection", "is_active")


@dataclass(frozen=True)
class AgentConfig:
    id: int
    name: str
    role_name: str
    instruction: str
    model_name: str
    temperature: float
    knowledge_collection: str | None
    is_active: bool


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AgentRepository(db)
        self.audit = ActivityLogService(db)

    def list(self, actor: Actor) -> list[dict]:
        agents = self.repo.list(include_inactive=actor.is_manager_or_admin)
        stats = self.repo.stats()
        return [self._with_stats(a, stats.get(a.id)) for a in agents]

    def get(self, agent_id: int) -> dict:
        agent = self._require(agent_id)
        return self._with_stats(agent, self.repo.stats().get(agent.id))

    def get_config(self, agent_id: int) -> AgentConfig:
        agent = self._require(agent_id)
        return AgentConfig(
            id=agent.id,
            name=agent.name,
            role_name=agent.role_name,
            instruction=agent.instruction,
            model_name=agent.model_name,
            temperature=agent.temperature,
            knowledge_collection=agent.knowledge_collection,
            is_active=agent.is_active,
        )

    def create(self, actor: Actor, data: dict) -> dict:
        require_roles(actor, "admin", "manager")
        self._validate(data)
        agent = self.repo.add(
            Agent(
                name=data["name"].strip(),
                role_name=data["role_name"].strip(),
                instruction=data["instruction"].strip(),
                model_name=data.get("model_name") or "default",
                temperature=data.get("temperature", 0.3),
                knowledge_collection=(data.get("knowledge_collection") or None),
                is_active=data.get("is_active", True),
                created_by=actor.id,
            )
        )
        self.audit.record(actor.id, "agent.create", "agent", agent.id, f"Tạo Agent '{agent.name}'")
        self.db.commit()
        return self._with_stats(agent, None)

    def update(self, actor: Actor, agent_id: int, data: dict) -> dict:
        require_roles(actor, "admin", "manager")
        agent = self._require(agent_id)
        self._validate({**{k: getattr(agent, k) for k in _EDITABLE}, **data})
        changes = {}
        for key in _EDITABLE:
            if key in data and data[key] != getattr(agent, key):
                value = data[key]
                if key == "knowledge_collection":
                    value = value or None
                changes[key] = [str(getattr(agent, key))[:80], str(value)[:80]]
                setattr(agent, key, value)
        if changes:
            action = "agent.deactivate" if changes.get("is_active", [None, None])[1] == "False" else "agent.update"
            self.audit.record(actor.id, action, "agent", agent.id, f"Cập nhật Agent '{agent.name}'", changes)
            self.db.commit()
        return self.get(agent.id)

    def delete(self, actor: Actor, agent_id: int) -> dict:
        """UC-03: delete an Agent without history, otherwise deactivate it (D10)."""
        require_roles(actor, "admin", "manager")
        agent = self._require(agent_id)
        if self.repo.has_history(agent.id):
            agent.is_active = False
            self.audit.record(
                actor.id, "agent.deactivate", "agent", agent.id,
                f"Agent '{agent.name}' đã có lịch sử nên được vô hiệu hoá thay vì xoá",
            )
            self.db.commit()
            return {"deleted": False, "deactivated": True}
        self.audit.record(actor.id, "agent.delete", "agent", agent.id, f"Xoá Agent '{agent.name}'")
        self.repo.delete(agent)
        self.db.commit()
        return {"deleted": True, "deactivated": False}

    # ---------------------------------------------------------------- helpers
    def _require(self, agent_id: int) -> Agent:
        agent = self.repo.get(agent_id)
        if agent is None:
            raise NotFound("Không tìm thấy Agent")
        return agent

    @staticmethod
    def _validate(data: dict) -> None:
        for field in ("name", "role_name", "instruction"):
            if not str(data.get(field) or "").strip():
                raise ValidationFailed(f"Trường '{field}' không được để trống")
        temperature = data.get("temperature", 0.3)
        if temperature is None or not 0 <= float(temperature) <= 2:
            raise ValidationFailed("temperature phải nằm trong khoảng 0 - 2")

    @staticmethod
    def _with_stats(agent: Agent, stats: dict | None) -> dict:
        stats = stats or {}
        return {
            "id": agent.id,
            "name": agent.name,
            "role_name": agent.role_name,
            "instruction": agent.instruction,
            "model_name": agent.model_name,
            "temperature": agent.temperature,
            "knowledge_collection": agent.knowledge_collection,
            "is_active": agent.is_active,
            "created_at": agent.created_at,
            "updated_at": agent.updated_at,
            "total_runs": stats.get("total_runs", 0),
            "done_runs": stats.get("done", 0),
            "failed_runs": stats.get("failed", 0),
            "last_status": stats.get("last_status"),
            "last_run_at": stats.get("last_run_at"),
        }
