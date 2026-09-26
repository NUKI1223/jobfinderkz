"""Free, owner-scoped self-study; never invokes providers or queues."""
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field
from sqlalchemy import select, text
from ..db import Record
from ..security import current_user, db_session
from ..schemas import Strict, Direction, Level, Language
from ..retrieval import evidence, canonical
from ..revisions import fingerprint
from ..store import shared, save_data
from ..http_common import PREFIX

router = APIRouter(prefix=PREFIX + '/study')
Mode = Literal['question', 'task']
Status = Literal['new', 'repeat', 'done']

class Draft(Strict):
    answer: str = ''
    content_version: str

class Progress(Strict):
    revision: str = 'new'
    status: Status = 'new'
    updated: bool = False
    answer: str = ''
    history: list[Draft] = Field(default_factory=list)

class Item(Strict):
    id: str
    question: str
    topic: str
    direction: Direction
    level: Level
    language: Language
    status: Status
    updated: bool

class Catalog(Strict):
    items: list[Item]
    total: int
    done: int
    repeat: int
    topics: list[str]
    next_offset: int | None

class Material(Strict):
    id: str
    version: int
    url: str
    text: str

class Card(Strict):
    item: Item
    content_version: str
    task: str
    task_solution: str
    reference_answer: str
    rubric: list[str]
    materials: list[Material]
    progress: Progress

class SaveProgress(Strict):
    answer: str = Field(max_length=50000)
    status: Status
    content_version: str = Field(min_length=64, max_length=64)


def available(db, row, mode):
    return row.status == 'published' and bool(evidence(db, row.data)) and (mode == 'question' or bool(row.data.get('task', '').strip()))


def version(db, row):
    # A shared RU/EN mark is current only for the entire canonical family.
    root = canonical(row)
    family = db.scalars(select(Record).where(Record.kind == 'question', Record.owner_id.is_(None),
        (Record.id == root) | (Record.data['translation_of'].as_string() == root)).order_by(Record.id)).all()
    return fingerprint([{'id': q.id, 'content': {k: q.data.get(k) for k in
        ('version', 'question', 'task', 'task_solution', 'reference_answer', 'rubric', 'material_ids', 'material_versions')},
        'materials': sorted(evidence(db, q.data), key=lambda m: m['id'])} for q in family])


def progress_row(db, owner, row, mode):
    return db.scalar(select(Record).where(Record.owner_id == owner, Record.kind == 'study_progress',
        Record.dedup_key == canonical(row) + ':' + mode))


def progress(row, language, content_version):
    data = row.data if row else {}
    draft = data.get('drafts', {}).get(language, {})
    updated = bool(data.get('content_version') and data['content_version'] != content_version)
    return Progress(revision=row.updated_at.isoformat() if row else 'new',
        status='new' if updated else data.get('status', 'new'), updated=updated,
        answer=draft.get('answer', ''), history=data.get('history', {}).get(language, []))


def item(row, p):
    return Item(id=row.id, **{k: row.data[k] for k in ('question', 'topic', 'direction', 'level', 'language')},
        status=p.status, updated=p.updated)


def card(db, row, mode, owner):
    v = version(db, row)
    p = progress(progress_row(db, owner, row, mode), row.data['language'], v)
    return Card(item=item(row, p), content_version=v, progress=p, materials=evidence(db, row.data),
        **{k: row.data.get(k, '') for k in ('task', 'task_solution', 'reference_answer')}, rubric=row.data.get('rubric', []))


@router.get('/items', response_model=Catalog)
def catalog(mode: Mode = 'question', direction: Direction | None = None, level: Level | None = None,
            language: Language | None = None, topic: str = Query('', max_length=150),
            search: str = Query('', max_length=300), status: Status | None = None,
            offset: int = Query(0, ge=0), user=Depends(current_user), db=Depends(db_session)):
    rows = db.scalars(select(Record).where(Record.kind == 'question', Record.owner_id.is_(None),
        Record.status == 'published').order_by(Record.created_at, Record.id)).all()
    items = []
    for row in rows:
        if any(value and row.data.get(key) != value for key, value in
               [('direction', direction), ('level', level), ('language', language)]):
            continue
        if not available(db, row, mode):
            continue
        p = progress(progress_row(db, user.id, row, mode), row.data['language'], version(db, row))
        items.append(item(row, p))
    topics = sorted({i.topic for i in items})
    items = [i for i in items if (not topic or i.topic == topic) and
             (not search or search.casefold() in (i.question + ' ' + i.topic).casefold())]
    done, repeat = sum(i.status == 'done' for i in items), sum(i.status == 'repeat' for i in items)
    items = [i for i in items if not status or i.status == status]
    total = len(items)
    return Catalog(items=items[offset:offset+20], total=total, done=done, repeat=repeat, topics=topics,
                   next_offset=offset+20 if offset+20 < total else None)


@router.get('/items/{item_id}', response_model=Card)
def detail(item_id: str, mode: Mode = 'question', user=Depends(current_user), db=Depends(db_session)):
    row = shared(db, item_id, 'question')
    if not available(db, row, mode):
        raise HTTPException(404, 'Опубликованный материал недоступен')
    return card(db, row, mode, user.id)


@router.put('/items/{item_id}/progress', response_model=Card)
def save(item_id: str, body: SaveProgress, mode: Mode = 'question', if_match: str | None = Header(None),
         user=Depends(current_user), db=Depends(db_session)):
    # Same lock as publication, plus owner/key lock for concurrent first saves.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
    row = shared(db, item_id, 'question')
    if not available(db, row, mode):
        raise HTTPException(409, 'Материал изменён или снят с публикации. Ответ не сохранён.')
    v = version(db, row)
    key = canonical(row) + ':' + mode
    db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': user.id + key})
    saved = progress_row(db, user.id, row, mode)
    if if_match != (saved.updated_at.isoformat() if saved else 'new') or body.content_version != v:
        raise HTTPException(409, 'Материал или прогресс изменён. Скопируйте свой ответ и откройте карточку заново.')
    if saved is None:
        saved = Record(owner_id=user.id, kind='study_progress', dedup_key=key, data={})
        db.add(saved)
    drafts = dict(saved.data.get('drafts', {}))
    history = dict(saved.data.get('history', {}))
    lang = row.data['language']
    old = drafts.get(lang)
    if old and old['content_version'] != v:
        history[lang] = history.get(lang, []) + [old]
    drafts[lang] = {'answer': body.answer, 'content_version': v}
    save_data(saved, drafts=drafts, history=history, content_version=v, status=body.status)
    db.commit()
    return card(db, row, mode, user.id)
