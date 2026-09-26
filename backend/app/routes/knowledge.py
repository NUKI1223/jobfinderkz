from ..workflows.queue import submit_job
import hashlib
from fastapi import Depends, HTTPException, UploadFile, File, Header
from sqlalchemy import select, text, delete
from ..config import settings
from ..db import Record, Knowledge, uid, now
from ..security import admin, db_session
from ..schemas import EditText, MaterialInput, QuestionInput, SourceInput
from ..store import owned, shared, record_dict, save_data
from ..ingest import youtube_id
from ..retrieval import evidence

from fastapi import APIRouter
from ..http_common import PREFIX, request_key, upload, json_key

router = APIRouter()

@router.post(PREFIX + '/admin/knowledge/reindex')
def knowledge_reindex(user=Depends(admin), db=Depends(db_session)):
    if not settings.openai_api_key:
        raise HTTPException(409, 'Для индексации добавьте OPENAI_API_KEY')
    rows = db.scalars(select(Record).join(Knowledge, Knowledge.record_id == Record.id)
        .where(Record.status == 'published', Knowledge.embedding.is_(None))).all()
    return {'jobs': [submit_job(db, user.id, 'index_knowledge', {'record_id': row.id, 'version': row.data.get('version', 1)},
        f'index:{row.id}:{row.data.get("version", 1)}:v2') for row in rows]}


@router.get(PREFIX + '/admin/{kind}')
def admin_list(kind: str, user=Depends(admin), db=Depends(db_session)):
    if kind not in ('source', 'question', 'material'):
        raise HTTPException(404)
    return [record_dict(r) for r in db.scalars(select(Record).where(Record.owner_id.is_(None), Record.kind == kind).order_by(Record.created_at.desc()))]


@router.post(PREFIX + '/admin/sources')
def source_create(body: SourceInput, user=Depends(admin), db=Depends(db_session)):
    video = youtube_id(body.url)
    row = db.scalar(select(Record).where(Record.kind == 'source', Record.owner_id.is_(None), Record.dedup_key == video))
    if row:
        if body.duration_seconds and not row.data.get('duration_seconds'):
            save_data(row, duration_seconds=body.duration_seconds)
            db.commit()
        return record_dict(row)
    row = Record(kind='source', dedup_key=video, data={**body.model_dump(), 'url': f'https://www.youtube.com/watch?v={video}', 'video_id': video})
    db.add(row)
    db.commit()
    return record_dict(row)


@router.post(PREFIX + '/admin/sources/{source_id}/import')
def source_import(source_id: str, force_audio: bool = False, user=Depends(admin), db=Depends(db_session)):
    source = shared(db, source_id, 'source')
    if source.data.get('transcript') and not force_audio:
        return {'record_id': source.id, 'message': 'Расшифровка уже сохранена'}
    return submit_job(db, user.id, 'import_source', {'source_id': source_id, 'force_audio': force_audio}, f'import:{source_id}:{force_audio}')


@router.post(PREFIX + '/admin/sources/{source_id}/upload')
async def source_upload(source_id: str, file: UploadFile = File(...), user=Depends(admin), db=Depends(db_session)):
    shared(db, source_id, 'source')
    path = await upload(file, user.id, {'.txt', '.srt', '.vtt', '.webm', '.mp3', '.mp4', '.m4a', '.wav', '.ogg'}, 150_000_000, db)
    return submit_job(db, user.id, 'import_source', {'source_id': source_id, 'path': str(path)}, uid())


@router.post(PREFIX + '/admin/sources/{source_id}/extract')
def source_extract(source_id: str, user=Depends(admin), db=Depends(db_session)):
    row = shared(db, source_id, 'source')
    version = hashlib.sha256(str(row.data.get('transcript')).encode()).hexdigest()[:16]
    return submit_job(db, user.id, 'extract_questions', {'source_id': source_id}, f'extract:{source_id}:{version}')


@router.post(PREFIX + '/admin/materials')
def material_create(body: MaterialInput, user=Depends(admin), db=Depends(db_session), idempotency_key: str | None = Header(None)):
    return submit_job(db, user.id, 'import_material', body.model_dump(), request_key(idempotency_key))


@router.post(PREFIX + '/admin/questions')
def question_create(body: QuestionInput, user=Depends(admin), db=Depends(db_session)):
    row = Record(kind='question', data={**body.model_dump(), 'sources': [], 'version': 1})
    db.add(row)
    db.commit()
    return record_dict(row)


@router.put(PREFIX + '/admin/questions/{question_id}')
def question_edit(question_id: str, body: QuestionInput, user=Depends(admin), db=Depends(db_session), if_match: str | None = Header(None)):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
    row = owned(db, question_id, None, 'question', lock=True)
    if if_match is not None and if_match != row.updated_at.isoformat():
        raise HTTPException(409, 'Объект изменён. Обновите данные перед сохранением.')
    before = {k: v for k, v in row.data.items() if k != 'history'}
    row.data = {**row.data, **body.model_dump(exclude_unset=True), 'version': row.data.get('version', 1) + 1,
                'history': row.data.get('history', []) + [before]}
    if len(row.data.get('sources', [])) == 1:
        row.data = {**row.data, 'sources': [{**row.data['sources'][0], 'start': body.start, 'end': body.end}]}
    for translation in db.scalars(select(Record).where(Record.kind == 'question',
            Record.data['translation_of'].as_string() == row.id).with_for_update()):
        translation.status = 'draft'
        db.execute(delete(Knowledge).where(Knowledge.record_id == translation.id))
    row.status = 'draft'
    db.execute(delete(Knowledge).where(Knowledge.record_id == row.id))
    db.commit()
    return record_dict(row)


