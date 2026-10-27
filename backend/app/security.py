"""Authentication (JWT bearer) and role-based access control."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

ROLES = ("admin", "procurement", "sales")

# permission -> roles allowed
PERMISSIONS: dict[str, set[str]] = {
    "view": {"admin", "procurement", "sales"},
    "export": {"admin", "procurement", "sales"},
    "import_inventory": {"admin", "procurement"},
    "import_evidence": {"admin", "procurement"},
    "edit_inventory": {"admin", "procurement"},
    "add_listing": {"admin", "procurement", "sales"},
    "edit_evidence": {"admin", "procurement"},
    "record_purchase": {"admin", "procurement"},
    "record_sale": {"admin", "sales"},
    "run_valuation": {"admin", "procurement", "sales"},
    "use_ai": {"admin", "procurement", "sales"},
    "edit_settings": {"admin"},
    "manage_connectors": {"admin"},
    "manage_users": {"admin"},
    "manage_demo": {"admin"},
    "view_audit": {"admin"},
    "run_backtest": {"admin", "procurement"},
    # Pricing Intelligence (procurement valuation of used IT assets)
    "pi_view": {"admin", "procurement", "sales"},
    "pi_import": {"admin", "procurement"},
    "pi_research": {"admin", "procurement"},
    "pi_price": {"admin", "procurement"},
    "pi_verify_evidence": {"admin", "procurement"},
    "pi_override": {"admin", "procurement"},
    "pi_approve": {"admin", "procurement"},
    "pi_quote": {"admin", "procurement"},
    "pi_outcomes": {"admin", "procurement", "sales"},
    "pi_sources": {"admin"},
    "pi_rules": {"admin"},
}

_bearer = HTTPBearer(auto_error=False)
ALGO = "HS256"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.token_ttl_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.secret_key, algorithm=ALGO)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, get_settings().secret_key, algorithms=[ALGO])
        uid = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    return user


def can(user: User, permission: str) -> bool:
    return user.role in PERMISSIONS[permission]


def require(permission: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not can(user, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{user.role}' lacks permission '{permission}'")
        return user
    return dep
