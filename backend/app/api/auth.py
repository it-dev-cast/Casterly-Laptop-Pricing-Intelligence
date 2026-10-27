from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User
from ..security import PERMISSIONS, ROLES, create_token, current_user, hash_password, require, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
            "permissions": sorted(p for p, roles in PERMISSIONS.items() if u.role in roles)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if u is None or not u.is_active or not verify_password(body.password, u.password_hash):
        audit.record(db, None, "auth.login_failed", "user", None, email=body.email.strip().lower()[:200])
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    audit.record(db, u, "auth.login", "user", u.id)
    db.commit()
    return {"access_token": create_token(u), "token_type": "bearer", "user": user_out(u)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    name: str = Field(min_length=1, max_length=200)
    role: str
    password: str = Field(min_length=10, max_length=128)


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require("manage_users"))):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), actor: User = Depends(require("manage_users"))):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=email, name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit.record(db, actor, "user.created", "user", u.id, email=email, role=body.role)
    db.commit()
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
                actor: User = Depends(require("manage_users"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    changes = {}
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of {ROLES}")
        if u.id == actor.id and body.role != "admin":
            raise HTTPException(422, "You cannot remove your own administrator role")
        u.role = changes["role"] = body.role
    if body.name is not None:
        u.name = changes["name"] = body.name
    if body.is_active is not None:
        if u.id == actor.id and not body.is_active:
            raise HTTPException(422, "You cannot deactivate yourself")
        u.is_active = changes["is_active"] = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
        changes["password"] = "changed"
    audit.record(db, actor, "user.updated", "user", u.id, **changes)
    db.commit()
    return user_out(u)
