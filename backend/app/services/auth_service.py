"""Auth & RBAC (QA-2): login, JWT issuance and token resolution."""
from __future__ import annotations

import jwt
from sqlalchemy.orm import Session

from app.core.errors import Unauthorized
from app.core.security import create_access_token, decode_access_token, verify_password
from app.repositories.repos import UserRepository
from app.services.activity_log_service import ActivityLogService
from app.services.common import Actor


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.audit = ActivityLogService(db)

    def login(self, email: str, password: str) -> dict:
        user = self.users.get_by_email(email.strip())
        if user is None or not verify_password(password, user.password_hash):
            raise Unauthorized("Email hoặc mật khẩu không đúng", code="invalid_credentials")
        if not user.is_active:
            raise Unauthorized("Tài khoản đã bị vô hiệu hoá", code="inactive_user")
        token, expires_in = create_access_token(user.id, user.role)
        self.audit.record(user.id, "auth.login", "user", user.id, f"{user.email} đăng nhập")
        self.db.commit()
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": user,
        }

    def resolve_token(self, token: str | None) -> Actor:
        if not token:
            raise Unauthorized("Thiếu access token", code="missing_token")
        try:
            payload = decode_access_token(token)
            user_id = int(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError):
            raise Unauthorized("Token không hợp lệ hoặc đã hết hạn", code="invalid_token") from None
        user = self.users.get(user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Tài khoản không còn hoạt động", code="inactive_user")
        # The role is read from the database, so a role change applies immediately.
        return Actor(id=user.id, email=user.email, full_name=user.full_name, role=user.role)
