import hashlib
import json
import math
import shutil
from pathlib import Path
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from . import ai, ingest
from .config import settings
from .db import Session, Record, Job, Knowledge, Budget, now
from .schemas import CVFacts, Ranking, DocumentResult, ExtractedQuestions, Evaluation
from .store import owned, shared, save_data
from .retrieval import retrieve, evidence
from .hh import FORMAT_IDS, region_index, resolve_regions, work_formats


def result_record(job, kind, data, status='draft'):
    """Idempotent final output: one result record per job."""
    with Session.begin() as db:
        row = db.scalar(select(Record).where(Record.owner_id == job.owner_id, Record.kind == kind, Record.dedup_key == job.id))
        if not row:
            row = Record(owner_id=job.owner_id, kind=kind, dedup_key=job.id, data=data, status=status)
            db.add(row)
            db.flush()
        return {'record_id': row.id}


def parse_cv(job):
    with Session() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        text = cv.data['text']
    facts = ai.structured(job.id, 'parse', 'Extract only explicitly stated resume facts. Preserve exact factual wording. '
        'Return empty lists for missing sections. Remove contact details and personal identifiers.', {'cv': text}, CVFacts)
    with Session.begin() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        # Never overwrite a profile the user confirmed while the task ran.
        if cv.status != 'confirmed':
            save_data(cv, facts=facts.model_dump(), parse_method='ai', unassigned_text='')
            cv.status = 'review'
    return {'record_id': cv.id}


def rank(job):
    with Session() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        if cv.status != 'confirmed':
            raise ValueError('Сначала подтвердите профиль резюме')
        vacancies = [owned(db, rid, job.owner_id, 'vacancy') for rid in job.payload['vacancy_ids'][:20]]
        content = {'facts': cv.data['facts'], 'vacancies': [{'id': v.id, **v.data} for v in vacancies]}
    result = ai.structured(job.id, 'rank', 'Rank vacancies by confirmed facts only. Give reasons, matching skills and gaps in Russian. '
        'Include each supplied vacancy ID exactly once.', content, Ranking)
    if {m.vacancy_id for m in result.matches} != {v.id for v in vacancies} or len(result.matches) != len(vacancies):
        raise ValueError('Ранжирование содержит неверные идентификаторы')
    with Session.begin() as db:
        for match in result.matches:
            row = owned(db, match.vacancy_id, job.owner_id, 'vacancy')
            save_data(row, match=match.model_dump(), ranked_at=now().isoformat())
    return {'count': len(result.matches)}


def fact_catalog(facts):
    catalog = {}
    for field, values in facts.items():
        for index, value in enumerate(values if isinstance(values, list) else [values]):
            if value:
                catalog[f'{field}:{index}'] = value
    return catalog


def document(job):
    with Session() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        vacancy = owned(db, job.payload['vacancy_id'], job.owner_id, 'vacancy')
        if cv.status != 'confirmed':
            raise ValueError('Подтвердите профиль CV')
        catalog = fact_catalog(cv.data['facts'])
        payload = {**job.payload, 'facts': catalog, 'vacancy': vacancy.data}
    result = ai.structured(job.id, 'document', 'Select and order existing fact IDs relevant to the vacancy. '
        'Do not introduce any new skill, employer, achievement, duration or experience. '
        'Introduction and closing may express only interest in the role, no factual claims about candidate. '
        'Write in requested language. Explain structural changes.', payload, DocumentResult)
    if any(key not in catalog for key in result.selected_fact_ids):
        raise ValueError('Модель предложила неподтверждённый факт')
    # Candidate assertions are rendered from confirmed facts, never generated prose.
    en = job.payload['language'] == 'en'
    if job.payload['kind'] == 'cover_letter':
        intro = f"I would like to apply for {vacancy.data['title']}." if en else f"Хочу откликнуться на вакансию «{vacancy.data['title']}»."
        closing = 'I would welcome the opportunity to discuss the role.' if en else 'Буду рад обсудить задачи и ожидания на интервью.'
    else:
        intro, closing = ('Relevant experience' if en else 'Релевантный опыт'), ''
    rendered = '\n\n'.join([intro] + [catalog[key] for key in dict.fromkeys(result.selected_fact_ids)] + ([closing] if closing else []))
    return result_record(job, 'document', {**job.payload, 'title': result.title, 'text': rendered,
        'original_facts': catalog, 'selected_fact_ids': result.selected_fact_ids, 'changes': result.changes,
        'versions': [], 'language_note': 'Подтверждённые факты сохранены на исходном языке, чтобы не изменить их смысл.'})


