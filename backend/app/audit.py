from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditEvent, User


def record(db: Session, user: User | None, action: str, entity_type: str | None = None,
           entity_id: int | str | None = None, **details) -> None:
    """Append an audit event. Caller commits."""
    db.add(AuditEvent(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=_clean(details) or None,
    ))


def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [_clean(v) for v in d]
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return d
