"""Video-pack mechanics use synthetic intervals, never claim to validate audio."""
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.db import Job, Record, Session, Usage
from app.import_reviewed_bank import import_batch
from app.retrieval import evidence

ROOT = Path('/reviewed/videos_20260926')


def batches():
    return [json.loads((ROOT / f'{direction}_junior.json').read_text())
            for direction in ['frontend', 'python', 'qa']]


def test_video_packages_have_provenance_and_free_study_access(client, user):
    manifest = {s['video_id']: s for s in json.loads((ROOT / 'source_manifest.json').read_text())}
    assert len(manifest) == 5
    with Session.begin() as db:
        for batch in batches():
            source = manifest[batch['video_id']]
            assert source['selected_for_questions'] and source['method'] == 'youtube-auto'
            assert len(source['transcript_sha256']) == 64
            for q in batch['questions']:
                assert 0 <= q['start'] < q['end'] <= source['transcript_end_seconds']
            db.add(Record(kind='source', status='review', data={
                'video_id': batch['video_id'], 'transcript': {'segments': [
                    {'start': q['start'], 'end': q['end'], 'text': 'Synthetic interval fixture, not real speech'}
                    for q in batch['questions']]}}))
    for batch in batches():
        assert import_batch(batch)['new_questions'] == len(batch['questions'])
        assert import_batch(batch, apply=True)['new_questions'] == len(batch['questions'])
        assert import_batch(batch, apply=True)['new_questions'] == 0
    with Session() as db:
        rows = db.scalars(select(Record).where(Record.kind == 'question')).all()
        assert len(rows) == 9 and sum(bool(q.data['task']) for q in rows) == 6
        for q in rows:
            assert evidence(db, q.data) and q.data['source_kind'] == 'video'
            source = q.data['sources'][0]
            assert source['video_id'] in manifest and source['start'] < source['end']
            card = client.get(f'/api/v1/study/items/{q.id}').json()
            assert card['reference_answer'] == q.data['reference_answer']
            assert any(source['video_id'] in m['text'] and '&t=' in m['text'] for m in card['materials'])
            assert 'candidate_answer' not in card and 'interviewer_notes' not in card
            task = client.get(f'/api/v1/study/items/{q.id}?mode=task')
            assert task.status_code == (200 if q.data['task'] else 404)
        for batch in batches():
            response = client.get('/api/v1/study/items', params={
                'direction': batch['direction'], 'level': 'junior', 'language': 'ru'})
            assert response.status_code == 200 and response.json()['total'] == len(batch['questions'])
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Usage)) == 0


def test_reviewed_video_python_exercises():
    batch = next(b for b in batches() if b['direction'] == 'python')
    solutions = {}
    for q in batch['questions']:
        namespace = {}
        exec(compile(q['task_solution'], q['key'], 'exec'), namespace)
        solutions[q['key']] = namespace
    render = solutions['parameters']['render']
    assert render(3) == '3' and render('abc', 'x:', upper=True) == 'X:ABC'
    assert render(3, prefix='n=') == 'n=3'
    with pytest.raises(TypeError):
        render(value=3)
    with pytest.raises(TypeError):
        render(3, '', True)
    unpack = solutions['unpacking']
    assert unpack['result'] == 'left/right'
    with pytest.raises(TypeError):
        unpack['combine'](*unpack['values'], a='extra')
    assert solutions['logging-levels']['capture_levels']() == ['warning', 'error']
    assert solutions['logging-levels']['capture_levels']() == ['warning', 'error']
    squares = solutions['generator']['squares']
    gen = squares(3)
    assert iter(gen) is gen
    assert next(gen) == 0 and next(gen) == 1
    assert list(gen) == [4] and list(gen) == []
    with pytest.raises(StopIteration):
        next(gen)
    for n in range(-2, 20):
        assert list(squares(n)) == [i * i for i in range(n)]


def test_reviewed_video_second_distinct_date_sql():
    batch = next(b for b in batches() if b['direction'] == 'qa')
    query = next(q['task_solution'] for q in batch['questions'] if q['key'] == 'second-date')
    with Session.begin() as db:
        assert db.scalar(text('SELECT current_database()')) == 'jobfinder_test'
        db.execute(text('CREATE TEMP TABLE events(id integer PRIMARY KEY, modified bigint) ON COMMIT DROP'))
        assert db.scalars(text(query)).all() == []
        db.execute(text('INSERT INTO events VALUES (1,100),(2,100),(5,NULL)'))
        assert db.scalars(text(query)).all() == []
        db.execute(text('INSERT INTO events VALUES (3,90),(4,90)'))
        assert db.scalars(text(query)).all() == [3, 4]
        db.execute(text('INSERT INTO events VALUES (6,110)'))
        assert db.scalars(text(query)).all() == [1, 2]
