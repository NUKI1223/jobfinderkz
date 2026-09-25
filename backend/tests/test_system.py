import io
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app import ai, tasks, ingest
from app.main import app
from app.db import Session, Record, Job, Budget, Usage, Knowledge, now, uid, engine
from app.config import settings
from app.schemas import CVFacts, Ranking, DocumentResult, Evaluation, ExtractedQuestions
from app.worker import run_once
from tests.conftest import register

P = '/api/v1'
FACTS = {'summary': 'Python developer with educational projects.', 'skills': ['Python', 'SQL'],
    'experience': ['Built a task tracker for a course.'], 'education': ['University, 2024'],
    'projects': ['Task tracker using PostgreSQL'], 'languages': ['Russian', 'English B1']}
QUESTION = {'question': 'Как работает транзакция базы данных?', 'topic': 'Транзакции', 'direction': 'python',
    'level': 'junior', 'language': 'ru', 'reference_answer': 'Транзакция объединяет операции и обеспечивает атомарность: все изменения фиксируются вместе или откатываются.',
    'rubric': ['Объясняет атомарность', 'Различает commit и rollback', 'Приводит пример'], 'needs_context': False}


def vacancy(client):
    # Provider fixture: regular users receive vacancies, never create them.
    owner = client.get(P + '/auth/me').json()['user']['id']
    with Session.begin() as db:
        row = Record(kind='vacancy', owner_id=owner, status='saved', data={'title': 'Python developer', 'company': 'Example',
            'description': 'Build Python services with PostgreSQL and automated tests.', 'direction': 'python', 'level': 'junior', 'source': 'hh'})
        db.add(row)
        db.flush()
        result = {'id': row.id, 'data': row.data}
    return result


def cv(client):
    row = client.post(P + '/cv/text', json={'text': 'Python developer. Built a task tracker for a university course in 2024.'}).json()
    result = client.put(P + f'/cv/{row["id"]}/confirm', json=FACTS)
    assert result.status_code == 200
    return result.json()


def knowledge(client):
    with Session.begin() as db:
        material = Record(kind='material', data={'url': 'https://docs.python.org/3/library/sqlite3.html',
            'title': 'Transactions', 'text': 'Transactions commit changes atomically, or roll back together. Commit persists changes; rollback cancels changes.',
            'direction': 'python', 'level': 'junior', 'language': 'ru'})
        db.add(material)
        db.flush()
        mid = material.id
    assert client.post(P + '/admin/publish/' + mid).status_code == 200
    ids = []
    for i in range(5):
        q = client.post(P + '/admin/questions', json={**QUESTION, 'question': QUESTION['question'] + f' Пример {i + 1}', 'material_ids': [mid]}).json()
        result = client.post(P + '/admin/publish/' + q['id'])
        assert result.status_code == 200, result.text
        ids.append(q['id'])
    return mid, ids


def fake_structured(job_id, step, instruction, data, schema):
    if schema is CVFacts:
        return CVFacts(**FACTS)
    if schema is DocumentResult:
        return DocumentResult(title='Письмо', introduction='UNTRUSTED fabricated achievement', selected_fact_ids=['skills:0', 'projects:0'],
            closing='UNTRUSTED ten years of experience', changes=['Выделен опыт Python и PostgreSQL'])
    if schema is Ranking:
        return Ranking(matches=[{'vacancy_id': v['id'], 'score': 72, 'reasons': ['Есть Python'],
            'matching_skills': ['Python'], 'missing_skills': ['pytest']} for v in data['vacancies']])
    if schema is Evaluation:
        reliable = data['answer'] != 'insufficient evidence'
        return Evaluation(reliable=reliable, correctness=3, completeness=2, reasoning=2,
            feedback='Уточните смысл rollback.', errors=[], missing_points=['rollback'],
            improved_answer='Транзакция фиксирует все изменения или откатывает их вместе.')
    raise AssertionError(schema)


def finish(client, response):
    assert response.status_code == 200, response.text
    job_id = response.json()['job_id']
    assert run_once()
    result = client.get(P + '/jobs/' + job_id).json()
    assert result['status'] == 'completed', result
    return result['result']