@router.put(PREFIX + '/admin/materials/{material_id}')
def material_edit(material_id: str, body: EditText, user=Depends(admin), db=Depends(db_session), if_match: str | None = Header(None)):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
    row = owned(db, material_id, None, 'material', lock=True)
    if if_match is not None and if_match != row.updated_at.isoformat():
        raise HTTPException(409, 'Объект изменён. Обновите данные перед сохранением.')
    save_data(row, text=body.text, version=row.data.get('version', 1) + 1)
    for question in db.scalars(select(Record).where(Record.kind == 'question', Record.status == 'published').order_by(Record.id).with_for_update()):
        if row.id in question.data.get('material_ids', []):
            question.status = 'draft'
            db.execute(delete(Knowledge).where(Knowledge.record_id == question.id))
    row.status = 'draft'
    db.execute(delete(Knowledge).where(Knowledge.record_id == row.id))
    db.commit()
    return record_dict(row)


@router.post(PREFIX + '/admin/questions/{question_id}/merge/{other_id}')
def merge_questions(question_id: str, other_id: str, other_version: str | None = None, user=Depends(admin), db=Depends(db_session), if_match: str | None = Header(None)):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
    if question_id == other_id:
        raise HTTPException(422)
    locked = {rid: owned(db, rid, None, 'question', lock=True) for rid in sorted([question_id, other_id])}
    target, other = locked[question_id], locked[other_id]
    if (if_match is not None and if_match != target.updated_at.isoformat()) or (other_version is not None and other_version != other.updated_at.isoformat()) or other.status == 'merged':
        raise HTTPException(409, 'Карточки изменились. Проверьте обе версии перед объединением.')
    sources = target.data.get('sources', []) + other.data.get('sources', [])
    unique = list({json_key(s): s for s in sources}.values())
    save_data(target, sources=unique, version=target.data.get('version', 1) + 1,
              merged_discussions=target.data.get('merged_discussions', []) + [other.data])
    target.status, other.status = 'draft', 'merged'
    db.execute(delete(Knowledge).where(Knowledge.record_id.in_([target.id, other.id])))
    db.commit()
    return record_dict(target)


@router.post(PREFIX + '/admin/publish/{record_id}')
def publish(record_id: str, user=Depends(admin), db=Depends(db_session)):
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
    row = owned(db, record_id, None, lock=True)
    if row.kind not in ('question', 'material'):
        raise HTTPException(422)
    data = row.data
    if row.kind == 'question':
        q = QuestionInput.model_validate({k: v for k, v in data.items() if k in QuestionInput.model_fields})
        if q.translation_of:
            original = shared(db, q.translation_of, 'question')
            if original.id == row.id or original.status != 'published' or original.data.get('translation_of'):
                raise HTTPException(422, 'Перевод должен ссылаться на опубликованный исходный вопрос')
            if original.data['direction'] != q.direction or original.data['level'] != q.level or original.data['language'] == q.language:
                raise HTTPException(422, 'Направление, уровень и язык перевода не совпадают с оригиналом')
            duplicate = db.scalar(select(Record).where(Record.kind == 'question', Record.status == 'published',
                Record.id != row.id, Record.data['translation_of'].as_string() == original.id,
                Record.data['language'].as_string() == q.language))
            if duplicate:
                raise HTTPException(409, 'Перевод этого вопроса на выбранный язык уже опубликован')
            save_data(row, translation_version=original.data.get('version', 1))
            data = row.data
            if not data.get('sources'):
                row.data = {**data, 'sources': original.data.get('sources', []), 'source_language': original.data['language']}
                if len(row.data.get('sources', [])) == 1:
                    save_data(row, start=row.data['sources'][0]['start'], end=row.data['sources'][0]['end'])
                data = row.data
        if q.needs_context or len(q.reference_answer) < 30 or len(q.rubric) < 3 or not q.material_ids:
            raise HTTPException(422, 'Для публикации дополните контекст, эталон, минимум 3 критерия и проверенные материалы')
        for material_id in q.material_ids:
            if shared(db, material_id, 'material').status != 'published':
                raise HTTPException(422, 'Сначала проверьте и опубликуйте материалы')
        if any(s.get('end', 0) <= s.get('start', 0) for s in data.get('sources', [])):
            raise HTTPException(422, 'Укажите точные таймкоды исходного обсуждения')
        content = q.question + '\n' + q.reference_answer + '\n' + ' '.join(q.rubric)
    else:
        content = data['text']
    if row.kind == 'question':
        save_data(row, material_versions={m['id']: m['version'] for m in evidence(db, {**row.data, 'material_versions': {}})})
    row.status = 'published'
    save_data(row, reviewed_at=now().isoformat(), version=data.get('version', 1))
    index = db.get(Knowledge, row.id)
    if index and index.text != content:
        db.delete(index)
        db.flush()
        index = None
    if index is None:
        db.add(Knowledge(record_id=row.id, text=content, direction=data['direction'], level=data['level'], language=data['language']))
    db.commit()
    indexing = submit_job(db, user.id, 'index_knowledge', {'record_id': row.id, 'version': row.data['version']}, f'index:{row.id}:{row.data["version"]}:v2') if settings.openai_api_key else None
    return {'record': record_dict(row), 'indexing': indexing}
