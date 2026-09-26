"""Durable transcription attempts bound to a specific interview turn."""
import hashlib
from fastapi import HTTPException
from sqlalchemy import select, or_, and_
from .db import Job
from .store import owned, save_data, enqueue


def enqueue_audio(db, owner_id, interview_id, index, path, key):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # Retry with same bytes is safe even if the client lost its request key.
    key = 'audio:' + (key or hashlib.sha256(f'{interview_id}:{index}:{digest}'.encode()).hexdigest())
    row = owned(db, interview_id, owner_id, 'interview', lock=True)
    existing = db.scalar(select(Job).where(Job.owner_id == owner_id, or_(Job.request_key == key, and_(Job.kind == 'audio_answer',
        Job.payload['interview_id'].as_string() == interview_id, Job.payload['index'].as_integer() == index,
        Job.payload['digest'].as_string() == digest))))
    if existing:
        path.unlink(missing_ok=True)
        if (existing.kind != 'audio_answer' or existing.payload.get('digest') != digest
                or existing.payload.get('index') != index or existing.payload.get('interview_id') != interview_id):
            raise HTTPException(409, 'Ключ записи уже связан с другим ответом')
        return {'job_id': existing.id}
    turns = list(row.data['turns'])
    if not 0 <= index < len(turns) or turns[index].get('evaluation') or turns[index].get('submitted'):
        path.unlink(missing_ok=True)
        raise HTTPException(409, 'Ответ уже отправлен; выберите текущий вопрос')
    if any(not t.get('evaluation') for t in turns[:index]):
        path.unlink(missing_ok=True)
        raise HTTPException(409, 'Завершите предыдущий вопрос')
    prior = db.get(Job, turns[index].get('audio_job_id', ''))
    if prior and prior.status in ('queued', 'running', 'needs_review'):
        path.unlink(missing_ok=True)
        raise HTTPException(409, 'Запись уже обрабатывается или ожидает сверки. Продолжите существующую попытку.')
    payload = {'interview_id': interview_id, 'index': index, 'digest': digest, 'path': str(path)}
    result = enqueue(db, owner_id, 'audio_answer', payload, key)
    turns[index] = {**turns[index], 'audio_job_id': result['job_id']}
    save_data(row, turns=turns)
    db.commit()
    return result
