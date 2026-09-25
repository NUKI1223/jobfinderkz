import httpx
import pytest
from sqlalchemy import select
from app import tasks
from app.config import settings
from app.db import Session, Job, Record, uid
from app.hh import region_index, resolve_regions, work_formats

TREE = [{'id': '40', 'name': 'Казахстан', 'areas': [{'id': '160', 'name': 'Алматы', 'areas': []}]}]
ITEM = {'id': '123', 'name': 'Python engineer', 'description': '<p>Python and SQL</p>',
    'alternate_url': 'https://hh.kz/vacancy/123', 'area': {'id': '160', 'name': 'Алматы'},
    'work_format': [{'id': 'HYBRID'}, {'id': 'REMOTE'}]}


def test_regions_reject_unknown_and_ambiguous():
    names, ids = region_index(TREE)
    assert resolve_regions([' алматы ', 'Алматы'], names) == ['160']
    assert ids['160']['parents'] == ['Казахстан']
    with pytest.raises(ValueError, match='не найден'):
        resolve_regions(['Typo'], names)
    with pytest.raises(ValueError, match='неоднозначно'):
        resolve_regions(['Алматы'], {'алматы': [ids['160'], ids['160']]})
    assert work_formats(ITEM) == ['hybrid', 'remote']
    assert work_formats({'schedule': {'id': 'fullDay'}}) == []


def test_sync_regions_formats_updates_and_resume(client, user, monkeypatch):
    monkeypatch.setattr(settings, 'hh_access_token', 'test-not-sent-to-network')
    requests, failing = [], [True]
    def respond(request):
        requests.append(request)
        if request.url.path == '/areas':
            return httpx.Response(200, json=TREE)
        if request.url.path == '/vacancies':
            return httpx.Response(200, json={'items': [{'id': '123'}, {'id': '456'}]})
        if request.url.path == '/vacancies/456' and failing[0]:
            return httpx.Response(429)
        if request.url.path == '/vacancies/456':
            return httpx.Response(404)
        return httpx.Response(200, json=ITEM)
    original = httpx.Client
    monkeypatch.setattr(tasks.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with Session.begin() as db:
        row = Record(owner_id=user['id'], kind='vacancy', dedup_key='hh:123', data={'favorite': True,
            'description': 'Old requirements', 'match': {'score': 99}})
        db.add(row)
        job = Job(owner_id=user['id'], kind='hh_sync', request_key=uid(), payload={'text': 'Python',
            'regions': ['Алматы'], 'level': 'middle', 'direction': 'python', 'work_format': 'hybrid'})
        db.add(job)
        db.flush()
    with pytest.raises(ValueError, match='429'):
        tasks.hh_sync(job)
    query = next(r for r in requests if r.url.path == '/vacancies')
    assert query.url.params.get_list('area') == ['160']
    assert query.url.params['work_format'] == 'HYBRID'
    assert query.url.params['experience'] == 'between1And3'
    failing[0] = False
    assert tasks.hh_sync(job)['count'] == 1
    assert sum(r.url.path == '/areas' for r in requests) == 1
    assert sum(r.url.path == '/vacancies/123' for r in requests) == 1
    with Session() as db:
        rows = db.scalars(select(Record).where(Record.kind == 'vacancy')).all()
        assert len(rows) == 1
        assert rows[0].data['favorite'] is True
        assert rows[0].data['description'] == 'Python and SQL'
        assert rows[0].data['work_formats'] == ['hybrid', 'remote']
        assert rows[0].data['region_parents'] == ['Казахстан']
        assert 'match' not in rows[0].data


def test_request_uses_profile_regions_when_not_overridden(client, user):
    assert client.put('/api/v1/profile', json={'regions': ['Алматы']}).status_code == 200
    result = client.post('/api/v1/vacancies/hh/sync', json={'text': 'Python'}).json()
    with Session() as db:
        assert db.get(Job, result['job_id']).payload['regions'] == ['Алматы']
