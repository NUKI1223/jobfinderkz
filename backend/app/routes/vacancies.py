from ..workflows.queue import submit_job
import hashlib
from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from pydantic import Field
from ..config import settings
from ..db import Record, Job
from ..security import current_user, admin, db_session
from ..schemas import HHQuery, Strict, VacancyInput
from ..store import owned, save_data
from ..ai import text_available

from fastapi import APIRouter
from ..http_common import PREFIX, request_key, public_record

router = APIRouter()

@router.post(PREFIX + '/vacancies')
def vacancy_create(body: VacancyInput, user=Depends(admin), db=Depends(db_session)):
    data = body.model_dump()
    key = hashlib.sha256((body.url or body.title + body.description).strip().encode()).hexdigest()
    existing = db.scalar(select(Record).where(Record.owner_id == user.id, Record.kind == 'vacancy', Record.dedup_key == key))
    if existing:
        return public_record(existing)
    row = Record(kind='vacancy', owner_id=user.id, dedup_key=key, status='saved', data={**data, 'source': 'manual', 'favorite': False})
    db.add(row)
    db.commit()
    return public_record(row)


@router.post(PREFIX + '/vacancies/{vacancy_id}/favorite')
def favorite(vacancy_id: str, user=Depends(current_user), db=Depends(db_session), if_match: str | None = Header(None)):
    row = owned(db, vacancy_id, user.id, 'vacancy', lock=True)
    if if_match is not None and if_match != row.updated_at.isoformat():
        raise HTTPException(409, 'Объект изменён. Обновите данные перед сохранением.')
    save_data(row, favorite=not row.data.get('favorite', False))
    db.commit()
    return public_record(row)


class RankRequest(Strict):
    cv_id: str
    vacancy_ids: list[str] = Field(min_length=1, max_length=20)


@router.post(PREFIX + '/vacancies/rank')
def rank_create(body: RankRequest, user=Depends(current_user), db=Depends(db_session), idempotency_key: str | None = Header(None)):
    owned(db, body.cv_id, user.id, 'cv')
    for rid in body.vacancy_ids:
        owned(db, rid, user.id, 'vacancy')
    return submit_job(db, user.id, 'rank', body.model_dump(), request_key(idempotency_key))


@router.post(PREFIX + '/vacancies/hh/sync')
def hh_sync(body: HHQuery, user=Depends(current_user), db=Depends(db_session), idempotency_key: str | None = Header(None)):
    payload = body.model_dump()
    if body.area is None and body.regions is None:
        payload['regions'] = user.profile.get('regions', ['Казахстан'])
    return submit_job(db, user.id, 'hh_sync', payload, request_key(idempotency_key))


@router.get(PREFIX + '/connections')
def connections(user=Depends(current_user), db=Depends(db_session)):
    last = db.scalar(select(Job).where(Job.owner_id == user.id, Job.kind == 'hh_sync').order_by(Job.created_at.desc()))
    return {'openai': bool(settings.openai_api_key), 'text_ai': text_available(),
        'text_provider': settings.text_provider, 'gemini_free_tier': settings.text_provider == 'gemini' and settings.gemini_free_tier,
        'audio': bool(settings.openai_api_key), 'embeddings': bool(settings.openai_api_key), 'hh': bool(settings.hh_access_token),
        'hh_last': {'status': last.status, 'error': last.error, 'created_at': last.created_at.isoformat()} if last else None}
