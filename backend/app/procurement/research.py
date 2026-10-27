"""Durable market-research jobs.

A job holds one task per *product identity* (not per serial number): 2,892 B002 rows become
52 research tasks. Job and task state live in the database, so a job survives restarts:
tasks left ``running`` by a crashed worker are returned to ``pending`` on recovery, failed tasks
are retried with back-off up to ``max_attempts``, and a cancelled job stops before its next task.
Re-running research never duplicates evidence (observations are unique per product + dedup key).
"""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..db import SessionLocal
from ..models import User
from . import extraction
from .models import PIAsset, PIObservation, PIProduct, PIResearchJob, PIResearchTask, PISource
from .providers import ProviderError, get_provider, queries_for
from .rules import Rules

log = logging.getLogger("clpi.research")
STALE_RUNNING = timedelta(minutes=5)


class ResearchError(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def create_job(db: Session, *, batch_id: int | None, product_ids: list[int] | None, provider: str,
               user: User | None, force: bool = False) -> PIResearchJob:
    p = get_provider(provider) if provider != "offline" else None
    if p and not p.configured():
        raise ResearchError(f"{p.label} is not configured: set {p.env_var} on the server")
    active = db.scalar(select(PIResearchJob).where(PIResearchJob.batch_id == batch_id,
                                                   PIResearchJob.status.in_(("queued", "running"))))
    if batch_id is not None and active is not None:
        return active  # idempotent: one live job per batch
    if product_ids is None:
        if batch_id is None:
            raise ResearchError("Give a batch or a list of products")
        product_ids = sorted({pid for pid in db.scalars(select(PIAsset.product_id).where(
            PIAsset.batch_id == batch_id, PIAsset.product_id.is_not(None))).all()})
    if not product_ids:
        raise ResearchError("No identified products to research")
    job = PIResearchJob(batch_id=batch_id, provider=provider, status="queued", total=len(product_ids),
                        params={"force": force}, created_by=user.id if user else None)
    db.add(job)
    db.flush()
    for pid in product_ids:
        db.add(PIResearchTask(job_id=job.id, product_id=pid))
    audit.record(db, user, "pi.research.queued", "pi_research_job", job.id, batch_id=batch_id, provider=provider,
                 products=len(product_ids))
    return job


def cancel_job(db: Session, job: PIResearchJob, user: User | None) -> None:
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = now()
    db.execute(update(PIResearchTask).where(PIResearchTask.job_id == job.id, PIResearchTask.status == "pending")
               .values(status="cancelled"))
    audit.record(db, user, "pi.research.cancelled", "pi_research_job", job.id)


def resume_job(db: Session, job: PIResearchJob, user: User | None) -> None:
    db.execute(update(PIResearchTask).where(PIResearchTask.job_id == job.id,
                                            PIResearchTask.status.in_(("failed", "cancelled", "running")))
               .values(status="pending", next_attempt_at=None))
    job.status, job.cancel_requested, job.finished_at, job.error = "queued", False, None, None
    audit.record(db, user, "pi.research.resumed", "pi_research_job", job.id)


def recover_stale(db: Session) -> int:
    """Return work abandoned by a crashed worker to the queue."""
    cutoff = now() - STALE_RUNNING
    n = 0
    for job in db.scalars(select(PIResearchJob).where(PIResearchJob.status == "running")).all():
        hb = _aware(job.heartbeat_at) or _aware(job.started_at)
        if hb is None or hb < cutoff:
            db.execute(update(PIResearchTask).where(PIResearchTask.job_id == job.id,
                                                    PIResearchTask.status == "running").values(status="pending"))
            job.status = "queued"
            n += 1
    return n


def next_queued_job(db: Session) -> int | None:
    pending = exists(select(PIResearchTask.id).where(PIResearchTask.job_id == PIResearchJob.id,
                                                   PIResearchTask.status == "pending"))
    due = exists(select(PIResearchTask.id).where(PIResearchTask.job_id == PIResearchJob.id,
        PIResearchTask.status == "pending", or_(PIResearchTask.next_attempt_at.is_(None), PIResearchTask.next_attempt_at <= now())))
    q = select(PIResearchJob.id).where(PIResearchJob.status == "queued", or_(~pending, due)).order_by(PIResearchJob.id).limit(1)
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job_id = db.scalar(q)
    if job_id is not None:
        # Claim while the SELECT lock is still held, before the caller commits.
        claimed = db.execute(update(PIResearchJob).where(PIResearchJob.id == job_id, PIResearchJob.status == "queued")
                             .values(status="running", heartbeat_at=now()))
        return job_id if claimed.rowcount else None
    return None


def _source_for(db: Session, domain: str) -> PISource | None:
    if not domain:
        return None
    s = db.scalar(select(PISource).where(PISource.domain == domain))
    if s is None:
        s = PISource(name=domain, domain=domain, source_kind="unclassified", reliability=0.5, is_active=True,
                     terms_note="Discovered through search results; review reliability and terms.")
        try:
            with db.begin_nested():
                db.add(s)
                db.flush()
        except IntegrityError:
            s = db.scalar(select(PISource).where(PISource.domain == domain))
    return s


def dedup_key(url: str | None, price, when: datetime, provider: str) -> str:
    raw = f"{(url or '').strip().lower()}|{price}|{when.date().isoformat()}|{provider}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _research_product(task_id: int, provider_name: str, rules: Rules, job_id: int,
                      transport: httpx.BaseTransport | None) -> None:
    with SessionLocal() as db:
        task = db.get(PIResearchTask, task_id)
        job = db.get(PIResearchJob, job_id)
        if task is None or task.status not in ("pending", "running"):
            return
        if job.cancel_requested:
            task.status = "cancelled"
            db.commit()
            return
        task.status, task.attempts, task.updated_at = "running", task.attempts + 1, now()
        db.commit()
        product = db.get(PIProduct, task.product_id)
        cutoff = now() - timedelta(days=rules.research.cache_days)
        if not (job.params or {}).get("force") and rules.research.cache_days > 0:
            recent = db.scalar(select(func.count(PIObservation.id)).where(
                PIObservation.product_id == product.id, PIObservation.provider.in_(("brave", "tavily")),
                PIObservation.retrieved_at >= cutoff, PIObservation.observed_at >= cutoff, PIObservation.status == "verified",
                PIObservation.price.is_not(None)))
            if recent:
                task.status, task.observations_found, task.updated_at = "cached", 0, now()
                db.execute(update(PIResearchJob).where(PIResearchJob.id == job_id).values(
                    done=PIResearchJob.done+1, cached=PIResearchJob.cached+1, heartbeat_at=now()))
                db.commit()
                return
        if provider_name == "offline":
            task.status, task.updated_at = "cached", now()
            db.execute(update(PIResearchJob).where(PIResearchJob.id == job_id).values(done=PIResearchJob.done+1, heartbeat_at=now()))
            db.commit()
            return
        from .providers import PROVIDERS
        names = [provider_name] + [n for n in PROVIDERS if n != provider_name and get_provider(n).configured()]
        provider = get_provider(provider_name, transport)
        qlog, found, seen_keys = [], 0, set()
        try:
            for q in queries_for(product.category, product.spec, product.label, rules.research.queries_per_product):
                errors, hits = [], []
                collected = []
                for name in names:
                    provider = get_provider(name, transport)
                    try:
                        hits = provider.search(q, count=rules.research.max_results_per_query, country=rules.research.country)
                    except ProviderError as e:
                        errors.append(e)
                        qlog.append({"provider": name, "query": q, "error": str(e), "hits": 0})
                        continue
                    collected.extend(hits)
                    # A response containing unrelated products or only unpriced leads is not a usable fallback.
                    if any(extraction.match_quality(product.category, product.spec, h.title + " " + h.snippet + " " + str(h.extra.get("raw_content") or "")) == "identical"
                           and extraction.confirmed_offer(h, product.category, product.spec)[0] is not None for h in hits):
                        break
                hits = collected
                if not hits and len(errors) == len(names):
                    raise ProviderError("; ".join(str(e) for e in errors), any(e.retryable for e in errors))
                entry = {"query": q, "hits": len(hits), "kept": 0, "leads": 0, "rejected": {}}
                for h in hits:
                    dom = extraction.domain_of(h.url)
                    src = _source_for(db, dom)
                    if src is not None and not src.is_active:
                        entry["rejected"]["source disabled"] = entry["rejected"].get("source disabled", 0) + 1
                        continue
                    c = extraction.to_candidate(h, product.category, product.spec, src.default_price_type if src else None)
                    rejected = c.reason and c.reason != "no price shown in the provider's result text"
                    if rejected:
                        entry["rejected"][c.reason] = entry["rejected"].get(c.reason, 0) + 1
                    ts = now()
                    status = "lead" if c.price is None else "candidate"
                    reason = "no price in provider result; open the source to verify" if c.price is None else None
                    amount, confirmation = extraction.confirmed_offer(h, product.category, product.spec)
                    if (not rejected and amount is not None and rules.research.auto_accept_confirmed
                            and c.match_quality == "identical" and c.condition in ("used", "refurbished")
                            and src is not None and src.is_active):
                        c.price = amount
                        status, reason = "verified", f"Automatically validated: {confirmation}; exact specification"
                    elif rejected:
                        status, reason = "rejected", c.reason
                    elif c.price is not None:
                        reason = "Snippet-only price; requires confirmed offer or authorized verification"
                    source_when = extraction.source_timestamp(h)
                    key = dedup_key(c.url, c.price, ts, h.provider)
                    if key in seen_keys or db.scalar(select(PIObservation.id).where(
                            PIObservation.product_id == product.id, PIObservation.dedup_key == key)):
                        entry["rejected"]["duplicate listing"] = entry["rejected"].get("duplicate listing", 0) + 1
                        continue
                    seen_keys.add(key)
                    db.add(PIObservation(
                        product_id=product.id, source_id=src.id if src else None, provider=h.provider,
                        price_type=c.price_type, match_quality=c.match_quality, title=c.title, price=c.price,
                        currency="INR", tax_basis="unknown", condition=c.condition, seller=src.name if src else dom,
                        url=c.url, observed_at=source_when or ts, retrieved_at=ts, snippet=c.snippet, status=status,
                        status_reason=reason, dedup_key=key, research_job_id=job_id,
                        attributes={"query": q, "other_prices_in_snippet": c.other_prices,
                                    "research_mode": "live_search_confirmed" if status == "verified" else "search_candidate",
                                    "confirmation": confirmation, "match_score": 1.0 if c.match_quality == "identical" else 0.5,
                                    "specifications": product.spec,
                                    "source_timestamp": source_when.isoformat() if source_when else None,
                                    "source_date_basis": "provider_timestamp" if source_when else "retrieval_only"}))
                    if status == "lead":
                        entry["leads"] += 1
                    elif status != "rejected":
                        entry["kept"] += 1
                        found += 1
                qlog.append(entry)
            task.status, task.queries, task.hits = "done", qlog, sum(e["hits"] for e in qlog)
            task.observations_found, task.error = found, None
        except ProviderError as e:
            db.rollback()
            task = db.get(PIResearchTask, task_id)
            task.error = str(e)
            task.queries = qlog
            if e.retryable and task.attempts < rules.research.max_attempts:
                task.status = "pending"
                task.next_attempt_at = now() + timedelta(seconds=rules.research.retry_backoff_seconds * task.attempts)
            else:
                task.status = "failed"
        except Exception as e:  # isolate failures to the task
            log.error("research task %s failed (%s)", task_id, type(e).__name__)
            db.rollback()
            task = db.get(PIResearchTask, task_id)
            task.status, task.error = "failed", f"Research task failed ({type(e).__name__}); check configuration"
        task.updated_at = now()
        if task.status in ("done", "failed"):
            db.execute(update(PIResearchJob).where(PIResearchJob.id == job_id).values(
                done=PIResearchJob.done + int(task.status == "done"),
                failed=PIResearchJob.failed + int(task.status == "failed"), heartbeat_at=now()))
        db.commit()


