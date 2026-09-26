"""Answer attempts may change only before a provider request is sent."""
from fastapi import HTTPException
from sqlalchemy import select, text
from .db import Job, Usage
from .store import owned, save_data, enqueue


def submit_answer(db, owner_id, interview_id, index, value):
    # Same lock as worker, so an answer cannot change between its snapshot and payment.
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtext(:key))'), {'key': 'user:' + owner_id}):
        raise HTTPException(409, 'Ответ обрабатывается. Дождитесь результата.')
    row = owned(db, interview_id, owner_id, 'interview', lock=True)
    turns = list(row.data['turns'])
    if not 0 <= index < len(turns):
        raise HTTPException(422)
    if any(not t.get('evaluation') for t in turns[:index]):
        raise HTTPException(409, 'Завершите предыдущий вопрос')
    if turns[index].get('evaluation'):
        raise HTTPException(409, 'Ответ уже оценён')
    key = f'answer:{row.id}:{index}'
    job = db.scalar(select(Job).where(Job.owner_id == owner_id, Job.request_key == key).with_for_update())
    payload = {'interview_id': row.id, 'index': index, 'text': value}
    if job and job.payload != payload:
        sent = db.scalar(select(Usage.key).where(Usage.key.like(job.id + ':%'), Usage.state != 'rejected').limit(1))
        if sent or job.checkpoints or job.status in ('running', 'needs_review', 'completed'):
            raise HTTPException(409, 'Попытка уже отправлена провайдеру. Продолжите её или выполните сверку расходов.')
        job.payload, job.status, job.error, job.attempts = payload, 'queued', None, 0
    turns[index] = {**turns[index], 'answer': value, 'submitted': True}
    save_data(row, turns=turns)
    result = {'job_id': job.id} if job else enqueue(db, owner_id, 'evaluate', payload, key)
    db.commit()
    return result