def test_full_user_journey(client, monkeypatch):
    register(client, 'owner@example.com')
    monkeypatch.setattr(ai, 'structured', fake_structured)
    knowledge(client)
    resume = cv(client)
    job = vacancy(client)
    assert client.put(P + '/profile', json={'direction': 'python', 'level': 'junior'}).status_code == 200
    finish(client, client.post(P + '/vacancies/rank', json={'cv_id': resume['id'], 'vacancy_ids': [job['id']]}))
    match = client.get(P + '/record/' + job['id']).json()['data']['match']
    assert match['score'] == 72
    document = finish(client, client.post(P + '/documents', json={'vacancy_id': job['id'], 'cv_id': resume['id'], 'kind': 'cover_letter'}))
    doc = client.get(P + '/record/' + document['record_id']).json()
    assert 'UNTRUSTED' not in doc['data']['text']
    assert 'Task tracker using PostgreSQL' in doc['data']['text']
    assert client.put(P + '/documents/' + doc['id'], json={'text': doc['data']['text']}).json()['status'] == 'saved'
    exported = client.get(P + f'/documents/{doc["id"]}/export')
    assert exported.content[:2] == b'PK'
    plan = finish(client, client.post(P + '/plans', json={'vacancy_id': job['id'], 'cv_id': resume['id']}))
    assert len(client.get(P + '/record/' + plan['record_id']).json()['data']['days']) == 7
    assert client.post(P + f'/plans/{plan["record_id"]}/days/1').json()['data']['days'][0]['done'] is True
    interview = client.post(P + '/interviews', json={'vacancy_id': job['id'], 'direction': 'python', 'level': 'junior', 'language': 'ru'}).json()
    for index in range(5):
        finish(client, client.post(P + f'/interviews/{interview["id"]}/answers/{index}', json={'text': 'Все изменения фиксируются вместе или отменяются.', 'confirmed': True}))
    assert client.get(P + '/record/' + interview['id']).json()['status'] == 'completed'
    stats = client.get(P + '/stats?direction=python&level=junior').json()
    assert stats['timeline'][0]['answers'] == 5
    assert client.get(P + '/stats?direction=frontend&level=junior').json()['timeline'] == []
    assert client.post(P + '/auth/logout').status_code == 200
    assert client.get(P + '/records/interview').status_code == 401
    login = client.post(P + '/auth/login', json={'email': 'owner@example.com', 'password': 'correct-horse-42'})
    assert login.status_code == 200
    assert len(client.get(P + '/records/interview').json()) == 1


