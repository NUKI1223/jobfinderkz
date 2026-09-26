from ..workflows.queue import submit_job
from collections import defaultdict
from fastapi import Depends, HTTPException, UploadFile, File, Header
from sqlalchemy import select
from ..config import settings
from ..db import Record, Knowledge
from ..security import current_user, db_session
from ..schemas import AnswerInput, Direction, InterviewInput, Language, Level, Strict
from ..store import owned, save_data
from ..retrieval import retrieve, evidence, practiced_questions, prioritize_questions, lexical_relevant
from ..audio import enqueue_audio
from ..answers import submit_answer

from fastapi import APIRouter
from ..http_common import PREFIX, request_key, public_record, upload

router = APIRouter()

class PlanRequest(Strict):
    vacancy_id: str
    cv_id: str


@router.post(PREFIX + '/plans')
def plan_create(body: PlanRequest, user=Depends(current_user), db=Depends(db_session), idempotency_key: str | None = Header(None)):
    owned(db, body.cv_id, user.id, 'cv')
    owned(db, body.vacancy_id, user.id, 'vacancy')
    return submit_job(db, user.id, 'plan', {**body.model_dump(), 'profile': user.profile}, request_key(idempotency_key))


@router.post(PREFIX + '/plans/{plan_id}/days/{day}')
def plan_done(plan_id: str, day: int, user=Depends(current_user), db=Depends(db_session)):
    row = owned(db, plan_id, user.id, 'plan', lock=True)
    if not 1 <= day <= 7:
        raise HTTPException(422, 'День должен быть от 1 до 7')
    days = list(row.data['days'])
    days[day - 1] = {**days[day - 1], 'done': not days[day - 1]['done']}
    save_data(row, days=days)
    db.commit()
    return public_record(row)


@router.post(PREFIX + '/interviews')
def interview_create(body: InterviewInput, user=Depends(current_user), db=Depends(db_session)):
    vacancy = owned(db, body.vacancy_id, user.id, 'vacancy')
    query = vacancy.data.get('title', '') + ' ' + vacancy.data['description']
    rows = retrieve(db, query, body.direction, body.level, body.language, 100, kind='question')
    questions = prioritize_questions(rows, practiced_questions(db, user.id))[:5]
    if len(questions) < 5:
        raise HTTPException(409, 'Для интервью нужны 5 опубликованных вопросов выбранного направления, уровня и языка')
    turns = [{'question_id': q.id, 'fallback': not lexical_relevant(db, q, query), 'question': q.data, 'rubric_version': q.data['version'],
              'materials': evidence(db, q.data), 'answer': '', 'evaluation': None} for q in questions]
    row = Record(kind='interview', owner_id=user.id, status='active', data={**body.model_dump(), 'turns': turns})
    db.add(row)
    db.commit()
    return public_record(row)


@router.get(PREFIX + '/knowledge/availability')
def knowledge_availability(user=Depends(current_user), db=Depends(db_session)):
    rows = db.scalars(select(Record).join(Knowledge, Knowledge.record_id == Record.id)
        .where(Record.kind == 'question', Record.status == 'published')).all()
    groups = []
    for direction in ('frontend', 'python', 'qa'):
        for level in ('junior', 'middle'):
            for language in ('ru', 'en'):
                count = sum(1 for row in rows if evidence(db, row.data) and all(row.data.get(k) == v for k, v in
                    [('direction', direction), ('level', level), ('language', language)]))
                groups.append({'direction': direction, 'level': level, 'language': language,
                    'questions': count, 'interview_ready': count >= 5, 'missing': max(0, 5-count)})
    return groups


@router.post(PREFIX + '/interviews/{interview_id}/answers/{index}')
def answer(interview_id: str, index: int, body: AnswerInput, user=Depends(current_user), db=Depends(db_session)):
    return submit_answer(db, user.id, interview_id, index, body.text)


@router.post(PREFIX + '/interviews/{interview_id}/audio')
async def answer_audio(interview_id: str, index: int = 0, file: UploadFile = File(...),
                       idempotency_key: str | None = Header(None), user=Depends(current_user), db=Depends(db_session)):
    owned(db, interview_id, user.id, 'interview')
    if not settings.openai_api_key:
        raise HTTPException(409, 'Распознавание голоса не подключено. Введите ответ текстом.')
    if idempotency_key:
        request_key(idempotency_key)
    path = await upload(file, user.id, {'.webm', '.mp3', '.mp4', '.m4a', '.wav', '.ogg'}, 15_000_000, db)
    try:
        return enqueue_audio(db, user.id, interview_id, index, path, idempotency_key)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@router.get(PREFIX + '/stats')
def statistics(direction: Direction = 'frontend', level: Level = 'junior', language: Language = 'ru', user=Depends(current_user), db=Depends(db_session)):
    rows = db.scalars(select(Record).where(Record.owner_id == user.id, Record.kind == 'interview').order_by(Record.created_at)).all()
    timeline, topics, errors = [], defaultdict(list), defaultdict(int)
    for row in rows:
        if row.data['direction'] != direction or row.data['level'] != level or row.data.get('language') != language:
            continue
        scores = []
        for turn in row.data['turns']:
            evaluation = turn.get('evaluation')
            if not evaluation or not evaluation['reliable']:
                continue
            score = sum(evaluation[k] for k in ('correctness', 'completeness', 'reasoning')) / 3
            scores.append(score)
            topics[turn['question']['topic']].append(score)
            for error in evaluation['errors']:
                errors[error] += 1
        if scores:
            timeline.append({'id': row.id, 'date': row.created_at.isoformat(), 'score': round(sum(scores) / len(scores), 2), 'answers': len(scores)})
    return {'timeline': timeline, 'topics': [{'topic': k, 'score': round(sum(v) / len(v), 2), 'answers': len(v)} for k, v in topics.items()],
            'errors': sorted([{'error': k, 'count': v} for k, v in errors.items()], key=lambda e: -e['count'])}
