from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import Record, Job, now


def owned(db, record_id, owner_id, kind=None, lock=False):
    query = select(Record).where(Record.id == record_id, Record.owner_id == owner_id)
    if kind:
        query = query.where(Record.kind == kind)
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if not record:
        raise HTTPException(404, 'Объект не найден')
    return record


def shared(db, record_id, kind=None):
    return owned(db, record_id, None, kind)


def record_dict(record):
    return {'id': record.id, 'kind': record.kind, 'status': record.status, 'data': record.data,
            'created_at': record.created_at.isoformat(), 'updated_at': record.updated_at.isoformat()}


def save_data(record, **updates):
    record.data = {**record.data, **updates}
    record.updated_at = now()


def enqueue(db, user_id, kind, payload, request_key):
    existing = db.scalar(select(Job).where(Job.owner_id == user_id, Job.request_key == request_key))
    if existing:
        if existing.kind != kind or existing.payload != payload:
            raise HTTPException(409, 'Этот ключ запроса уже использован с другими данными')
        return {'job_id': existing.id}
    job = Job(owner_id=user_id, kind=kind, payload=payload, request_key=request_key)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return enqueue(db, user_id, kind, payload, request_key)
    return {'job_id': job.id}
