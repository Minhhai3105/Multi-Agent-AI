from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import Forbidden


@dataclass(frozen=True)
class Actor:
    """The authenticated caller, resolved by Auth & RBAC before any business logic."""

    id: int
    email: str
    full_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_manager_or_admin(self) -> bool:
        return self.role in ("admin", "manager")


def require_roles(actor: Actor, *roles: str) -> None:
    if actor.role not in roles:
        raise Forbidden(
            f"Vai trò '{actor.role}' không có quyền thực hiện thao tác này",
            code="insufficient_role",
        )
