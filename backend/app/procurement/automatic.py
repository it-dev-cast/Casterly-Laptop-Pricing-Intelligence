"""Durable automatic valuation orchestration. No invented evidence or automatic approvals."""
from __future__ import annotations
import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from ..config import get_settings
from ..db import SessionLocal
from ..importing.files import stored_path
from ..models import User
from .models import PIBatch, PIAsset, PIProduct, PIObservation, PIResearchJob
from . import providers, research, service
from .rules import Rules

log = logging.getLogger('clpi.automatic')
PHASES = ['Importing assets', 'Identifying products', 'Researching market', 'Validating price evidence',
          'Calculating procurement prices', 'Generating quotation']


def phase(db, job, label, **values):
    params = dict(job.params or {})
    events = list(params.get('events', []))
    if not events or events[-1]['phase'] != label:
        events.append({'phase': label, 'at': datetime.now(timezone.utc).isoformat()})
    job.params = {**params, **values, 'phase': label, 'events': events}
    job.heartbeat_at = research.now()
    db.commit()


def queue(db, batch, user):
    existing = db.scalar(select(PIResearchJob).where(PIResearchJob.batch_id == batch.id,
                         PIResearchJob.status.in_(('queued', 'running'))))
    if existing:
        return existing
    rules, version = service.active_rules(db)
    provider = providers.default_provider() or 'offline'
    ids = sorted(set(db.scalars(select(PIAsset.product_id).where(PIAsset.batch_id == batch.id,
                     PIAsset.product_id.is_not(None))).all()))
    if ids:
        job = research.create_job(db, batch_id=batch.id, product_ids=ids, provider=provider, user=user)
    else:
        job = PIResearchJob(batch_id=batch.id, provider=provider, status='queued', total=0, created_by=user.id)
        db.add(job)
        db.flush()
    stamp = batch.created_at.isoformat()
    job.params = {**(job.params or {}), 'automatic': True, 'rule_version_id': version.id,
                  'rules_snapshot': rules.model_dump(mode='json'), 'phase': 'Queued for analysis',
                  'research_mode': 'configured_live_search' if provider != 'offline' else 'offline_history',
                  'events': [{'phase': 'Importing assets', 'at': stamp},
                             {'phase': 'Identifying products', 'at': (batch.detection or {}).get('identified_at', stamp)}]}
    batch.status = 'analyzing'
    db.flush()
    return job


def import_configured_references(db):
    """Only administrator-configured directories, never silently import test fixtures in production."""
    from .reference import import_reference_pack
    reports = []
    for directory in get_settings().reference_dirs:
        if not directory.is_dir():
            reports.append({'directory': str(directory), 'status': 'missing'})
            continue
        for path in sorted(directory.glob('*.xlsx')):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if any((o.attributes or {}).get('sha256') == digest and (o.attributes or {}).get('identity_version') == 'pi-identity-1.1' for o in db.scalars(
                    select(PIObservation).where(PIObservation.provider == 'reference_pack')).all()):
                continue
            try:
                with db.begin_nested():
                    res = import_reference_pack(db, None, filename=path.name, content=path.read_bytes())
                reports.append({'file': path.name, 'status': 'imported', 'observations': res['historical_observations']})
            except (service.ServiceError, ValueError):
                reports.append({'file': path.name, 'status': 'needs_review', 'reason': 'Completed dated workbook required'})
    return reports


