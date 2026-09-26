from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from .db import Record, Job, GlobalOperation, now


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
    if kind == 'index_knowledge':
        operation = f"index:{payload['record_id']}:{payload.get('version', 1)}"
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': operation})
        operation_row = db.get(GlobalOperation, operation)
        if operation_row:
            if db.get(Job, operation_row.job_id) is None:
                raise HTTPException(409, 'Операция этой версии уже выполнялась; инициатор удалён. Повторная оплата заблокирована.')
            return {'job_id': operation_row.job_id}
        # Includes legacy per-admin keys and unknown outcomes.
        existing = db.scalar(select(Job).where(Job.kind == kind,
            Job.payload['record_id'].as_string() == payload['record_id'],
            Job.payload['version'].as_integer() == payload.get('version', 1)).order_by(Job.created_at))
        if existing:
            db.add(GlobalOperation(key=operation, job_id=existing.id))
            return {'job_id': existing.id}
    existing = db.scalar(select(Job).where(Job.owner_id == user_id, Job.request_key == request_key))
    if existing:
        if existing.kind != kind or existing.payload != payload:
            raise HTTPException(409, 'Этот ключ запроса уже использован с другими данными')
        return {'job_id': existing.id}
    job = Job(owner_id=user_id, kind=kind, payload=payload, request_key=request_key)
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, 'sqlstate', None) != '23505':
            raise
        existing = db.scalar(select(Job).where(Job.owner_id == user_id, Job.request_key == request_key))
        if existing is None:
            raise
        if existing.kind != kind or existing.payload != payload:
            raise HTTPException(409, 'Этот ключ запроса уже использован с другими данными') from exc
        return {'job_id': existing.id}
    if kind == 'index_knowledge':
        db.add(GlobalOperation(key=operation, job_id=job.id))
    db.flush()
    return {'job_id': job.id}
