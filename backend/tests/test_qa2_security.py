"""QA-2 Security: 100% of business APIs require authentication; insufficient role -> 403;
passwords stored as hashes; no secrets in the source code."""
from __future__ import annotations

import re
import time
from pathlib import Path

import jwt
import pytest

from app.core.config import get_settings
from app.models import User
from app.repositories.database import SessionLocal

PUBLIC = {("POST", "/api/auth/login"), ("GET", "/api/health")}


def business_routes(app):
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            if (method, path) not in PUBLIC:
                yield method, re.sub(r"\{[^}]+\}", "1", path)


def test_every_business_endpoint_requires_a_token(client):
    routes = list(business_routes(client.app))
    assert len(routes) >= 30
    for method, path in routes:
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        assert r.json()["error"]["code"] in ("missing_token", "invalid_token")


def test_invalid_and_expired_tokens_are_rejected(client):
    assert client.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    settings = get_settings()
    expired = jwt.encode({"sub": "1", "role": "admin", "exp": int(time.time()) - 10}, settings.jwt_secret, algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": "1", "role": "admin", "exp": int(time.time()) + 600}, "wrong-secret-0123456789-0123456789-abcd", algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_wrong_password_returns_401(client):
    r = client.post("/api/auth/login", json={"email": "admin@company.local", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/agents", {"name": "x", "role_name": "x", "instruction": "x"}),
        ("PUT", "/api/workflows/1", {"name": "hack"}),
        ("POST", "/api/workflows", {"name": "x", "steps": []}),
        ("GET", "/api/activity-logs", None),
        ("POST", "/api/users", {"email": "a@b.co", "full_name": "A", "role": "admin", "password": "12345678"}),
        ("PUT", "/api/demo/llm-fault", {"mode": "fail_always"}),
        ("POST", "/api/tasks", {"title": "x"}),
    ],
)
def test_employee_gets_403_outside_role(client, tokens, method, path, body):
    r = client.request(method, path, json=body, headers=tokens["employee"])
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "insufficient_role"


def test_manager_cannot_manage_users(client, tokens):
    r = client.post("/api/users", json={"email": "m@b.co", "full_name": "M", "role": "admin", "password": "12345678"},
                    headers=tokens["manager"])
    assert r.status_code == 403


def test_passwords_are_stored_as_hashes(client):
    with SessionLocal() as db:
        users = db.query(User).all()
    assert users
    for u in users:
        assert u.password_hash.startswith("pbkdf2_sha256$")
        assert "Admin@123" not in u.password_hash and "Employee@123" not in u.password_hash


def test_no_api_keys_in_source_code():
    root = Path(__file__).resolve().parent.parent / "app"
    pattern = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,})")
    offenders = [str(p) for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
