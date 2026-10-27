"""Background worker for market-research jobs.

Runs either as a daemon thread inside the API process (``CLPI_RESEARCH_WORKER=thread``, default)
or as a separate process: ``python -m app.procurement.worker`` (the ``worker`` service in
docker-compose). Several workers may run against PostgreSQL: jobs are claimed with
``SELECT ... FOR UPDATE SKIP LOCKED``.
"""
from __future__ import annotations

import logging
import threading
import time

from ..config import get_settings
from ..db import SessionLocal
from . import research
from .service import active_rules
from .models import PIResearchJob
from .rules import Rules
from . import automatic

log = logging.getLogger("clpi.worker")
_thread: threading.Thread | None = None
_stop = threading.Event()


def run_once() -> int | None:
    with SessionLocal() as db:
        research.recover_stale(db)
        db.commit()
        job_id = research.next_queued_job(db)
        if job_id is None:
            db.commit()
            return None
        rules, _ = active_rules(db)
        job = db.get(PIResearchJob, job_id)
        if (job.params or {}).get('rules_snapshot'):
            rules = Rules.model_validate(job.params['rules_snapshot'])
            automatic.phase(db, job, 'Researching market')
        db.commit()
    research.run_job(job_id, rules)
    automatic.complete(job_id)
    return job_id


def loop(stop: threading.Event | None = None) -> None:
    stop = stop or _stop
    interval = get_settings().research_poll_seconds
    while not stop.is_set():
        try:
            from .diagnostics import heartbeat
            heartbeat()
            if run_once() is None:
                stop.wait(interval)
        except Exception:  # keep the worker alive; the job/task rows record the failure
            log.exception("research worker iteration failed")
            stop.wait(interval)


def start_in_process() -> None:
    global _thread
    if get_settings().research_worker != "thread" or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=loop, name="pi-research-worker", daemon=True)
    _thread.start()


def stop_in_process() -> None:
    _stop.set()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    log.info("Pricing Intelligence research worker started")
    while True:
        try:
            loop()
        except KeyboardInterrupt:
            break
        time.sleep(1)
