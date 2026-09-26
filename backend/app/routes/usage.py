from fastapi import Depends
from sqlalchemy import select
from ..config import settings
from ..db import Budget, Usage, now
from ..security import admin, db_session

from fastapi import APIRouter
from ..http_common import PREFIX
from ..reconciliation import Reconciliation, reconcile

router = APIRouter()

@router.get(PREFIX + '/admin/usage/summary')
def usage_summary(user=Depends(admin), db=Depends(db_session)):
    month = now().strftime('%Y-%m')
    budget = db.get(Budget, month)
    usage = db.scalars(select(Usage).where(Usage.month == month).order_by(Usage.created_at.desc())).all()
    completed = sum(float(u.actual or 0) for u in usage if u.state in ('completed', 'reconciled'))
    reserved = sum(float(u.reserved) for u in usage if u.state in ('reserved', 'uncertain'))
    audio_estimates = sum(float(u.actual or 0) for u in usage
        if u.state == 'completed' and u.details.get('method') == 'audio_duration_estimate')
    return {'month': month, 'limit': settings.monthly_budget_usd, 'charged_and_reserved': float(budget.charged) if budget else 0,
        'completed': completed, 'open_reservations': reserved, 'audio_estimates': audio_estimates,
        'remaining': max(0, settings.monthly_budget_usd - float(budget.charged if budget else 0)),
        'video_hours': budget.video_seconds / 3600 if budget else 0,
        'operations': [{'key': u.key, 'model': u.model, 'state': u.state, 'reserved': float(u.reserved),
                        'actual': float(u.actual) if u.actual is not None else None,
                        'operation': u.operation, 'details': u.details} for u in usage]}


@router.post(PREFIX + '/admin/usage/{usage_key}/reconcile')
def reconcile_usage(usage_key: str, body: Reconciliation, user=Depends(admin), db=Depends(db_session)):
    return reconcile(db, usage_key, body, user.id)