def test_ownership_csrf_and_deletion(client, user):
    resume = cv(client)
    with TestClient(app) as stranger:
        register(stranger, 'stranger@example.com')
        assert stranger.get(P + '/record/' + resume['id']).status_code == 404
        assert stranger.put(P + f'/cv/{resume["id"]}/confirm', json=FACTS).status_code == 404
        assert stranger.get(P + '/admin/source').status_code == 403
    csrf = client.headers.pop('x-csrf-token')
    assert client.post(P + '/vacancies', json={}).status_code == 403
    client.headers['x-csrf-token'] = csrf
    assert client.post(P + '/auth/logout', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.delete(P + '/account').status_code == 200
    assert client.get(P + '/auth/me').status_code == 401
    with Session() as db:
        assert db.get(Record, resume['id']) is None


def test_unreviewed_knowledge_never_retrieved(client):
    register(client, 'owner@example.com')
    job = vacancy(client)
    q = client.post(P + '/admin/questions', json={**QUESTION, 'needs_context': True}).json()
    assert client.post(P + '/admin/publish/' + q['id']).status_code == 422
    response = client.post(P + '/interviews', json={'vacancy_id': job['id'], 'direction': 'python', 'level': 'junior', 'language': 'ru'})
    assert response.status_code == 409


def test_resume_uses_snapshot_and_uncertain_score(client, monkeypatch):
    register(client, 'owner@example.com')
    monkeypatch.setattr(ai, 'structured', fake_structured)
    mid, ids = knowledge(client)
    job = vacancy(client)
    interview = client.post(P + '/interviews', json={'vacancy_id': job['id'], 'direction': 'python', 'level': 'junior', 'language': 'ru'}).json()
    assert client.post(P + f'/interviews/{interview["id"]}/answers/0', json={'text': 'x', 'confirmed': False}).status_code == 422
    assert client.post(P + f'/interviews/{interview["id"]}/answers/2', json={'text': 'x', 'confirmed': True}).status_code == 409
    old = interview['data']['turns'][0]['question']
    assert client.put(P + '/admin/questions/' + ids[0], json={**QUESTION, 'reference_answer': 'Changed reviewed answer', 'material_ids': [mid]}).status_code == 200
    assert client.get(P + '/record/' + interview['id']).json()['data']['turns'][0]['question'] == old
    finish(client, client.post(P + f'/interviews/{interview["id"]}/answers/0', json={'text': 'insufficient evidence', 'confirmed': True}))
    evaluation = client.get(P + '/record/' + interview['id']).json()['data']['turns'][0]['evaluation']
    assert evaluation['correctness'] is None and evaluation['reliable'] is False


def test_parallel_budget_reservations_are_atomic(monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', 'test-key-never-used')
    monkeypatch.setattr(settings, 'monthly_budget_usd', 1)
    barrier = Barrier(2)
    def charge(key):
        barrier.wait()
        try:
            ai.reserve(key, 'test', 'fake', .7)
            return 'reserved'
        except ai.Paused:
            return 'paused'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(charge, ['one', 'two']))
    assert sorted(results) == ['paused', 'reserved']
    with Session() as db:
        assert db.get(Budget, now().strftime('%Y-%m')).charged == Decimal('0.700000')


def test_paid_checkpoint_and_unknown_outcome(client, user, monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', 'test-key-never-used')
    with Session.begin() as db:
        job = Job(owner_id=user['id'], kind='test', request_key=uid(), payload={})
        db.add(job)
        db.flush()
        job_id = job.id
    calls = []
    def success():
        calls.append(1)
        return {'text': 'saved'}, .02
    assert ai.paid(job_id, 'ok', 'test', 'fake', .1, success) == {'text': 'saved'}
    assert ai.paid(job_id, 'ok', 'test', 'fake', .1, success) == {'text': 'saved'}
    assert len(calls) == 1
    def timeout():
        calls.append(2)
        raise TimeoutError()
    with pytest.raises(ai.Uncertain):
        ai.paid(job_id, 'unknown', 'test', 'fake', .2, timeout)
    with pytest.raises(ai.Uncertain):
        ai.paid(job_id, 'unknown', 'test', 'fake', .2, timeout)
    assert calls == [1, 2]
    with Session() as db:
        assert db.get(Budget, now().strftime('%Y-%m')).charged == Decimal('.220000')


def test_youtube_normalization_and_subtitles():
    assert ingest.youtube_id('https://www.youtube.com/watch?v=GlK6nGzAK8E&list=abc') == 'GlK6nGzAK8E'
    assert ingest.youtube_id('https://youtu.be/zibAC8HkGFk?t=12') == 'zibAC8HkGFk'
    for url in ['https://youtube.com.evil.test/watch?v=zibAC8HkGFk', 'http://localhost', 'https://youtube.com/playlist?list=x']:
        with pytest.raises(ValueError):
            ingest.youtube_id(url)
    raw = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello world\n\n00:00:01.900 --> 00:00:04.000\nhello world again\n'
    segments = ingest.subtitles(raw)
    assert [s['text'] for s in segments] == ['hello world', 'again']
    assert segments[1]['end'] == 4


def test_import_checkpoints_and_source_dedup(client, monkeypatch):
    register(client, 'owner@example.com')
    source = client.post(P + '/admin/sources', json={'url': 'https://youtu.be/zibAC8HkGFk'}).json()
    duplicate = client.post(P + '/admin/sources', json={'url': 'https://www.youtube.com/watch?v=zibAC8HkGFk&list=x'}).json()
    assert source['id'] == duplicate['id']
    calls = []
    def fake_fetch(*args):
        calls.append(1)
        return {'raw': 'test', 'segments': [{'text': 'What is Python?', 'start': 0, 'end': 120, 'speaker': None}], 'method': 'youtube-authored', 'language': 'en'}
    monkeypatch.setattr(ingest, 'fetch_youtube', fake_fetch)
    response = client.post(P + f'/admin/sources/{source["id"]}/import')
    finish(client, response)
    job_id = response.json()['job_id']
    with Session.begin() as db:
        db.get(Job, job_id).status = 'running'  # Simulate restart after final data saved.
    assert run_once()
    assert calls == [1]
    with Session() as db:
        assert db.get(Budget, now().strftime('%Y-%m')).video_seconds == 120
    assert client.get(P + '/jobs/' + job_id).json()['status'] == 'completed'


def test_disallowed_material_urls_never_connect(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Network must not be contacted')
    monkeypatch.setattr(ingest.socket, 'getaddrinfo', forbidden)
    for url in ['https://127.0.0.1/', 'http://docs.python.org/', 'https://docs.python.org.evil.test/', 'https://user:password@docs.python.org/']:
        with pytest.raises(ValueError):
            ingest.public_page(url)


def test_rebinding_and_private_address_rejected(monkeypatch):
    monkeypatch.setattr(ingest.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='Непубличный'):
        ingest.public_page('https://docs.python.org/3/')


def test_no_key_pauses_without_spending(client, user):
    resume = cv(client)
    response = client.post(P + f'/cv/{resume["id"]}/parse')
    assert run_once()
    result = client.get(P + '/jobs/' + response.json()['job_id']).json()
    assert result['status'] == 'paused'
    assert result['attempts'] == 0
    for _ in range(3):
        assert client.post(P + '/jobs/' + response.json()['job_id'] + '/resume').status_code == 200
        assert run_once()
    assert client.get(P + '/jobs/' + response.json()['job_id']).json()['attempts'] == 0
    with Session() as db:
        assert db.scalars(select(Usage)).all() == []


def test_audio_duration_limit_before_paid_call(client, user, monkeypatch, tmp_path):
    monkeypatch.setattr(ingest, 'duration', lambda p: 190)
    with pytest.raises(ValueError, match='3 минут'):
        ingest.audio_transcript('irrelevant', tmp_path / 'audio.webm', tmp_path, diarize=False)


def test_account_delete_while_worker_locked(client, user):
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key': 'user:' + user['id']})
        try:
            assert client.delete(P + '/account').status_code == 409
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': 'user:' + user['id']})
    assert client.delete(P + '/account').status_code == 200
