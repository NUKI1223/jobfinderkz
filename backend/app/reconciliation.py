"""Explicit, audited accounting corrections; no automatic paid replay."""
from decimal import Decimal
from typing import Literal
from pydantic import Field
from fastapi import HTTPException
from sqlalchemy import select, text
from .db import Usage, Budget, Job, now
from .schemas import Strict


class Reconciliation(Strict):
    outcome: Literal['not_charged', 'charged', 'result_lost']
    amount: Decimal | None = Field(default=None, ge=0, le=100)
    evidence: str = Field(min_length=10, max_length=2000)


def reconcile(db, key, body, actor):
    usage = db.get(Usage, key)
    if not usage:
        raise HTTPException(404)
    job = db.get(Job, key.split(':', 1)[0])
    if job and not db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtext(:key))'), {'key': 'user:' + job.owner_id}):
        raise HTTPException(409, 'Дождитесь завершения запроса worker')
    # Lock ordering matches reserve/settlement: budget before usage.
    budget = db.scalar(select(Budget).where(Budget.month == usage.month).with_for_update())
    usage = db.scalar(select(Usage).where(Usage.key == key).with_for_update().execution_options(populate_existing=True))
    if usage.state not in ('reserved', 'uncertain'):
        raise HTTPException(409, 'Эта операция уже сверена или завершена')
    if body.outcome == 'charged' and body.amount is None:
        raise HTTPException(422, 'Укажите подтверждённую сумму списания')
    amount = Decimal(0) if body.outcome == 'not_charged' else body.amount
    if amount is None:
        amount = usage.reserved  # Lost result with unknown charge keeps the ceiling.
    budget.charged += amount - usage.reserved
    previous = {'state': usage.state, 'reserved': str(usage.reserved), 'actual': str(usage.actual)}
    usage.actual = amount
    usage.state = 'rejected' if body.outcome == 'not_charged' else 'reconciled'
    usage.details = {**usage.details, 'reconciliations': usage.details.get('reconciliations', []) + [{
        'actor_id': actor, 'at': now().isoformat(), 'outcome': body.outcome,
        'amount_known': body.amount is not None or body.outcome == 'not_charged',
        'evidence': body.evidence, 'previous': previous, 'amount': str(amount)}]}
    if job and job.status == 'needs_review':
        job.status = 'paused' if body.outcome == 'not_charged' else 'needs_review'
        job.error = ('Подтверждено отсутствие списания. Повтор возможен только по кнопке «Продолжить».'
            if body.outcome == 'not_charged' else 'Расход сверён; результат отсутствует. Повторная оплата заблокирована.')
    db.commit()
    return {'key': key, 'state': usage.state, 'amount': str(amount)}