def catalog_evidence(db, product_ids):
    """Approved local catalog feed. No web crawling; configured feed owner confirms authorized use."""
    cfg = get_settings()
    if not cfg.approved_catalog_path or not cfg.approved_catalog_terms_confirmed:
        return {'status': 'not_configured', 'added': 0}
    try:
        records = json.loads(cfg.approved_catalog_path.read_text(encoding='utf-8-sig'))
        if not isinstance(records, list):
            raise ValueError('Catalog must be an array')
    except (OSError, ValueError):
        return {'status': 'unavailable', 'added': 0}
    products = {p.product_key:p for p in db.scalars(select(PIProduct).where(PIProduct.id.in_(product_ids))).all()}
    added = rejected = 0
    from .rules import PRICE_TYPES
    for record in records:
        try:
            p = products.get(record['product_key'])
            if p is None:
                continue
            price = Decimal(str(record['price']))
            when = datetime.fromisoformat(record['observed_at'].replace('Z', '+00:00'))
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            ptype = record['price_type']
            if not price.is_finite() or price <= 0 or when > research.now() or ptype not in PRICE_TYPES:
                raise ValueError('Invalid amount, date or price type')
            if record.get('currency') != 'INR' or record.get('tax_basis') not in ('inclusive','exclusive'):
                raise ValueError('Explicit currency and tax basis required')
            if record.get('match_quality', 'identical') != 'identical':
                raise ValueError('Catalog requires exact product identity')
            key = research.dedup_key(record.get('url') or 'catalog:'+p.product_key, price, when, 'approved_catalog')
            if db.scalar(select(PIObservation.id).where(PIObservation.product_id == p.id, PIObservation.dedup_key == key)):
                continue
            db.add(PIObservation(product_id=p.id, provider='approved_catalog', price_type=ptype,
                   match_quality='identical', title=record.get('title', p.label)[:500], price=price, currency='INR',
                   tax_basis=record['tax_basis'], condition=record.get('condition'), seller=record.get('seller'),
                   url=record.get('url'), observed_at=when, retrieved_at=research.now(), status='verified',
                   status_reason='Authorized configured catalog; exact product key', dedup_key=key,
                   attributes={'research_mode':'approved_catalog', 'source_timestamp':when.isoformat(),
                               'grade':record.get('grade')}))
            added += 1
        except (KeyError, TypeError, ValueError, InvalidOperation):
            rejected += 1
    db.flush()
    return {'status':'loaded', 'added':added, 'rejected':rejected}


def similar_evidence(db, product_ids, rules):
    """No inferred monetary adjustment unless an administrator supplied an explicit versioned factor."""
    for p in db.scalars(select(PIProduct).where(PIProduct.id.in_(product_ids))).all():
        exact = db.scalars(select(PIObservation).where(PIObservation.product_id == p.id,
              PIObservation.status == 'verified', PIObservation.match_quality == 'identical', PIObservation.price.is_not(None))).all()
        if any(0 <= (research.now()-research._aware(o.observed_at)).total_seconds()/86400 <=
               (rules.provisional_max_age_days if o.price_type == 'historical_valuation' else rules.freshness_days.get(o.price_type,30)) for o in exact):
            continue
        mapping = rules.similar_model_factors.get(p.product_key)
        if not mapping:
            continue
        source = db.scalar(select(PIProduct).where(PIProduct.product_key == mapping.get('source_product_key')))
        try:
            factor = Decimal(str(mapping['factor']))
            if not factor.is_finite() or factor <= 0 or not mapping.get('reason'):
                continue
        except (KeyError, InvalidOperation):
            continue
        if source is None or source.category != p.category:
            continue
        observation = db.scalar(select(PIObservation).where(PIObservation.product_id == source.id,
                       PIObservation.status == 'verified', PIObservation.price.is_not(None))
                       .order_by(PIObservation.observed_at.desc()).limit(1))
        if observation is None or observation.provider == 'similar_model':
            continue
        price = observation.price * factor
        key = research.dedup_key('similar:'+str(observation.id)+':'+str(factor),price,observation.observed_at,'similar_model')
        if db.scalar(select(PIObservation.id).where(PIObservation.product_id==p.id, PIObservation.dedup_key==key)):
            continue
        db.add(PIObservation(product_id=p.id, provider='similar_model', price_type=observation.price_type,
               match_quality='comparable', title='Provisional comparable: '+source.label, price=price,
               currency=observation.currency, tax_basis=observation.tax_basis, observed_at=observation.observed_at,
               url=observation.url, status='verified', dedup_key=key,
               attributes={'research_mode':'similar_model_estimate','factor':str(factor), 'reason':mapping['reason'],
                           'source_observation_id':observation.id}))
    db.flush()


