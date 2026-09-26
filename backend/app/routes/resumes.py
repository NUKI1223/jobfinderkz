from ..workflows.queue import submit_job
from pathlib import Path
from fastapi import Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse
from ..db import Record, now
from ..security import current_user, db_session
from ..schemas import CVFacts, CVText
from ..store import owned, save_data
from ..ingest import extract_cv
from ..cv_sections import section_draft

from fastapi import APIRouter
from ..http_common import PREFIX, request_key, public_record, upload

router = APIRouter()

@router.post(PREFIX + '/cv/text')
def cv_text(body: CVText, user=Depends(current_user), db=Depends(db_session)):
    row = Record(kind='cv', owner_id=user.id, status='review', data={'text': body.text, 'filename': 'Вставленный текст', **section_draft(body.text)})
    db.add(row)
    db.commit()
    return public_record(row)


@router.post(PREFIX + '/cv/upload')
async def cv_upload(file: UploadFile = File(...), user=Depends(current_user), db=Depends(db_session)):
    filename = Path(file.filename or 'CV').name
    path = await upload(file, user.id, {'.pdf', '.docx'}, 10_000_000, db)
    try:
        value = extract_cv(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise
        raise HTTPException(422, 'Не удалось прочитать документ. Проверьте PDF/DOCX или вставьте текст вручную.') from exc
    row = Record(kind='cv', owner_id=user.id, status='review', data={'text': value, 'file_path': str(path), 'filename': filename, **section_draft(value)})
    db.add(row)
    db.commit()
    return public_record(row)


@router.get(PREFIX + '/cv/{cv_id}/original')
def cv_original(cv_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, cv_id, user.id, 'cv')
    if not row.data.get('file_path'):
        raise HTTPException(404, 'Резюме добавлено текстом')
    return FileResponse(row.data['file_path'], filename=row.data['filename'])


@router.post(PREFIX + '/cv/{cv_id}/parse')
def cv_parse(cv_id: str, user=Depends(current_user), db=Depends(db_session), idempotency_key: str | None = Header(None)):
    row = owned(db, cv_id, user.id, 'cv')
    return submit_job(db, user.id, 'parse_cv', {'cv_id': row.id}, request_key(idempotency_key))


@router.put(PREFIX + '/cv/{cv_id}/confirm')
def cv_confirm(cv_id: str, body: CVFacts, user=Depends(current_user), db=Depends(db_session), if_match: str | None = Header(None)):
    row = owned(db, cv_id, user.id, 'cv', lock=True)
    if if_match is not None and if_match not in (str(row.data.get('version', 1)), row.updated_at.isoformat()):
        raise HTTPException(409, 'Резюме изменилось. Обновите страницу перед сохранением.')
    previous = row.data.get('facts')
    versions = row.data.get('versions', [])
    if previous:
        versions = versions + [{'facts': previous, 'saved_at': now().isoformat()}]
    save_data(row, facts=body.model_dump(), versions=versions, version=row.data.get('version', 1) + 1)
    row.status = 'confirmed'
    db.commit()
    return public_record(row)


@router.post(PREFIX + '/cv/{cv_id}/sections')
def cv_sections(cv_id: str, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, cv_id, user.id, 'cv', lock=True)
    versions = row.data.get('versions', [])
    if row.data.get('facts'):
        versions = versions + [{'facts': row.data['facts'], 'saved_at': now().isoformat()}]
    save_data(row, **section_draft(row.data['text']), versions=versions, version=row.data.get('version', 1) + 1)
    row.status = 'review'
    db.commit()
    return public_record(row)