def run_job(job_id: int, rules: Rules, *, transport: httpx.BaseTransport | None = None,
            wait_for_backoff: bool = False) -> None:
    """Process all runnable tasks of a job. Safe to call again (idempotent, resumable)."""
    with SessionLocal() as db:
        job = db.get(PIResearchJob, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status, job.started_at, job.heartbeat_at = "running", job.started_at or now(), now()
        db.commit()
        provider_name = job.provider
    while True:
        with SessionLocal() as db:
            job = db.get(PIResearchJob, job_id)
            if job.cancel_requested:
                break
            tasks = db.scalars(select(PIResearchTask).where(PIResearchTask.job_id == job_id,
                                                            PIResearchTask.status == "pending")).all()
            due = [t.id for t in tasks if t.next_attempt_at is None or _aware(t.next_attempt_at) <= now()]
            waiting = len(tasks) - len(due)
        if not due:
            if waiting and wait_for_backoff:
                import time
                time.sleep(1)
                continue
            break
        with ThreadPoolExecutor(max_workers=rules.research.concurrency) as pool:
            list(pool.map(lambda tid: _research_product(tid, provider_name, rules, job_id, transport), due))
        with SessionLocal() as db:
            current = db.get(PIResearchJob, job_id)
            current.heartbeat_at = now()
            current.done = db.scalar(select(func.count()).select_from(PIResearchTask).where(
                PIResearchTask.job_id == job_id, PIResearchTask.status.in_(("done", "cached")))) or 0
            db.commit()
        if waiting and not wait_for_backoff:
            break
    finalize(job_id)


def finalize(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(PIResearchJob, job_id)
        counts = dict(db.execute(select(PIResearchTask.status, func.count()).where(PIResearchTask.job_id == job_id)
                                 .group_by(PIResearchTask.status)).all())
        job.done = counts.get("done", 0) + counts.get("cached", 0)
        job.cached = counts.get("cached", 0)
        job.failed = counts.get("failed", 0)
        job.observations_found = db.scalar(select(func.coalesce(func.sum(PIResearchTask.observations_found), 0))
                                           .where(PIResearchTask.job_id == job_id)) or 0
        pending = counts.get("pending", 0) + counts.get("running", 0)
        if job.cancel_requested:
            job.status = "cancelled"
        elif pending:
            job.status = "queued"  # back-off retries outstanding; the worker will pick it up again
        elif job.failed and job.done:
            job.status = "completed_with_errors"
        elif job.failed:
            job.status = "failed"
            job.error = db.scalar(select(PIResearchTask.error).where(PIResearchTask.job_id == job_id,
                                                                     PIResearchTask.status == "failed").limit(1))
        else:
            job.status = "completed"
        if job.status != "queued":
            job.finished_at = now()
        audit.record(db, None, "pi.research.finished", "pi_research_job", job.id, status=job.status, done=job.done,
                     failed=job.failed, observations=job.observations_found)
        db.commit()