def plan(job):
    with Session() as db:
        vacancy = owned(db, job.payload['vacancy_id'], job.owner_id, 'vacancy')
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        if cv.status != 'confirmed':
            raise ValueError('Подтвердите профиль CV')
        profile = job.payload['profile']
        query = vacancy.data['description'] + ' ' + ' '.join(vacancy.data.get('match', {}).get('missing_skills', []))
        vector = ai.embed(job.id, 'query-vector', query) if settings.openai_api_key else None
        rows = retrieve(db, query, profile['direction'], profile['level'], profile['language'], 40, vector)
        questions = [r for r in rows if r.kind == 'question']
        if not questions:
            raise ValueError('Нет опубликованных вопросов для выбранных направления, уровня и языка. Администратор должен проверить и опубликовать базу.')
        days = []
        for day in range(7):
            question = questions[day % len(questions)]
            q = question.data
            days.append({'day': day + 1, 'title': q['topic'], 'question_id': question.id, 'question': q['question'],
                'example': q['reference_answer'], 'task': q.get('task') or ('Объясните решение на собственном примере.' if profile['language'] == 'ru' else 'Explain using your own example.'),
                'materials': [{'id': m['id'], 'url': m['url']} for m in evidence(db, q)], 'done': False})
    return result_record(job, 'plan', {'vacancy_id': vacancy.id, 'days': days, 'profile': profile,
        'gaps': vacancy.data.get('match', {}).get('missing_skills', []), 'review': 'Дни 6–7 используйте для повторения и пробного интервью.'}, 'ready')


def evaluate(job):
    with Session() as db:
        session = owned(db, job.payload['interview_id'], job.owner_id, 'interview')
        index = job.payload['index']
        turn = session.data['turns'][index]
        if turn.get('evaluation'):
            return {'record_id': session.id}
        q = turn['question']
        materials = turn['materials']
    if not materials or not q.get('rubric'):
        evaluation = Evaluation(reliable=False, correctness=None, completeness=None, reasoning=None,
            feedback='Недостаточно проверенных оснований для надёжной оценки.', errors=[], missing_points=[], improved_answer='')
    else:
        evaluation = ai.structured(job.id, 'evaluate', 'Evaluate technical correctness, completeness and reasoning from 0 to 4. '
            'Accept correct paraphrases and alternative solutions. Ignore accent, pronunciation and style. '
            'Use only provided reviewed reference, rubric and materials. If evidence conflicts or is insufficient, '
            'set reliable=false and all scores=null. Explain errors, gaps, and a better example in interview language.',
            {'question': q, 'materials': materials, 'answer': job.payload['text'], 'language': session.data['language']}, Evaluation)
        if not evaluation.reliable:
            evaluation.correctness = evaluation.completeness = evaluation.reasoning = None
        elif any(x is None for x in [evaluation.correctness, evaluation.completeness, evaluation.reasoning]):
            raise ValueError('Неполная оценка модели')
    with Session.begin() as db:
        session = owned(db, session.id, job.owner_id, 'interview', lock=True)
        turns = list(session.data['turns'])
        turns[index] = {**turns[index], 'answer': job.payload['text'], 'evaluation': evaluation.model_dump(), 'evaluated_at': now().isoformat()}
        save_data(session, turns=turns)
        if all(t.get('evaluation') for t in turns):
            session.status = 'completed'
    return {'record_id': session.id}


def audio_answer(job):
    path = Path(job.payload['path'])
    directory = path.parent / job.id
    directory.mkdir(exist_ok=True)
    transcript = ai.checkpoint(job.id, 'transcript')
    if transcript is None:
        transcript = ingest.audio_transcript(job.id, path, directory, diarize=False)
        ai.save_checkpoint(job.id, 'transcript', transcript)
    path.unlink(missing_ok=True)
    shutil.rmtree(directory, ignore_errors=True)
    return {'text': ' '.join(p['text'] for p in transcript['segments']), 'requires_confirmation': True}


