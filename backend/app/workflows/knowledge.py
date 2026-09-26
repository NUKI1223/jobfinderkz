from ..ports import TextPort, EmbeddingPort
import hashlib
from pathlib import Path
from sqlalchemy import select
from .. import ai, ingest
from ..config import settings
from ..db import Session, Record, Knowledge
from ..schemas import ExtractedQuestions
from ..revisions import fingerprint
from ..store import owned, shared, save_data



def import_source(job, *, sessions=Session):
    with sessions() as db:
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
    with sessions.begin() as db:
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


def extract_questions(job, *, sessions=Session, text: TextPort = ai):
    with sessions() as db:
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
        questions = text.structured(job.id, f'extract-{index}', 'Extract interview questions and discussions from timed transcript. '
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
        with sessions.begin() as db:
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


def import_material(job, *, sessions=Session):
    result = ai.checkpoint(job.id, 'page')
    if result is None:
        result = ingest.public_page(job.payload['url'])
        ai.save_checkpoint(job.id, 'page', result)
    key = fingerprint([result['url'], *(job.payload[k] for k in ('direction', 'level', 'language'))])
    with sessions.begin() as db:
        row = db.scalar(select(Record).where(Record.kind == 'material', Record.dedup_key == key, Record.owner_id.is_(None)))
        if not row:
            row = Record(kind='material', dedup_key=key, data={**job.payload, **result})
            db.add(row)
            db.flush()
        return {'record_id': row.id}


def index_knowledge(job, *, sessions=Session, embedding: EmbeddingPort = ai):
    snapshot = ai.checkpoint(job.id, 'index-input')
    if snapshot is None:
        # Legacy paid checkpoints have no provable association with a revision.
        if ai.checkpoint(job.id, 'embedding') is not None:
            raise ai.Uncertain('Сохранённый вектор не связан с версией материала; требуется проверка.')
        with sessions() as db:
            row = shared(db, job.payload['record_id'])
            index = db.get(Knowledge, row.id)
            version = row.data.get('version', 1)
            if row.status != 'published' or index is None or job.payload.get('version', version) != version:
                return {'record_id': row.id, 'skipped': 'revision_changed'}
            snapshot = {'version': version, 'text': index.text}
        ai.save_checkpoint(job.id, 'index-input', snapshot)
    embedding = embedding.embed(job.id, 'embedding', snapshot['text'])
    with sessions.begin() as db:
        row = owned(db, job.payload['record_id'], None, lock=True)
        index = db.get(Knowledge, row.id)
        if (row.status == 'published' and row.data.get('version', 1) == snapshot['version']
                and index is not None and index.text == snapshot['text']):
            index.embedding = embedding
        else:
            return {'record_id': row.id, 'skipped': 'revision_changed'}
    return {'record_id': row.id}
