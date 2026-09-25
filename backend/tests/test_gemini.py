import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.config import settings
from app.db import Session, Job, Usage, Budget
from app.schemas import CVFacts
from tests.test_system import FACTS


@pytest.fixture
def gemini_job(monkeypatch, user):
    monkeypatch.setattr(settings, 'text_provider', 'gemini')
    monkeypatch.setattr(settings, 'gemini_api_key', 'synthetic-key')
    monkeypatch.setattr(settings, 'gemini_free_tier', True)
    with Session.begin() as db:
        job = Job(owner_id=user['id'], kind='parse_cv', request_key='gemini-test', payload={})
        db.add(job)
        db.flush()
        return job.id


def transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(ai.gemini.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def response():
    return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(FACTS)}]}}],
        'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 50, 'thoughtsTokenCount': 10}})


def call(job):
    return ai.structured(job, 'facts', 'Extract facts', {'text': 'test@example.com Python'}, CVFacts)


def test_success_redaction_checkpoint_and_switch(monkeypatch, gemini_job):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['x-goog-api-key'] == 'synthetic-key'
        assert 'synthetic-key' not in str(request.url)
        body = json.loads(request.content)
        assert 'test@example.com' not in body['contents'][0]['parts'][0]['text']
        assert body['generationConfig']['responseJsonSchema']['additionalProperties'] is False
        return response()
    transport(monkeypatch, handle)
    assert call(gemini_job).skills == FACTS['skills']
    monkeypatch.setattr(settings, 'text_provider', 'openai')
    assert call(gemini_job).skills == FACTS['skills']
    assert len(requests) == 1
    with Session() as db:
        usage = db.get(Usage, gemini_job + ':facts')
        assert usage.actual == 0 and usage.state == 'completed'
        assert usage.model.startswith('gemini/')


def test_rejected_quota_can_resume(monkeypatch, gemini_job):
    replies = [httpx.Response(429, json={'error': 'private provider detail'}), response()]
    transport(monkeypatch, lambda request: replies.pop(0))
    with pytest.raises(ai.Paused, match='лимит Gemini'):
        call(gemini_job)
    with Session() as db:
        assert db.get(Usage, gemini_job + ':facts').state == 'rejected'
        assert db.scalar(select(Budget)).charged == 0
    assert call(gemini_job).skills == FACTS['skills']


@pytest.mark.parametrize('mode', ['timeout', 'server', 'invalid'])
def test_unknown_never_retries_or_falls_back(monkeypatch, gemini_job, mode):
    def handle(request):
        if mode == 'timeout':
            raise httpx.ReadTimeout('private detail')
        return httpx.Response(500 if mode == 'server' else 200, json={})
    transport(monkeypatch, handle)
    with pytest.raises(ai.Uncertain) as error:
        call(gemini_job)
    assert 'private' not in str(error.value)
    monkeypatch.setattr(settings, 'text_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_api_key', 'fake')
    with pytest.raises(ai.Uncertain):
        call(gemini_job)


def test_daily_limit_serializes_parallel_requests(monkeypatch, gemini_job):
    monkeypatch.setattr(settings, 'gemini_daily_requests', 1)
    def reserve(i):
        try:
            ai.reserve(str(i), 'text', 'gemini/test', 0, provider='gemini')
            return True
        except ai.Paused:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]


def test_paid_cost_and_capabilities(monkeypatch, gemini_job, client):
    monkeypatch.setattr(settings, 'gemini_free_tier', False)
    transport(monkeypatch, lambda request: response())
    call(gemini_job)
    with Session() as db:
        assert float(db.get(Usage, gemini_job + ':facts').actual) == pytest.approx(.000180)
    flags = client.get('/api/v1/connections').json()
    assert flags['text_ai'] and flags['text_provider'] == 'gemini'
    assert not flags['audio'] and not flags['embeddings']


def test_openai_retained_explicit_selection(monkeypatch, gemini_job):
    monkeypatch.setattr(settings, 'text_provider', 'openai')
    with pytest.raises(ai.Paused, match='OPENAI_API_KEY'):
        call(gemini_job)
    monkeypatch.setattr(settings, 'openai_api_key', 'fake')
    def parse(**kwargs):
        assert kwargs['text_format'] is CVFacts and kwargs['store'] is False
        return SimpleNamespace(output_parsed=CVFacts(**FACTS), usage=SimpleNamespace(input_tokens=100, output_tokens=50))
    monkeypatch.setattr(ai, 'client', lambda: SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    assert call(gemini_job).skills == FACTS['skills']