def import_source(job):
    with Session() as db:
        source = shared(db, job.payload['source_id'], 'source')
        data = source.data
    # A second administrator may have queued the same import before it finished.
    if (data.get('transcript') and not job.payload.get('path') and not job.payload.get('force_audio')
            and ai.checkpoint(job.id, 'transcript') is None):
        return {'record_id': source.id, 'segments': len(data['transcript']['segments'])}
    directory = settings.storage_path / 'sources' / source.id / job.id
    directory.mkdir(parents=True, exist_ok=True)
    transcript = ai.checkpoint(job.id, 'transcript')
    if transcript is None:
        if job.payload.get('path'):
            path = Path(job.payload['path'])
            if path.suffix in ('.txt', '.srt', '.vtt'):
                raw = path.read_text(encoding='utf-8-sig')
                if len(raw) > 1_000_000:
                    raise ValueError('Расшифровка превышает 1 000 000 символов')
                if path.suffix == '.txt':
                    if not data.get('duration_seconds'):
                        raise ValueError('Для TXT без таймкодов укажите длительность записи при добавлении источника')
                    ai.reserve_video(job.id, data['duration_seconds'])
                segments = ingest.subtitles(raw) if path.suffix != '.txt' else [{'start': 0, 'end': 0, 'speaker': None, 'text': raw}]
                if not segments:
                    raise ValueError('Не удалось прочитать субтитры')
                transcript = {'raw': raw, 'segments': segments, 'language': data['language'], 'method': 'manual' + path.suffix}
            else:
                transcript = ingest.audio_transcript(job.id, path, directory)
        else:
            transcript = ingest.fetch_youtube(data['video_id'], data['language'], directory, job.payload.get('force_audio', False))
            if transcript.get('audio_path'):
                transcript = ingest.audio_transcript(job.id, Path(transcript['audio_path']), directory)
        if not transcript['method'].startswith('manual.txt'):
            seconds = max((s['end'] for s in transcript['segments']), default=0)
            if seconds:
                ai.reserve_video(job.id, seconds)
        ai.save_checkpoint(job.id, 'transcript', transcript)
    with Session.begin() as db:
        source = shared(db, source.id, 'source')
        previous = source.data.get('transcript')
        history = source.data.get('transcript_versions', [])
        if previous and previous != transcript:
            history = history + [previous]
        save_data(source, transcript=transcript, transcript_versions=history)
        source.status = 'review'
    # Only remove media after transcript and source have been committed.
    for file in directory.iterdir():
        if file.is_file():
            file.unlink()
    if job.payload.get('path'):
        Path(job.payload['path']).unlink(missing_ok=True)
    return {'record_id': source.id, 'segments': len(transcript['segments'])}


