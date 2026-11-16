"""UC-01 Authenticate, UC-10 Profile, UC-02 Manage users & roles."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import auth_service, get_actor, user_service
from app.schemas.dto import (
    LoginIn,
    ProfileUpdateIn,
    TokenOut,
    UserCreateIn,
    UserOut,
    UserPage,
    UserUpdateIn,
)
from app.services.auth_service import AuthService
from app.services.common import Actor
from app.services.user_service import UserService

public = APIRouter(prefix="/api", tags=["auth"])
router = APIRouter(prefix="/api", tags=["users"])


@public.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, svc: AuthService = Depends(auth_service)):
    return svc.login(body.email, body.password)


@router.get("/me", response_model=UserOut)
def me(actor: Actor = Depends(get_actor), svc: UserService = Depends(user_service)):
    return svc.get_profile(actor)


@router.put("/me", response_model=UserOut)
def update_me(body: ProfileUpdateIn, actor: Actor = Depends(get_actor), svc: UserService = Depends(user_service)):
    return svc.update_profile(actor, body.full_name, body.current_password, body.new_password)


@router.get("/users", response_model=UserPage)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50),
    role: str | None = None,
    actor: Actor = Depends(get_actor),
    svc: UserService = Depends(user_service),
):
    return svc.list_users(actor, page, page_size, role)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, actor: Actor = Depends(get_actor), svc: UserService = Depends(user_service)):
    return svc.create_user(actor, body.email, body.full_name, body.role, body.password)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdateIn, actor: Actor = Depends(get_actor), svc: UserService = Depends(user_service)
):
    return svc.update_user(actor, user_id, body.role, body.is_active, body.full_name)
