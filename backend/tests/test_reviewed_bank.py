from sqlalchemy import select

from app.db import Knowledge, Record, Session
from app.import_reviewed_bank import import_batch


def test_reviewed_batch_is_additive_and_idempotent():
    with Session.begin() as db:
        db.add(Record(kind='source', status='review', data={'video_id': 'review-fixture',
            'transcript': {'segments': [{'start': 10, 'end': 35, 'text': 'Question and answer'}]}}))
    batch = {'batch': 'reviewed-test', 'video_id': 'review-fixture', 'direction': 'python',
        'level': 'junior', 'language': 'ru', 'materials': [{
            'key': 'manual', 'url': 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Methods/PUT',
            'title': 'PUT', 'text': 'A documented representation replacement with idempotent request semantics.',
            'review_note': 'Checked in fixture'}], 'questions': [{
            'key': 'method', 'question': 'What does a PUT request do?', 'topic': 'HTTP',
            'start': 10, 'end': 30, 'roles': 'Interviewer asks and candidate answers.',
            'reference_answer': 'PUT creates or replaces a representation of the target resource.',
            'rubric': ['Describes target resource', 'Describes replacement', 'Describes repeat semantics'],
            'material_keys': ['manual'], 'review_note': 'Checked source interval'}]}
    assert import_batch(batch) == {'batch': 'reviewed-test', 'applied': False,
        'new_materials': 1, 'new_questions': 1, 'source_video': 'review-fixture'}
    with Session() as db:
        assert db.scalars(select(Record).where(Record.kind == 'question')).all() == []
    assert import_batch(batch, apply=True)['new_questions'] == 1
    assert import_batch(batch, apply=True)['new_questions'] == 0
    with Session() as db:
        rows = db.scalars(select(Record).where(Record.kind.in_(['material', 'question']))).all()
        assert len(rows) == 2
        assert all(row.status == 'published' and db.get(Knowledge, row.id) for row in rows)
        question = next(row for row in rows if row.kind == 'question')
        assert question.data['material_ids'] == [next(row.id for row in rows if row.kind == 'material')]


def test_reviewed_batch_rejects_missing_evidence():
    with Session.begin() as db:
        db.add(Record(kind='source', data={'video_id': 'review-fixture',
            'transcript': {'segments': [{'start': 10, 'end': 20, 'text': 'A'}]}}))
    batch = {'batch': 'reviewed-test', 'video_id': 'review-fixture', 'direction': 'python',
        'level': 'junior', 'language': 'ru', 'materials': [{
            'key': 'manual', 'url': 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Methods/PUT',
            'title': 'PUT', 'text': 'A documented representation replacement with idempotent request semantics.',
            'review_note': 'Checked in fixture'}], 'questions': [{
            'key': 'method', 'question': 'What does a PUT request do?', 'topic': 'HTTP',
            'start': 30, 'end': 40, 'roles': 'Interviewer asks and candidate answers.',
            'reference_answer': 'PUT creates or replaces a representation of the target resource.',
            'rubric': ['Describes target resource', 'Describes replacement', 'Describes repeat semantics'],
            'material_keys': ['manual'], 'review_note': 'Checked source interval'}]}
    import pytest
    with pytest.raises(ValueError, match='Invalid source interval'):
        import_batch(batch, apply=True)
    with Session() as db:
        assert db.scalars(select(Record).where(Record.kind.in_(['material', 'question']))).all() == []


def test_documentation_batch_validates_provenance_and_freezes_import():
    import copy
    import pytest
    from app.retrieval import evidence
    batch = {'batch': 'reviewed-doc-test', 'source_kind': 'documentation', 'review_method': 'Official documentation review',
        'direction': 'frontend', 'level': 'junior', 'language': 'ru',
        'materials': [{'key': 'button', 'url': 'https://developer.mozilla.org/en-US/docs/Web/HTML/Element/button',
            'title': 'Button', 'text': 'A native button provides keyboard activation and focus behavior.', 'review_note': 'Fixture review'}],
        'questions': [{'key': 'button', 'question': 'Why use a native button?', 'topic': 'HTML',
            'reference_answer': 'A native button exposes semantic role and standard keyboard interaction.',
            'rubric': ['Role', 'Keyboard', 'Focus'], 'roles': 'Documentation exercise',
            'review_note': 'Official reference', 'material_keys': ['button'],
            'task': 'Write a non-submit button', 'task_solution': '<button type="button">Open</button>'}]}
    bad=copy.deepcopy(batch);bad['questions'][0]['candidate_answer']='Invented interview'
    with pytest.raises(ValueError, match='invent video'):
        import_batch(bad,apply=True)
    with Session() as db:
        assert not db.scalars(select(Record).where(Record.kind=='material')).all()
    assert import_batch(batch)['new_questions']==1
    assert import_batch(batch,apply=True)['new_questions']==1
    assert import_batch(batch,apply=True)['new_questions']==0
    changed=copy.deepcopy(batch);changed['questions'][0]['task_solution']='Another solution'
    with pytest.raises(ValueError, match='content changed'):
        import_batch(changed,apply=True)
    with Session() as db:
        q=db.scalar(select(Record).where(Record.kind=='question'))
        assert q.data['sources']==[] and q.data['candidate_answer']==''
        assert q.data['task_solution'] and evidence(db,q.data)


