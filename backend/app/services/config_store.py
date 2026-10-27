"""Versioned pricing configuration storage."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import PricingConfigVersion, User
from ..pricing.config import PricingConfig, config_hash, default_config


def active_version(db: Session) -> PricingConfigVersion:
    v = db.scalar(select(PricingConfigVersion).where(PricingConfigVersion.is_active.is_(True)))
    if v is None:
        v = save_config(db, default_config(), None, "Initial defaults (no fees, costs, yields or adjustments configured)")
        db.commit()
    return v


def active_config(db: Session) -> tuple[PricingConfig, PricingConfigVersion]:
    v = active_version(db)
    return PricingConfig.model_validate(v.config), v


def save_config(db: Session, cfg: PricingConfig, user: User | None, note: str | None) -> PricingConfigVersion:
    next_v = (db.scalar(select(func.max(PricingConfigVersion.version))) or 0) + 1
    db.execute(update(PricingConfigVersion).values(is_active=False))
    v = PricingConfigVersion(version=next_v, config=cfg.model_dump(mode="json"), config_hash=config_hash(cfg),
                             note=note, is_active=True, created_by=user.id if user else None)
    db.add(v)
    db.flush()
    return v