def extract_questions(job):
    with Session() as db:
        source = shared(db, job.payload['source_id'], 'source')
        transcript = source.data.get('transcript')
        if not transcript:
            raise ValueError('Сначала получите расшифровку')
        data = source.data
    # Resume each paid window against the same input even if the source was edited.
    snapshot = ai.checkpoint(job.id, 'extraction-input')
    if snapshot is None:
        if any(key.startswith('extract-') for key in job.checkpoints):
            raise ai.Uncertain('Старое извлечение не содержит снимка входных данных; требуется проверка перед продолжением.')
        snapshot = {'transcript': transcript, 'data': {k: data[k] for k in ('video_id', 'direction', 'level', 'language')}}
        ai.save_checkpoint(job.id, 'extraction-input', snapshot)
    transcript, data = snapshot['transcript'], snapshot['data']
    # Bounded contextual windows with one segment overlap; dedup uses normalized question.
    windows, buffer, size = [], [], 0
    for segment in transcript['segments']:
        if size + len(segment['text']) > 16000 and buffer:
            windows.append(buffer)
            buffer = buffer[-1:]
            size = sum(len(s['text']) for s in buffer)
        buffer.append(segment)
        size += len(segment['text'])
    if buffer:
        windows.append(buffer)
    count = 0
    for index, window in enumerate(windows):
        questions = ai.structured(job.id, f'extract-{index}', 'Extract interview questions and discussions from timed transcript. '
            'Preserve candidate mistakes and uncertainty; never silently correct their answer or transcription. '
            'interviewer_notes must contain only remarks actually made by the interviewer, not your assessment. '
            'Use the supplied language for all prose. If transcription is ambiguous, mark needs_context=true. '
            'Separate candidate answers from interviewer corrections. Assign speaker roles only with contextual evidence, '
            'otherwise mark roles ambiguous. Never treat candidate answer as reference. '
            'Leave reference_answer, rubric, material_ids empty; administrator supplies verified documentation later. '
            'Set needs_context=true if visual task information is missing or context/roles ambiguous. '
            'Do not invent missing tasks. Keep supplied direction/language and estimate junior/middle level. '
            'Use source timestamps; never fabricate timing.', {'direction': data['direction'], 'level': data['level'],
                'language': data['language'], 'segments': window}, ExtractedQuestions)
        with Session.begin() as db:
            for q in questions.questions:
                q.reference_answer, q.rubric, q.material_ids = '', [], []
                if not q.roles.strip():
                    q.needs_context = True
                if q.end < q.start or q.start < window[0]['start'] or q.end > max(s['end'] for s in window) + 1:
                    q.needs_context = True
                    q.start, q.end = window[0]['start'], window[-1]['end']
                key = hashlib.sha256((source.id + q.question.strip().lower()).encode()).hexdigest()
                existing = db.scalar(select(Record).where(Record.kind == 'question', Record.dedup_key == key, Record.owner_id.is_(None)))
                if not existing:
                    row = Record(kind='question', dedup_key=key, data={**q.model_dump(), 'version': 1,
                        'sources': [{'source_id': source.id, 'video_id': data['video_id'], 'start': q.start, 'end': q.end}]})
                    db.add(row)
                    count += 1
    return {'record_id': source.id, 'created': count}


def import_material(job):
    result = ai.checkpoint(job.id, 'page')
    if result is None:
        result = ingest.public_page(job.payload['url'])
        ai.save_checkpoint(job.id, 'page', result)
    key = hashlib.sha256(result['url'].encode()).hexdigest()
    with Session.begin() as db:
        row = db.scalar(select(Record).where(Record.kind == 'material', Record.dedup_key == key, Record.owner_id.is_(None)))
        if not row:
            row = Record(kind='material', dedup_key=key, data={**job.payload, **result})
            db.add(row)
            db.flush()
        return {'record_id': row.id}


def index_knowledge(job):
    snapshot = ai.checkpoint(job.id, 'index-input')
    if snapshot is None:
        # Legacy paid checkpoints have no provable association with a revision.
        if ai.checkpoint(job.id, 'embedding') is not None:
            raise ai.Uncertain('Сохранённый вектор не связан с версией материала; требуется проверка.')
        with Session() as db:
            row = shared(db, job.payload['record_id'])
            index = db.get(Knowledge, row.id)
            version = row.data.get('version', 1)
            if row.status != 'published' or index is None or job.payload.get('version', version) != version:
                return {'record_id': row.id, 'skipped': 'revision_changed'}
            snapshot = {'version': version, 'text': index.text}
        ai.save_checkpoint(job.id, 'index-input', snapshot)
    embedding = ai.embed(job.id, 'embedding', snapshot['text'])
    with Session.begin() as db:
        row = owned(db, job.payload['record_id'], None, lock=True)
        index = db.get(Knowledge, row.id)
        if (row.status == 'published' and row.data.get('version', 1) == snapshot['version']
                and index is not None and index.text == snapshot['text']):
            index.embedding = embedding
        else:
            return {'record_id': row.id, 'skipped': 'revision_changed'}
    return {'record_id': row.id}


