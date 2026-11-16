"""User Service: profile (UC-10) and Admin user/role management (UC-02)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import hash_password, verify_password
from app.models import User
from app.models.entities import ROLES
from app.repositories.repos import UserRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor, require_roles


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.audit = ActivityLogService(db)

    def get_profile(self, actor: Actor) -> User:
        user = self.users.get(actor.id)
        if user is None:
            raise NotFound("Không tìm thấy người dùng")
        return user

    def update_profile(
        self,
        actor: Actor,
        full_name: str | None,
        current_password: str | None,
        new_password: str | None,
    ) -> User:
        user = self.get_profile(actor)
        changed = []
        if full_name is not None and full_name.strip() and full_name.strip() != user.full_name:
            user.full_name = full_name.strip()
            changed.append("full_name")
        if new_password:
            if not current_password or not verify_password(current_password, user.password_hash):
                raise ValidationFailed("Mật khẩu hiện tại không đúng", code="wrong_password")
            if len(new_password) < 8:
                raise ValidationFailed("Mật khẩu mới phải có ít nhất 8 ký tự")
            user.password_hash = hash_password(new_password)
            changed.append("password")
        if changed:
            self.audit.record(
                actor.id, "user.update_profile", "user", user.id,
                "Cập nhật hồ sơ cá nhân", {"fields": changed},
            )
            self.db.commit()
        return user

    def list_users(self, actor: Actor, page: int, page_size: int, role: str | None) -> dict:
        require_roles(actor, "admin", "manager")
        rows, total = self.users.list(page, page_size, role)
        return {"items": rows, "total": total, "page": page, "page_size": page_size}

    def create_user(self, actor: Actor, email: str, full_name: str, role: str, password: str) -> User:
        require_roles(actor, "admin")
        if role not in ROLES:
            raise ValidationFailed(f"Vai trò không hợp lệ: {role}")
        if len(password) < 8:
            raise ValidationFailed("Mật khẩu phải có ít nhất 8 ký tự")
        if self.users.get_by_email(email):
            raise Conflict("Email đã tồn tại", code="email_exists")
        user = self.users.add(
            User(
                email=email.strip().lower(),
                full_name=full_name.strip(),
                role=role,
                password_hash=hash_password(password),
                is_active=True,
            )
        )
        self.audit.record(
            actor.id, "user.create", "user", user.id, f"Tạo người dùng {user.email}", {"role": role}
        )
        self.db.commit()
        return user

    def update_user(
        self, actor: Actor, user_id: int, role: str | None, is_active: bool | None, full_name: str | None
    ) -> User:
        require_roles(actor, "admin")
        user = self.users.get(user_id)
        if user is None:
            raise NotFound("Không tìm thấy người dùng")
        changes: dict = {}
        if role is not None and role != user.role:
            if role not in ROLES:
                raise ValidationFailed(f"Vai trò không hợp lệ: {role}")
            if user.id == actor.id:
                raise ValidationFailed("Không thể tự thay đổi vai trò của chính mình")
            changes["role"] = [user.role, role]
            user.role = role
        if is_active is not None and is_active != user.is_active:
            if user.id == actor.id and not is_active:
                raise ValidationFailed("Không thể tự vô hiệu hoá tài khoản của mình")
            changes["is_active"] = [user.is_active, is_active]
            user.is_active = is_active
        if full_name and full_name.strip() != user.full_name:
            changes["full_name"] = [user.full_name, full_name.strip()]
            user.full_name = full_name.strip()
        if changes:
            self.audit.record(actor.id, "user.update", "user", user.id, f"Cập nhật {user.email}", changes)
            self.db.commit()
        return user
