"""Authenticated operations diagnostics. Configuration is not reported as a successful provider probe."""
from datetime import timedelta
from sqlalchemy import func, select
from ..config import get_settings
from .models import PIResearchJob, PIWorkerHeartbeat
from . import providers, research

def heartbeat():
    import os, socket
    from ..db import SessionLocal
    worker_id = f'{socket.gethostname()}:{os.getpid()}'[:100]
    with SessionLocal() as db:
        h = db.get(PIWorkerHeartbeat, worker_id)
        if h is None:
            h = PIWorkerHeartbeat(worker_id=worker_id)
            db.add(h)
        h.updated_at = research.now()
        db.commit()

def report(db):
    latest = db.scalar(select(func.max(PIWorkerHeartbeat.updated_at)))
    fresh = latest is not None and research._aware(latest) > research.now()-timedelta(minutes=5)
    return {'providers':[{**p,'connectivity_verified':None} for p in providers.status()],
            'research_mode':'live_configured_unprobed' if providers.default_provider() else 'offline_history',
            'queue':{'worker_mode':get_settings().research_worker,'worker_healthy':fresh,
                     'last_heartbeat':latest.isoformat() if latest else None,
                     'queued_jobs':db.scalar(select(func.count()).select_from(PIResearchJob).where(PIResearchJob.status=='queued')) or 0},
            'references':{'directories_configured':len(get_settings().reference_dirs)},
            'catalog_configured':bool(get_settings().approved_catalog_path and get_settings().approved_catalog_terms_confirmed)}

if __name__ == '__main__':
    from ..db import SessionLocal
    with SessionLocal() as db:
        raise SystemExit(0 if report(db)['queue']['worker_healthy'] else 1)
