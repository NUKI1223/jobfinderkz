from sqlalchemy import select
from app import ai
from app.db import Session, Record, Job, Knowledge
from app.schemas import DocumentResult, DocumentFragment, DocumentReview, FragmentReview
from tests.conftest import register
from tests.test_system import cv, vacancy, finish, knowledge, fake_structured


def test_translated_document_requires_review_and_blocks_new_claims(client, user, monkeypatch):
    resume, job = cv(client), vacancy(client)
    def generate(job_id, step, instruction, data, schema):
        if schema is DocumentResult:
            return DocumentResult(title='Resume', introduction='', closing='', changes=['Translated'],
                selected_fact_ids=['projects:0'], fragments=[DocumentFragment(fact_ids=['projects:0'],
                text='Built a task tracker using PostgreSQL for 500 customers.')])
        return DocumentReview(fragments=[FragmentReview(index=0, supported=False, issues=['Customers are invented'])])
    monkeypatch.setattr(ai, 'structured', generate)
    doc_id = finish(client, client.post('/api/v1/documents', json={'cv_id': resume['id'],
        'vacancy_id': job['id'], 'kind': 'adapted_cv', 'language': 'en'}))['record_id']
    doc = client.get('/api/v1/record/' + doc_id).json()['data']
    assert doc['fragments'][0]['fact_ids'] == ['projects:0']
    assert client.get(f'/api/v1/documents/{doc_id}/export').status_code == 409
    bad = {'text': doc['text'], 'confirmed': True, 'fragment_texts': [doc['fragments'][0]['text']]}
    assert client.put('/api/v1/documents/' + doc_id, json=bad).status_code == 422
    corrected = 'Task tracker using PostgreSQL'
    good = {'text': corrected, 'confirmed': True, 'fragment_texts': [corrected]}
    assert client.put('/api/v1/documents/' + doc_id, json=good).status_code == 200
    assert client.get(f'/api/v1/documents/{doc_id}/export').content[:2] == b'PK'
    with Session() as db:
        assert db.get(Record, doc_id).data['versions'][0]['fragments'][0]['issues']


def test_long_ranking_batches_and_resume(client, user, monkeypatch):
    resume = cv(client)
    ids = [vacancy(client)['id'] for _ in range(8)]
    with Session.begin() as db:
        for rid in ids:
            row = db.get(Record, rid)
            row.data = {**row.data, 'description': 'Python опыт ' * 2200}
    calls = []
    def generate(*args):
        import json
        calls.append(args[1])
        assert len(json.dumps(args[3], ensure_ascii=False).encode()) < 85000
        return fake_structured(*args)
    monkeypatch.setattr(ai, 'structured', generate)
    result = finish(client, client.post('/api/v1/vacancies/rank', json={'cv_id': resume['id'], 'vacancy_ids': ids}))
    assert result['count'] == 8 and len(calls) > 1
    with Session() as db:
        assert all(db.get(Record, rid).data['match']['score'] == 72 for rid in ids)
        assert db.scalar(select(Job).where(Job.kind == 'rank')).checkpoints['rank-input']


def test_availability_and_plan_repeats(client, monkeypatch):
    register(client, 'owner@example.com')
    monkeypatch.setattr(ai, 'structured', fake_structured)
    knowledge(client)
    resume, job = cv(client), vacancy(client)
    client.put('/api/v1/profile', json={'direction': 'python', 'level': 'junior'})
    available = client.get('/api/v1/knowledge/availability').json()
    assert next(a for a in available if a['direction']=='python' and a['level']=='junior' and a['language']=='ru')['interview_ready']
    assert not next(a for a in available if a['direction']=='python' and a['level']=='junior' and a['language']=='en')['interview_ready']
    plan = finish(client, client.post('/api/v1/plans', json={'cv_id': resume['id'], 'vacancy_id': job['id']}))
    days = client.get('/api/v1/record/' + plan['record_id']).json()['data']
    assert days['shortage'] == 2
    assert [d['repeat'] for d in days['days']] == [False]*5+[True]*2


def test_english_translation_keeps_canonical_question_and_rejects_duplicate(client):
    register(client, 'owner@example.com')
    material, ids = knowledge(client)
    with Session.begin() as db:
        english = Record(kind='material', status='published', data={'url': 'https://docs.python.org/3/reference/compound_stmts.html',
            'title': 'Python docs', 'text': 'A with statement invokes enter and exit.', 'direction': 'python',
            'level': 'junior', 'language': 'en'})
        db.add(english)
        db.flush()
        mid = english.id
    payload = {'question': 'How does a database transaction work in Python?', 'topic': 'Transactions',
        'direction': 'python', 'level': 'junior', 'language': 'en', 'reference_answer': 'A transaction commits all changes together or rolls them back.',
        'rubric': ['Commit', 'Rollback', 'Atomicity'], 'material_ids': [mid], 'needs_context': False,
        'translation_of': ids[0]}
    created = client.post('/api/v1/admin/questions', json=payload).json()
    assert client.post('/api/v1/admin/publish/' + created['id']).status_code == 200
    duplicate = client.post('/api/v1/admin/questions', json=payload).json()
    assert client.post('/api/v1/admin/publish/' + duplicate['id']).status_code == 409
    with Session() as db:
        data = db.get(Record, created['id']).data
    assert data['translation_of'] == ids[0]
    assert data['language'] == 'en'