def test_expansion_packages_import_retrieve_and_study(client,user):
    import json
    from pathlib import Path
    from app.retrieval import evidence, retrieve
    from app.db import Job, Usage
    from sqlalchemy import func
    paths=sorted(Path('/reviewed/expansion_20260926').glob('*.json'))
    batches=[json.loads(p.read_text()) for p in paths if p.name!='source_manifest.json']
    assert len(batches)==8
    # Synthetic transcript intervals validate importer mechanics, not audio quality.
    with Session.begin() as db:
        db.add(Record(kind='source',data={'video_id':'UYmA6p7UwOo','transcript':{'segments':[
            {'start':q['start'],'end':q['end'],'text':'Synthetic source fixture'}
            for b in batches if b['source_kind']=='video' for q in b['questions']]}}))
    for batch in batches:
        expected=len(batch['questions'])
        assert import_batch(batch)['new_questions']==expected
        assert import_batch(batch,apply=True)['new_questions']==expected
        assert import_batch(batch,apply=True)['new_questions']==0
    with Session() as db:
        rows=db.scalars(select(Record).where(Record.kind=='question')).all()
        assert len(rows)==80 and all(evidence(db,q.data) for q in rows)
        assert all(q.data.get('task_solution') for q in rows if q.data.get('task'))
        assert db.scalar(select(func.count()).select_from(Job))==0
        assert db.scalar(select(func.count()).select_from(Usage))==0
        for direction in ['frontend','python','qa']:
            for level in ['junior','middle']:
                assert retrieve(db,'test',direction,level,'ru',kind='question')
                result=client.get(f'/api/v1/study/items?direction={direction}&level={level}&language=ru').json()
                assert result['total']>0
                first=result['items'][0]['id']
                assert client.get('/api/v1/study/items/'+first).status_code==200
        for row in rows:
            response=client.get('/api/v1/study/items/'+row.id+'?mode=task')
            assert response.status_code==(200 if row.data.get('task') else 404)


def test_easyoffer_topic_packages_have_reviewed_evidence_and_no_paid_work(client, user):
    import json
    from pathlib import Path
    from sqlalchemy import func
    from app.db import Job, Usage
    from app.retrieval import evidence, retrieve
    root = Path('/reviewed/easyoffer_20260926')
    discovery = json.loads((root / 'discovery_manifest.json').read_text())
    discovered = {url for page in discovery for url in page['question_links']}
    batches = [json.loads((root / name).read_text()) for name in
               ['frontend_junior.json', 'frontend_middle.json', 'qa_junior.json']]
    for batch in batches:
        for question in batch['questions']:
            assert any(url + '.' in question['review_note'] for url in discovered)
        assert import_batch(batch)['new_questions'] == len(batch['questions'])
        assert import_batch(batch, apply=True)['new_questions'] == len(batch['questions'])
        assert import_batch(batch, apply=True)['new_questions'] == 0
    with Session() as db:
        rows = db.scalars(select(Record).where(Record.kind == 'question')).all()
        assert len(rows) == 12
        assert all(evidence(db, row.data) and row.data['source_kind'] == 'documentation' for row in rows)
        assert sum(bool(row.data.get('task')) for row in rows) == 6
        assert all(row.data.get('task_solution') for row in rows if row.data.get('task'))
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Usage)) == 0
        for batch in batches:
            direction, level = batch['direction'], batch['level']
            assert retrieve(db, 'test', direction, level, 'ru', kind='question')
            result = client.get(f'/api/v1/study/items?direction={direction}&level={level}&language=ru').json()
            assert result['total'] == len(batch['questions'])
        for row in rows:
            detail = client.get('/api/v1/study/items/' + row.id).json()
            assert detail['reference_answer'] == row.data['reference_answer']
            assert all(m['url'].startswith('https://') for m in detail['materials'])
            task = client.get('/api/v1/study/items/' + row.id + '?mode=task')
            assert task.status_code == (200 if row.data.get('task') else 404)
