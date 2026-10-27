from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from . import audit
from .api import admin, auth, imports, pricing_intel, records, valuations
from .config import get_settings
from .connectors.adapters import ensure_defaults
from .db import SessionLocal
from .models import User
from .procurement import service as pi_service
from .procurement import worker as pi_worker
from .security import hash_password
from .services.config_store import active_version

log = logging.getLogger("clpi")


def bootstrap() -> None:
    """Idempotent start-up seeding: default config, connector rows, first administrator."""
    s = get_settings()
    with SessionLocal() as db:
        active_version(db)
        ensure_defaults(db)
        pi_service.active_rules(db)
        pi_service.seed_sources(db)
        from .procurement.automatic import import_configured_references
        import_configured_references(db)
        has_user = db.scalar(select(User.id).limit(1))
        if not has_user and s.bootstrap_admin_email and s.bootstrap_admin_password:
            u = User(email=s.bootstrap_admin_email.lower(), name=s.bootstrap_admin_name, role="admin",
                     password_hash=hash_password(s.bootstrap_admin_password))
            db.add(u)
            db.flush()
            audit.record(db, None, "user.bootstrap_admin_created", "user", u.id, email=u.email)
            log.warning("Created bootstrap administrator %s", u.email)
        elif not has_user:
            log.warning("No users exist and CLPI_BOOTSTRAP_ADMIN_EMAIL/PASSWORD are not set: nobody can sign in.")
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    pi_worker.start_in_process()
    yield
    pi_worker.stop_in_process()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Casterly Laptop Pricing Intelligence", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
    for r in (auth.router, imports.router, records.router, valuations.router, admin.router, pricing_intel.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        with SessionLocal() as db:
            db.execute(text("select 1"))
        return {"status": "ok", "ai_configured": s.ai_configured,
                "research_mode": "live_configured_unprobed" if (s.brave_api_key or s.tavily_api_key) else "offline_history",
                "queue_mode": s.research_worker}

    return app


app = create_app()
