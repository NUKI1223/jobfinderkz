from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
import httpx
from openai import OpenAI
import pytest
from sqlalchemy import select
from app import ai, live_budget
from app.config import settings
from app.db import Session, Usage, Budget, Job
from app.schemas import CVFacts
from tests.test_system import FACTS


@pytest.fixture
def paid_job(user, monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', 'synthetic-key')
    with Session.begin() as db:
        job = Job(owner_id=user['id'], kind='test', request_key='accounting-test', payload={})
        db.add(job)
        db.flush()
        return job.id


@pytest.mark.parametrize('status,expected', [(400, 'rejected'), (401, 'rejected'), (403, 'rejected'),
    (404, 'rejected'), (429, 'rejected'), (500, 'uncertain'), (408, 'uncertain')])
def test_openai_error_reservation(paid_job, monkeypatch, status, expected):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={'error': {'message': 'private provider detail'}})
    client = OpenAI(api_key='fake', max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(ai, 'client', lambda: client)
    with pytest.raises(ai.Paused if expected == 'rejected' else ai.Uncertain) as error:
        ai.embed(paid_job, 'embedding', 'synthetic')
    assert 'private' not in str(error.value)
    assert len(calls) == 1
    with Session() as db:
        usage = db.get(Usage, paid_job + ':embedding')
        assert usage.state == expected
        assert db.scalar(select(Budget)).charged == (0 if expected == 'rejected' else usage.reserved)


def test_tokens_cache_reasoning_and_refusal_checkpoint(paid_job, monkeypatch):
    calls = []
    def parse(**kwargs):
        calls.append(1)
        return SimpleNamespace(output_parsed=None, usage=SimpleNamespace(input_tokens=1000,
            output_tokens=200, input_tokens_details=SimpleNamespace(cached_tokens=600),
            output_tokens_details=SimpleNamespace(reasoning_tokens=100)))
    monkeypatch.setattr(ai, 'client', lambda: SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    for _ in range(2):
        with pytest.raises(ValueError, match='отказ'):
            ai.structured(paid_job, 'refusal', 'test', {}, CVFacts)
    assert len(calls) == 1
    with Session() as db:
        usage = db.get(Usage, paid_job + ':refusal')
        assert usage.actual == Decimal('0.001245')
        assert usage.details['reasoning_tokens'] == 100
        assert usage.state == 'completed'


def test_audio_estimate_is_not_rounded_reservation(paid_job, monkeypatch, tmp_path):
    path = tmp_path / 'fake.wav'
    path.write_bytes(b'fixed response audio fixture')
    response = SimpleNamespace(model_dump=lambda: {'text': 'Synthetic', 'usage': {'type': 'duration', 'seconds': 61}})
    monkeypatch.setattr(ai, 'client', lambda: SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=lambda **kwargs: response))))
    ai.transcribe(paid_job, 'audio', path, 61)
    with Session() as db:
        usage = db.get(Usage, paid_job + ':audio')
        assert usage.reserved == Decimal('.04')
        assert usage.actual == Decimal('.00305')
        assert usage.details['duration_seconds'] == 61
        assert usage.details['method'] == 'audio_duration_estimate'


def test_shared_live_cap_parallel_and_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'live_check_mode', True)
    monkeypatch.setattr(settings, 'live_check_ledger', tmp_path / 'ledger.json')
    def reserve(index):
        try:
            live_budget.update(str(index), ceiling=1.1)
            return True
        except ai.Paused:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, ['main', 'test'])) == [False, True]
    # A new reader sees persisted unresolved reservations, regardless of DB resets.
    with pytest.raises(ai.Paused):
        live_budget.update('after-restart', ceiling=1)


def test_summary_distinguishes_spend_reserve_and_estimate(client, monkeypatch, paid_job):
    from app.db import User
    with Session.begin() as db:
        owner = db.get(Job, paid_job).owner_id
        db.get(User, owner).role = 'admin'
    ai.paid(paid_job, 'done', 'text', 'fake', .1, lambda: ({}, .02))
    ai.reserve('unknown', 'text', 'fake', .3)
    summary = client.get('/api/v1/admin/usage/summary').json()
    assert summary['completed'] == .02
    assert summary['open_reservations'] == .3
    assert summary['remaining'] == pytest.approx(19.68)
