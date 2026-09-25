import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from app import ai, tasks
from app.cv_sections import section_draft
from app.db import Session, Job, Record, Knowledge, User, uid
from app.worker import run_once
from tests.conftest import register

P = '/api/v1'


@pytest.mark.parametrize('text', [
    'Анна\nО себе\nРазработчик Python\nНавыки: Python, SQL\nОпыт работы\nООО Пример, 2022–2024\nОбразование\nУниверситет\nПроекты\nТрекер задач\nЯзыки: Русский; English B1',
    'Anna\nSUMMARY: Разработчик Python\nSKILLS: Python, SQL\nWORK EXPERIENCE\nООО Пример, 2022–2024\nEDUCATION\nУниверситет\nPROJECTS\nТрекер задач\nLANGUAGES: Русский; English B1',
])
def test_cv_sections_without_ai(client, user, text):
    response = client.post(P + '/cv/text', json={'text': text})
    assert response.status_code == 200
    data = response.json()['data']
    assert data['facts'] == {'summary': 'Разработчик Python', 'skills': ['Python', 'SQL'],
        'experience': ['ООО Пример, 2022–2024'], 'education': ['Университет'],
        'projects': ['Трекер задач'], 'languages': ['Русский', 'English B1']}
    assert data['unassigned_text'] in ('Анна', 'Anna')


def test_cv_unstructured_text_and_legacy_records_are_not_summary(client, user):
    raw = 'Python developer. Built services with PostgreSQL for a university project.'
    assert section_draft(raw)['facts']['summary'] == ''
    with Session.begin() as db:
        row = Record(owner_id=user['id'], kind='cv', data={'text': raw, 'facts': None})
        db.add(row)
        db.flush()
        rid = row.id
    data = client.get(P + '/record/' + rid).json()['data']
    assert data['facts']['summary'] == ''
    assert data['unassigned_text'] == raw


def test_user_cannot_create_vacancy(client, user):
    assert client.post(P + '/vacancies', json={'title': 'Python developer',
        'description': 'Python developer with PostgreSQL experience.'}).status_code == 403


def test_docx_sections_and_explicit_reparse_preserve_previous_facts(client, user):
    import io
    from docx import Document
    doc = Document()
    for line in ['О себе', 'Разработчик Python', 'Навыки', 'Python, SQL', 'Опыт работы', 'Разработка учебного сервиса']:
        doc.add_paragraph(line)
    output = io.BytesIO()
    doc.save(output)
    row = client.post(P + '/cv/upload', files={'file': ('cv.docx', output.getvalue())}).json()
    assert row['data']['facts']['skills'] == ['Python', 'SQL']
    facts = {**row['data']['facts'], 'summary': 'Моя сохранённая правка'}
    assert client.put(P + '/cv/' + row['id'] + '/confirm', json=facts).status_code == 200
    result = client.post(P + '/cv/' + row['id'] + '/sections').json()
    assert result['status'] == 'review'
    assert result['data']['facts']['summary'] == 'Разработчик Python'
    assert result['data']['versions'][-1]['facts'] == facts


def test_shared_source_serialized_across_different_owners(client, user, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def handler(job):
        calls.append(job.id)
        if len(calls) == 1:
            started.set()
            assert release.wait(8)
        return {}
    monkeypatch.setitem(tasks.HANDLERS, 'import_source', handler)
    with Session.begin() as db:
        other = User(email='second@example.com', password_hash='unused')
        db.add(other)
        db.flush()
        for owner in (user['id'], other.id):
            db.add(Job(owner_id=owner, kind='import_source', request_key=uid(), payload={'source_id': 'same-source'}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_once)
        assert started.wait(3)
        try:
            assert pool.submit(run_once).result(timeout=3) is False
        finally:
            release.set()
        assert first.result(timeout=3)
    assert run_once()
    assert len(calls) == 2


def test_stale_embedding_checkpoint_never_written_to_new_revision(client, user, monkeypatch):
    with Session.begin() as db:
        row = Record(kind='material', status='published', data={'version': 2})
        db.add(row)
        db.flush()
        rid = row.id
        db.add(Knowledge(record_id=rid, text='New reviewed content', direction='python', level='junior', language='ru'))
        job = Job(owner_id=user['id'], kind='index_knowledge', request_key=uid(), payload={'record_id': rid},
            checkpoints={'index-input': {'version': 1, 'text': 'Old reviewed content'}, 'embedding': [0.01] * 1536})
        db.add(job)
        db.flush()
    seen = []
    def embed(job_id, step, text):
        seen.append(text)
        return ai.checkpoint(job_id, step)
    monkeypatch.setattr(ai, 'embed', embed)
    assert tasks.index_knowledge(job)['skipped'] == 'revision_changed'
    assert seen == ['Old reviewed content']
    with Session() as db:
        assert db.get(Knowledge, rid).embedding is None


def test_republishing_material_preserves_embedding(client):
    register(client, 'owner@example.com')
    with Session.begin() as db:
        row = Record(kind='material', status='published', data={'text': 'Reviewed material text', 'version': 1,
            'direction': 'python', 'level': 'junior', 'language': 'ru'})
        db.add(row)
        db.flush()
        rid = row.id
        db.add(Knowledge(record_id=rid, text=row.data['text'], direction='python', level='junior', language='ru', embedding=[0.01] * 1536))
    assert client.post(P + '/admin/publish/' + rid).status_code == 200
    with Session() as db:
        assert db.get(Knowledge, rid).embedding is not None


def test_second_queued_source_import_reuses_existing_transcript(client, user, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Source already imported: no network or paid request')
    monkeypatch.setattr(tasks.ingest, 'fetch_youtube', forbidden)
    with Session.begin() as db:
        source = Record(kind='source', data={'transcript': {'segments': [{'text': 'Saved'}]}})
        db.add(source)
        db.flush()
        job = Job(owner_id=user['id'], kind='import_source', request_key=uid(), payload={'source_id': source.id})
        db.add(job)
        db.flush()
    assert tasks.import_source(job) == {'record_id': source.id, 'segments': 1}
