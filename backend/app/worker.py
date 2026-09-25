import logging
import time
from sqlalchemy import select, text
from .db import Session, Job, engine, now
from .tasks import HANDLERS
from .ai import Paused, Uncertain

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def run_once():
    with Session() as db:
        jobs = db.scalars(select(Job).where(Job.status.in_(['queued', 'running']))
                          .order_by(Job.created_at).limit(50)).all()
    for candidate in jobs:
        # Session advisory locks survive transaction commits but disappear if worker dies.
        # Hold a dedicated connection, never return a locked connection to the pool.
        with engine.connect() as lock:
            acquired = lock.scalar(text('SELECT pg_try_advisory_lock(hashtext(:key))'), {'key': candidate.id})
            if not acquired:
                continue
            user_acquired = False
            source_acquired = False
            source_key = ('source:' + candidate.payload['source_id']) if candidate.kind in ('import_source', 'extract_questions') else None
            try:
                user_acquired = lock.scalar(text('SELECT pg_try_advisory_lock(hashtext(:key))'), {'key': 'user:' + candidate.owner_id})
                if not user_acquired:
                    continue
                # Shared sources can be processed by different administrators.
                if source_key:
                    source_acquired = lock.scalar(text('SELECT pg_try_advisory_lock(hashtext(:key))'), {'key': source_key})
                    if not source_acquired:
                        continue
                with Session.begin() as db:
                    job = db.get(Job, candidate.id)
                    if not job or job.status not in ('queued', 'running'):
                        continue
                    if job.attempts >= 3:
                        job.status, job.error = 'failed', 'Достигнут лимит попыток восстановления'
                        continue
                    job.status, job.error = 'running', None
                    job.attempts += 1
                    job.heartbeat = now()
                try:
                    result = HANDLERS[job.kind](job)
                    state, error = 'completed', None
                except Paused as exc:
                    result, state, error = {}, 'paused', str(exc)
                except Uncertain as exc:
                    result, state, error = {}, 'needs_review', str(exc)
                except ValueError as exc:
                    result, state, error = {}, 'failed', str(exc)
                except Exception as exc:
                    # No payloads or tracebacks containing private documents in logs.
                    logging.error('Job %s failed: %s', job.id, type(exc).__name__)
                    result, state, error = {}, 'failed', 'Операция не завершена: ' + type(exc).__name__
                with Session.begin() as db:
                    current = db.get(Job, job.id)
                    if current:
                        current.result, current.status, current.error, current.heartbeat = result, state, error, now()
                        if state == 'paused':
                            # Missing credentials/budget are waiting conditions, not
                            # failed retries. They must not permanently exhaust a job.
                            current.attempts = max(0, current.attempts - 1)
                return True
            finally:
                if source_acquired:
                    lock.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': source_key})
                if user_acquired:
                    lock.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': 'user:' + candidate.owner_id})
                lock.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': candidate.id})
                lock.commit()
    return False


if __name__ == '__main__':
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except Exception as exc:
            logging.error('Worker connection failure: %s', type(exc).__name__)
            time.sleep(5)
