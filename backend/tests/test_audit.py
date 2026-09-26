"""Audit regressions. Synthetic fixtures; isolated PostgreSQL only, no providers."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app import ai, tasks
from app.config import settings
from app.db import Session, Record, Job, Knowledge, uid
from app.schemas import CVFacts
from app.store import enqueue
from tests.conftest import register
from tests.test_system import cv, vacancy, knowledge, FACTS, QUESTION, fake_structured, finish

P = '/api/v1'


def test_b01_redaction_preserves_dates():
    source = '2020-01-01, 01.02.2020, 2020 - 2024; +7 (777) 123-45-67; 87771234567; a@example.com'
    result = ai.redact(source)
    for value in ('2020-01-01', '01.02.2020', '2020 - 2024'):
        assert value in result
    assert '777' not in result and 'example.com' not in result


def test_b06_cv_item_and_total_limits():
    with pytest.raises(ValueError):
        CVFacts(**{**FACTS, 'skills': ['x' * 200000]})


def test_b02_omitted_translation_is_preserved(client):
    register(client, 'owner@example.com')
    with Session.begin() as db:
        row = Record(kind='question', data={**QUESTION, 'translation_of': 'original', 'version': 1})
        db.add(row)
        db.flush()
    response = client.put(P + '/admin/questions/' + row.id, json=QUESTION)
    assert response.status_code == 200
    assert response.json()['data']['translation_of'] == 'original'


def test_b04_b14_parse_creates_reviewable_draft(client, user, monkeypatch):
    resume = cv(client)
    monkeypatch.setattr(ai, 'structured', fake_structured)
    result = finish(client, client.post(P + '/cv/' + resume['id'] + '/parse'))
    updated = client.get(P + '/record/' + resume['id']).json()
    assert updated['status'] == 'confirmed'
    assert updated['data']['parse_drafts'][-1]['facts'] == FACTS
    again = client.post(P + '/cv/' + resume['id'] + '/parse').json()
    with Session() as db:
        assert db.get(Job, again['job_id']).status == 'queued'


def test_b03_b09_audio_repeat_is_bound_to_turn(client, user, monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', 'synthetic')
    with Session.begin() as db:
        row = Record(kind='interview', owner_id=user['id'], data={'turns': [{'evaluation': None}] * 5})
        db.add(row)
        db.flush()
    def post(data=b'synthetic audio', index=0):
        return client.post(P + f'/interviews/{row.id}/audio?index={index}',
            files={'file': ('answer.webm', data)}, headers={'Idempotency-Key': 'audio-attempt'})
    one, two = post(), post()
    assert one.status_code == two.status_code == 200
    assert one.json() == two.json()
    assert post(b'changed').status_code == 409
    assert post(index=1).status_code == 409
    with Session() as db:
        job = db.get(Job, one.json()['job_id'])
        assert job.payload['index'] == 0
        assert len(list(settings.storage_path.rglob('*.webm'))) == 1


def test_b08_partial_fts_match(client, user):
    from app.retrieval import retrieve
    with Session.begin() as db:
        for rid, content in [('a', 'Unrelated gardening'), ('z', 'Python functions')]:
            db.add(Record(id=rid, kind='material', status='published', data={}))
            db.flush()
            db.add(Knowledge(record_id=rid, text=content, direction='python', level='junior', language='en'))
    with Session() as db:
        rows = retrieve(db, 'Python SQL docker experience required', 'python', 'junior', 'en')
        assert rows[0].id == 'z'


def test_b17_b22_no_payment_without_current_evidence(client, monkeypatch):
    register(client, 'owner@example.com')
    mid, ids = knowledge(client)
    resume, vac = cv(client), vacancy(client)
    client.put(P + '/profile', json={'direction': 'python', 'level': 'junior'})
    assert client.put(P + '/admin/materials/' + mid, json={'text': 'Updated reviewed documentation'}).status_code == 200
    available = client.get(P + '/knowledge/availability').json()
    assert not next(x for x in available if x['direction']=='python' and x['language']=='ru' and x['level']=='junior')['interview_ready']
    assert client.post(P + '/interviews', json={'vacancy_id': vac['id'], 'direction':'python','level':'junior','language':'ru'}).status_code == 409
    monkeypatch.setattr(settings, 'openai_api_key', 'synthetic')
    monkeypatch.setattr(ai, 'embed', lambda *a: pytest.fail('Must check evidence before payment'))
    response = client.post(P + '/plans', json={'cv_id':resume['id'],'vacancy_id':vac['id']})
    from app.worker import run_once
    assert run_once()
    assert client.get(P + '/jobs/' + response.json()['job_id']).json()['status'] == 'failed'


def test_b18_material_classification_part_of_identity(client, user, monkeypatch):
    monkeypatch.setattr(tasks.ingest, 'public_page', lambda url: {'url':url, 'title':'Python', 'text':'Documentation'})
    results = []
    for level in ('junior', 'middle'):
        with Session.begin() as db:
            job = Job(owner_id=user['id'], kind='import_material', request_key=uid(), payload={
                'url':'https://docs.python.org/3/', 'direction':'python','level':level,'language':'en'})
            db.add(job)
            db.flush()
        results.append(tasks.import_material(job)['record_id'])
    assert len(set(results)) == 2


def test_b19_global_index_identity(client, user):
    from app.db import User
    with Session.begin() as db:
        other = User(email='admin2@example.invalid', password_hash='disabled')
        db.add(other)
        db.flush()
    with Session() as db:
        a = enqueue(db, user['id'], 'index_knowledge', {'record_id':'shared', 'version':1}, 'one')
        b = enqueue(db, other.id, 'index_knowledge', {'record_id':'shared', 'version':1}, 'two')
    assert a == b


def test_b20_foreign_key_failure_is_not_retried():
    with Session() as db, pytest.raises(IntegrityError):
        enqueue(db, 'missing-owner', 'parse_cv', {}, 'key')


def test_b05_large_cyrillic_cv_preserves_all_parse_parts(client, user, monkeypatch):
    raw = 'Опыт разработки. ' * 3500
    row = client.post(P + '/cv/text', json={'text': raw}).json()
    seen = []
    def generate(job, step, instruction, data, schema):
        seen.append(data['cv'])
        assert len(data['cv'].encode()) < 50000
        return CVFacts(**FACTS)
    monkeypatch.setattr(ai, 'structured', generate)
    finish(client, client.post(P + '/cv/' + row['id'] + '/parse'))
    assert ''.join(seen) == raw
    result = client.get(P + '/record/' + row['id']).json()['data']
    assert len(result['parse_drafts'][0]['parts']) == len(seen)


def test_b07_user_claims_are_never_automatically_verified(client, user):
    import io
    from docx import Document
    with Session.begin() as db:
        row = Record(owner_id=user['id'], kind='document', data={'title':'CV', 'text':'Invented claim',
            'requires_confirmation':True, 'fragments':[{'text':'Invented claim', 'proposed_text':'Invented claim',
            'source_text':'Source', 'fact_ids':['skills:0'], 'issues':['Unsupported']} ]})
        db.add(row)
        db.flush()
    value = 'Invented claim!\n\nNew employer and 20 years experience.'
    body = {'text':value, 'confirmed':True}
    assert client.put(P + '/documents/' + row.id, json=body).status_code == 422
    response = client.put(P + '/documents/' + row.id, json={**body, 'accept_user_claims':True})
    assert response.status_code == 200
    data = response.json()['data']
    assert all(b['origin']=='user' and not b['verified_by_cv'] for b in data['blocks'])
    assert data['versions'][0]['text'] == 'Invented claim'
    exported = Document(io.BytesIO(client.get(P + '/documents/' + row.id + '/export').content))
    assert '\n'.join(p.text for p in exported.paragraphs[1:]) == value


def test_b11_ranking_changed_cv_never_applied(client, user, monkeypatch):
    resume, vac = cv(client), vacancy(client)
    def generate(*args):
        with Session.begin() as db:
            row = db.get(Record, resume['id'])
            row.data = {**row.data, 'version':99}
        return fake_structured(*args)
    monkeypatch.setattr(ai, 'structured', generate)
    finish(client, client.post(P + '/vacancies/rank', json={'cv_id':resume['id'], 'vacancy_ids':[vac['id']]}))
    assert 'match' not in client.get(P + '/record/' + vac['id']).json()['data']


def test_b15_paused_answer_can_change_only_before_payment(client, user):
    from app.db import Usage, Budget, now
    with Session.begin() as db:
        row = Record(kind='interview', owner_id=user['id'], data={'turns':[{'evaluation':None,'question':{},'materials':[]}]})
        db.add(row)
        db.flush()
    url = P + f'/interviews/{row.id}/answers/0'
    first = client.post(url, json={'text':'First', 'confirmed':True}).json()['job_id']
    with Session.begin() as db:
        db.get(Job, first).status = 'paused'
    response = client.post(url, json={'text':'Corrected', 'confirmed':True})
    assert response.status_code == 200 and response.json()['job_id'] == first
    with Session.begin() as db:
        db.get(Job, first).status = 'needs_review'
        db.add(Budget(month='2026-09'))
        db.flush()
        db.add(Usage(key=first+':evaluate', month='2026-09', operation='text', model='fixture', reserved=1, state='uncertain'))
    assert client.post(url, json={'text':'Third', 'confirmed':True}).status_code == 409
    with Session() as db:
        assert db.get(Job, first).payload['text'] == 'Corrected'
        assert db.get(Record, row.id).data['turns'][0]['answer'] == 'Corrected'


def test_b16_stats_language(client, user):
    with Session.begin() as db:
        for language, score in [('ru',1),('en',4)]:
            db.add(Record(kind='interview', owner_id=user['id'], data={'direction':'python','level':'junior','language':language,
                'turns':[{'question':{'topic':'Functions'}, 'evaluation':{'reliable':True,
                    'correctness':score,'completeness':score,'reasoning':score,'errors':[]}}]}))
    for language, score in [('ru',1),('en',4)]:
        data = client.get(P + '/stats?direction=python&level=junior&language='+language).json()
        assert len(data['timeline']) == 1 and data['timeline'][0]['score'] == score


def test_b23_probe_verdict_and_technical_terms():
    from app.probe_checks import exit_status, speech_terms
    assert exit_status({'checks':{'text':False}}) == 1
    assert exit_status({'checks':{'text':True},'stopped':'timeout'}) == 1
    assert exit_status({'checks':{'audio':'skipped'}}) == 2
    assert exit_status({'checks':{'text':True}}) == 0
    assert not speech_terms('Some unrelated speech', ['python','context'])
    assert speech_terms('Python functions and context managers', ['python','function','context'])


def test_reconciliation_is_atomic_and_never_replays(client):
    from app.db import Usage, Budget
    register(client, 'owner@example.com')
    with Session.begin() as db:
        db.add(Budget(month='2026-09', charged=1))
        db.flush()
        db.add(Usage(key='synthetic:call', month='2026-09', operation='text', model='fixture', reserved=1,state='uncertain'))
    body={'outcome':'charged','amount':'0.125','evidence':'Synthetic receipt reference; no real spending'}
    result = client.post(P + '/admin/usage/synthetic:call/reconcile', json=body)
    assert result.status_code == 200
    assert client.post(P + '/admin/usage/synthetic:call/reconcile', json=body).status_code == 409
    with Session() as db:
        assert float(db.get(Budget,'2026-09').charged) == .125
        assert len(db.get(Usage,'synthetic:call').details['reconciliations']) == 1
        assert db.scalar(select(Job)) is None


def test_b10_sigterm_drains_paid_checkpoint_and_stops_claiming(client, user, tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time
    from app.db import Usage
    with Session.begin() as db:
        first = Job(owner_id=user['id'], kind='drain_fixture', request_key='first', payload={})
        second = Job(owner_id=user['id'], kind='drain_fixture', request_key='second', payload={})
        db.add(first)
        db.flush()
        db.add(second)
        db.flush()
    script = '''
import runpy, time
from app import tasks, ai
from app.config import settings
settings.openai_api_key = 'synthetic-no-network'
def handler(job):
    def paid_response():
        time.sleep(1)
        return {'saved': True}, 0.001
    return ai.paid(job.id, 'fixture', 'text', 'synthetic', .1, paid_response)
tasks.HANDLERS['drain_fixture'] = handler
runpy.run_module('app.worker', run_name='__main__')
'''
    process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            with Session() as db:
                if db.get(Usage,first.id+':fixture'):
                    break
            time.sleep(.05)
        else:
            pytest.fail('Worker never reached reserved provider call')
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=8) == 0
        with Session() as db:
            assert db.get(Job,first.id).status == 'completed'
            assert db.get(Job,first.id).checkpoints['fixture'] == {'saved':True}
            assert db.get(Job,second.id).status == 'queued'
            assert db.get(Usage,first.id+':fixture').state == 'completed'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_b12_concurrent_cv_confirmation_conflict(client, user):
    resume = cv(client)
    version = str(resume['data']['version'])
    assert client.put(P + '/cv/' + resume['id'] + '/confirm', json=FACTS, headers={'If-Match':version}).status_code == 200
    assert client.put(P + '/cv/' + resume['id'] + '/confirm', json=FACTS, headers={'If-Match':version}).status_code == 409


def test_b12_hh_preserves_favorite_after_waiting_for_row_lock(client, user, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    import time
    monkeypatch.setattr(settings,'hh_access_token','synthetic')
    with Session.begin() as db:
        row = Record(owner_id=user['id'], kind='vacancy', dedup_key='hh:123', data={'favorite':False})
        db.add(row)
        job = Job(owner_id=user['id'], kind='hh_sync', request_key=uid(),
            payload={'text':'Python','level':'junior','direction':'python','work_format':'any'},
            checkpoints={'hh':[{'id':'123','name':'Developer','description':'Python','alternate_url':'https://hh.kz/vacancy/123',
                'area':{'id':'40','name':'Kazakhstan'}}]})
        db.add(job)
        db.flush()
    with Session() as db, ThreadPoolExecutor(max_workers=1) as pool:
        locked = db.scalar(select(Record).where(Record.id==row.id).with_for_update())
        future = pool.submit(tasks.hh_sync,job)
        time.sleep(.1)
        assert not future.done()
        locked.data = {'favorite':True}
        db.commit()
        assert future.result(timeout=3)['count'] == 1
    with Session() as db:
        assert db.get(Record,row.id).data['favorite'] is True


def test_b21_upload_and_account_deletion_share_lock(client, user):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.main import upload
    from fastapi import HTTPException
    started, release = threading.Event(), threading.Event()
    class File:
        filename = 'cv.docx'
        done = False
        async def read(self, size):
            started.set()
            assert release.wait(3)
            if self.done:
                return b''
            self.done = True
            return b'fixture'
        async def close(self):
            pass
    def uploading():
        with Session.begin() as db:
            return asyncio.run(upload(File(),user['id'],{'.docx'},100,db))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(uploading)
        assert started.wait(2)
        try:
            assert client.delete(P+'/account').status_code == 409
        finally:
            release.set()
        path = future.result(timeout=3)
    assert path.exists()
    assert client.delete(P+'/account').status_code == 200
    assert not path.exists()
    with Session() as db, pytest.raises(HTTPException) as error:
        asyncio.run(upload(File(),user['id'],{'.docx'},100,db))
    assert error.value.status_code == 401
    assert not path.parent.exists()


def test_queue_does_not_starve_after_fifty_blocked_jobs(client, user, monkeypatch):
    from app.db import User, engine
    from sqlalchemy import text
    from app.worker import run_once
    from concurrent.futures import ThreadPoolExecutor
    with Session.begin() as db:
        other = User(email='unblocked@example.invalid',password_hash='disabled')
        db.add(other)
        db.flush()
        for i in range(50):
            db.add(Job(owner_id=user['id'],kind='queue_fixture',request_key=str(i),payload={}))
        db.flush()
        last = Job(owner_id=other.id,kind='queue_fixture',request_key='last',payload={})
        db.add(last)
        db.flush()
    monkeypatch.setitem(tasks.HANDLERS,'queue_fixture',lambda job: {})
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key':'user:'+user['id']})
        try:
            assert run_once()
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key':'user:'+user['id']})
            connection.commit()
    with Session() as db:
        assert db.get(Job,last.id).status == 'completed'


def test_b19_deleted_initiator_does_not_release_shared_identity(client, user):
    from app.db import User
    from fastapi import HTTPException
    with Session() as db:
        enqueue(db,user['id'],'index_knowledge',{'record_id':'shared','version':1},'index')
        db.delete(db.get(User,user['id']))
        db.commit()
        with pytest.raises(HTTPException) as error:
            enqueue(db,'other','index_knowledge',{'record_id':'shared','version':1},'again')
        assert error.value.status_code == 409


def test_large_single_rank_input_is_partitioned_without_truncation(client, user, monkeypatch):
    resume, vac = cv(client), vacancy(client)
    long_facts = {**FACTS, 'experience':['Опыт ' * 900 for _ in range(10)]}
    long_description = 'Разработка Python и SQL. ' * 1600
    with Session.begin() as db:
        row=db.get(Record,resume['id']);row.data={**row.data,'facts':long_facts}
        row=db.get(Record,vac['id']);row.data={**row.data,'description':long_description}
    inputs=[]
    def generate(*args):
        from app.large_inputs import byte_size
        assert byte_size(args[3]) < 80000
        inputs.append({'step':args[1],**args[3]})
        return fake_structured(*args)
    monkeypatch.setattr(ai,'structured',generate)
    result=finish(client,client.post(P+'/vacancies/rank',json={'cv_id':resume['id'],'vacancy_ids':[vac['id']]}))
    assert result['count']==1 and len(inputs)>1
    # Every description partition and every repeated fact is represented.
    descriptions=[x['vacancies'][0]['description'] for x in inputs if x['step'].endswith('-f0')]
    assert ''.join(descriptions)==long_description
    assert sum(len(x['facts'].get('experience',[])) for x in inputs)>=10


@pytest.mark.parametrize('provider',['openai','gemini'])
@pytest.mark.parametrize('outcome',['success','refusal','rejected','unknown'])
def test_provider_contract_accounting_and_replay(client,user,monkeypatch,provider,outcome):
    from app.providers import RequestRejected
    from app.providers.registry import text_adapter
    from app.costs import Cost
    from app.db import Usage
    monkeypatch.setattr(settings,'text_provider',provider)
    monkeypatch.setattr(settings,'openai_api_key','synthetic')
    monkeypatch.setattr(settings,'gemini_api_key','synthetic')
    monkeypatch.setattr(settings,'gemini_free_tier',False)
    calls=[]
    def generate(*args):
        calls.append(1)
        if outcome=='rejected':raise RequestRejected('Explicit rejection')
        if outcome=='unknown':raise TimeoutError()
        return ({'_provider_error':'Refusal'} if outcome=='refusal' else FACTS), Cost(.001,{'method':'contract-fixture'})
    from app.providers import openai_text,gemini
    monkeypatch.setattr(openai_text if provider=='openai' else gemini,'generate',generate)
    with Session.begin() as db:
        job=Job(owner_id=user['id'],kind='contract',request_key=uid(),payload={})
        db.add(job);db.flush()
    expected={'refusal':ValueError,'rejected':ai.Paused,'unknown':ai.Uncertain}
    def invoke():return ai.structured(job.id,'step','Extract facts',{'cv':'synthetic'},CVFacts)
    if outcome=='success':assert invoke().skills==FACTS['skills']
    else:
        with pytest.raises(expected[outcome]):invoke()
    with Session() as db:
        usage=db.get(Usage,job.id+':step')
        assert usage.state=={'success':'completed','refusal':'completed','rejected':'rejected','unknown':'uncertain'}[outcome]
    if outcome!='rejected':
        if outcome=='success':invoke()
        else:
            with pytest.raises(expected[outcome]):invoke()
        assert len(calls)==1


def test_b19_concurrent_administrators_share_one_index_job(client,user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.db import User
    from app.workflows.queue import submit_job
    with Session.begin() as db:
        other=User(email='concurrent-admin@example.invalid',password_hash='disabled');db.add(other);db.flush()
    gate=Barrier(2)
    def enqueue_index(owner):
        with Session() as db:
            gate.wait(timeout=3)
            return submit_job(db,owner,'index_knowledge',{'record_id':'shared','version':7},uid())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(enqueue_index,[user['id'],other.id]))
    assert results[0]==results[1]
    with Session() as db:
        assert len(db.scalars(select(Job)).all())==1


def test_large_document_partitions_keep_source_ids_and_checkpoint_steps(client,user,monkeypatch):
    from app.schemas import DocumentResult,DocumentFragment,DocumentReview,FragmentReview
    resume,vac=cv(client),vacancy(client)
    with Session.begin() as db:
        row=db.get(Record,resume['id']);row.data={**row.data,'facts':{**FACTS,'experience':['Опыт '+str(i)+' '+('разработка '*350) for i in range(10)]}}
        row=db.get(Record,vac['id']);row.data={**row.data,'description':'Python разработка. '*1800}
    seen=[]
    def generate(job,step,instruction,data,schema):
        from app.large_inputs import byte_size
        assert byte_size(data)<80000
        seen.append(step)
        if schema is DocumentResult:
            ids=list(data['facts'])
            return DocumentResult(title='Synthetic',introduction='',closing='',selected_fact_ids=ids,changes=[],
                fragments=[DocumentFragment(fact_ids=[key],text=data['facts'][key]) for key in ids])
        return DocumentReview(fragments=[FragmentReview(index=f['index'],supported=True,issues=[]) for f in data['fragments']])
    monkeypatch.setattr(ai,'structured',generate)
    result=finish(client,client.post(P+'/documents',json={'cv_id':resume['id'],'vacancy_id':vac['id'],'kind':'adapted_cv','language':'ru'}))
    data=client.get(P+'/record/'+result['record_id']).json()['data']
    assert len([k for k in data['selected_fact_ids'] if k.startswith('experience:')])==10
    assert any(step.startswith('document-part-') for step in seen)


def test_translation_inherits_source_timestamps_for_editor(client):
    register(client,'owner@example.com')
    mid,ids=knowledge(client)
    with Session.begin() as db:
        original=db.get(Record,ids[0]);original.data={**original.data,'sources':[{'video_id':'zibAC8HkGFk','start':1.5,'end':15.25}]}
    row=client.post(P+'/admin/questions',json={**QUESTION,'language':'en','material_ids':[mid],'translation_of':ids[0]}).json()
    published=client.post(P+'/admin/publish/'+row['id'])
    assert published.status_code==200
    data=published.json()['record']['data']
    assert data['start']==1.5 and data['end']==15.25