def complete(job_id):
    """Continue after research, including failed/offline research; errors never become success."""
    with SessionLocal() as db:
        job = db.get(PIResearchJob, job_id)
        params = job.params or {}
        if not params.get('automatic') or job.status in ('queued','cancelled') or params.get('phase') in ('Completed','Needs Review','Research Unavailable'):
            return
        if job.cancel_requested:
            return
        batch = db.get(PIBatch,job.batch_id)
        user = db.get(User,job.created_by)
        rules = Rules.model_validate(params['rules_snapshot'])
        try:
            job.status = 'running'
            phase(db,job,'Validating price evidence')
            refs = import_configured_references(db)
            ids = list(db.scalars(select(PIAsset.product_id).where(PIAsset.batch_id==batch.id, PIAsset.product_id.is_not(None))).all())
            # A verified fresh search offer takes precedence over catalog fallback for the same product.
            live_ids = set()
            for ob in db.scalars(select(PIObservation).where(PIObservation.product_id.in_(ids), PIObservation.status=='verified')).all():
                if (ob.attributes or {}).get('research_mode') == 'live_search_confirmed' and ob.price and (
                    research.now()-research._aware(ob.observed_at)).total_seconds()/86400 <= rules.freshness_days.get(ob.price_type,30):
                    live_ids.add(ob.product_id)
            cat = catalog_evidence(db,[pid for pid in ids if pid not in live_ids])
            similar_evidence(db,ids,rules)
            phase(db,job,'Calculating procurement prices', catalog=cat, reference_imports=refs)
            result = service.price_batch(db,batch,user,rules_version_id=params['rule_version_id'])
            phase(db,job,'Generating quotation', calculation=result)
            quote = None
            if any(a.final_price is not None and a.quantity for a in db.scalars(select(PIAsset).where(PIAsset.batch_id==batch.id)).all()):
                quote,_ = service.create_quotation(db,user,batch,vendor=batch.vendor,
                    notes='Automatic draft only; review provisional prices and exceptions before approval.',include_unapproved=True)
            db.flush()  # quotation lines must be visible before workbook snapshot queries
            from .excel_export import build
            content, integrity = build(db,batch,quote)
            digest = hashlib.sha256(content).hexdigest()
            artifact_name = 'valuation-'+str(job.id)+'-'+digest[:16]+'.xlsx'
            stored_path(artifact_name).write_bytes(content)
            summary = service.batch_out(db,batch)
            priced = sum(n['lines'] for s,n in summary['by_status'].items() if s != 'manual_required')
            final = 'Research Unavailable' if not priced else ('Needs Review' if summary['open_exceptions'] or
                    any(s in summary['by_status'] for s in ('provisional','manual_required','review')) else 'Completed')
            batch.status = {'Completed':'completed','Needs Review':'needs_review','Research Unavailable':'research_unavailable'}[final]
            job.status = 'completed_with_errors' if job.failed else 'completed'
            job.finished_at = research.now()
            phase(db,job,final,artifact=artifact_name,artifact_sha256=digest,integrity=integrity,
                  quotation_id=quote.id if quote else None, priced_lines=integrity["prices_written"], prices_available=priced,
                  result=final, research_errors=job.failed)
        except Exception as e:
            db.rollback()
            job = db.get(PIResearchJob,job_id)
            job.status,job.error,job.finished_at = 'failed',f'Automatic workflow failed ({type(e).__name__}); check server diagnostics',research.now()
            phase(db,job,'Failed')
            log.error('Automatic valuation job %s failed (%s)',job_id,type(e).__name__)
