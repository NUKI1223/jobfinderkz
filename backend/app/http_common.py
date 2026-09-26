import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import select, text
from .config import settings
from .db import User, uid
from .store import record_dict
from .cv_sections import section_draft

PREFIX = '/api/v1'
attempts = defaultdict(deque)
attempts_lock = threading.Lock()

def throttle(request):
    host = request.client.host
    with attempts_lock:
        ticks = attempts[host]
        current = time.monotonic()
        while ticks and ticks[0] < current - 60:
            ticks.popleft()
        if len(ticks) >= 15:
            raise HTTPException(429, 'Слишком много попыток. Подождите минуту.')
        ticks.append(current)


def request_key(value):
    if value and (len(value) > 100 or not value.isascii()):
        raise HTTPException(422, 'Неверный Idempotency-Key')
    return value or uid()


def public_record(row):
    value = record_dict(row)
    value['data'] = {k: v for k, v in value['data'].items() if k != 'file_path'}
    if row.kind == 'cv' and not value['data'].get('facts'):
        value['data'] = {**value['data'], **section_draft(value['data'].get('text', ''))}
    return value


async def upload(file, user_id, extensions, limit, db):
    # Same transaction lock as account deletion, held until upload + record commit.
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtext(:key))'), {'key': 'user:' + user_id}):
        raise HTTPException(409, 'Дождитесь завершения операции аккаунта')
    if db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(401, 'Аккаунт удалён')
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in extensions:
        raise HTTPException(422, 'Неподдерживаемый формат файла')
    directory = settings.storage_path / 'users' / user_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uid() + suffix)
    size = 0
    try:
        with path.open('xb') as output:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise HTTPException(413, 'Файл слишком большой')
                output.write(block)
        if not size:
            raise HTTPException(422, 'Файл пуст')
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return path


def job_dict(job):
    return {'id': job.id, 'kind': job.kind, 'status': job.status, 'result': job.result, 'error': job.error,
            'created_at': job.created_at.isoformat(), 'attempts': job.attempts, 'completed_steps': list(job.checkpoints),
            'context': {k: job.payload[k] for k in ('interview_id', 'index') if k in job.payload},
            'sent': bool(job.checkpoints) or job.status == 'needs_review'}


def json_key(value):
    import json
    return json.dumps(value, sort_keys=True)