def hh_sync(job):
    if not settings.hh_access_token:
        raise ai.Paused('HeadHunter не подключён: добавьте HH_ACCESS_TOKEN и HH_USER_AGENT в .env')
    params = {'text': job.payload['text'], 'per_page': 20,
              'experience': 'noExperience' if job.payload['level'] == 'junior' else 'between1And3'}
    if job.payload['work_format'] in FORMAT_IDS:
        params['work_format'] = FORMAT_IDS[job.payload['work_format']]
    saved = ai.checkpoint(job.id, 'hh')
    area_snapshot = ai.checkpoint(job.id, 'hh-areas')
    if saved is None:
        with httpx.Client(timeout=30, headers={'Authorization': f'Bearer {settings.hh_access_token}', 'HH-User-Agent': settings.hh_user_agent}) as client:
            if area_snapshot is None:
                response = client.get('https://api.hh.ru/areas')
                if response.status_code != 200:
                    raise ValueError(f'Справочник HeadHunter недоступен (HTTP {response.status_code})')
                by_name, by_id = region_index(response.json())
                areas = [job.payload['area']] if job.payload.get('area') else resolve_regions(job.payload.get('regions') or [], by_name)
                area_snapshot = {'ids': areas, 'regions': by_id}
                ai.save_checkpoint(job.id, 'hh-areas', area_snapshot)
            if area_snapshot['ids']:
                params['area'] = area_snapshot['ids']
            listings = ai.checkpoint(job.id, 'hh-list')
            if listings is None:
                response = client.get('https://api.hh.ru/vacancies', params=params)
                if response.status_code != 200:
                    raise ValueError(f'HeadHunter недоступен (HTTP {response.status_code}); сохранённые вакансии остаются доступны')
                listings = response.json().get('items', [])[:20]
                ai.save_checkpoint(job.id, 'hh-list', listings)
            saved = []
            for item in listings:
                rid = str(item['id'])
                if not rid.isdigit():
                    continue
                detail = ai.checkpoint(job.id, 'hh-detail:' + rid)
                if detail is None:
                    response = client.get(f'https://api.hh.ru/vacancies/{rid}')
                    if response.status_code in (404, 410):
                        detail = {'unavailable': True}
                    elif response.status_code == 200:
                        detail = response.json()
                    else:
                        raise ValueError(f'Не удалось получить вакансию HeadHunter (HTTP {response.status_code}); полученные этапы сохранены')
                    ai.save_checkpoint(job.id, 'hh-detail:' + rid, detail)
                if not detail.get('unavailable') and not detail.get('archived'):
                    saved.append(detail)
        ai.save_checkpoint(job.id, 'hh', saved)
    count = 0
    with Session.begin() as db:
        for item in saved:
            key = 'hh:' + str(item['id'])
            row = db.scalar(select(Record).where(Record.owner_id == job.owner_id, Record.kind == 'vacancy', Record.dedup_key == key))
            formats = work_formats(item)
            data = {
                'title': item['name'], 'company': (item.get('employer') or {}).get('name', ''),
                'description': ingest.BeautifulSoup(item['description'], 'html.parser').get_text(' ', strip=True),
                'url': item['alternate_url'], 'region': item['area']['name'], 'direction': job.payload['direction'],
                'region_parents': ((area_snapshot or {}).get('regions', {}).get(str(item['area']['id']), {})).get('parents', []),
                'level': job.payload['level'], 'work_format': formats[0] if formats else 'any', 'work_formats': formats,
                'source': 'hh', 'fetched_at': now().isoformat(), 'favorite': row.data.get('favorite', False) if row else False}
            if row:
                old = row.data
                if all(old.get(k) == data.get(k) for k in ('title', 'description', 'direction', 'level')):
                    for field in ('match', 'ranked_at'):
                        if field in old:
                            data[field] = old[field]
                row.data = data
            else:
                db.add(Record(kind='vacancy', owner_id=job.owner_id, dedup_key=key, status='saved', data=data))
            count += 1
    return {'count': count, 'synced_at': now().isoformat()}


HANDLERS = {'parse_cv': parse_cv, 'rank': rank, 'document': document, 'plan': plan, 'evaluate': evaluate,
    'audio_answer': audio_answer, 'import_source': import_source, 'extract_questions': extract_questions,
    'import_material': import_material, 'index_knowledge': index_knowledge, 'hh_sync': hh_sync}
