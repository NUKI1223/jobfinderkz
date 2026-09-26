from sqlalchemy import select, func
from app.db import Session, Record, Job, Usage
from .conftest import register


def seed():
    with Session() as db:
        m = Record(kind='material', status='published', data={'url':'https://docs.python.org/3/', 'text':'Reviewed material', 'version':1})
        db.add(m); db.flush()
        data = dict(question='Explain Python iteration', topic='iteration', direction='python', level='junior', language='ru',
                    reference_answer='Reviewed explanation of iteration and iterators.', rubric=['one','two','three'], task='Implement an iterator',
                    material_ids=[m.id], material_versions={m.id:1}, version=1, candidate_answer='PRIVATE', interviewer_notes='PRIVATE')
        q = Record(kind='question', status='published', data=data)
        db.add(q); db.flush()
        en = Record(kind='question', status='published', data={**data,'language':'en','translation_of':q.id,'translation_version':1})
        draft = Record(kind='question', status='draft', data=data)
        empty = Record(kind='question', status='published', data={**data,'task':'  ','topic':'empty'})
        stale = Record(kind='question', status='published', data={**data,'material_versions':{m.id:2}})
        db.add_all([en,draft,empty,stale]); db.commit()
        return q.id,en.id,m.id


def get(client, id, mode='question'):
    r=client.get(f'/api/v1/study/items/{id}?mode={mode}');assert r.status_code==200,r.text;return r.json()


def save(client, id, card, answer='my answer', status='done', mode='question'):
    return client.put(f'/api/v1/study/items/{id}/progress?mode={mode}', headers={'If-Match':card['progress']['revision']},
        json={'answer':answer,'status':status,'content_version':card['content_version']})


def test_catalog_access_filters_and_pagination(client,user):
    q,en,m=seed()
    url='/api/v1/study/items?direction=python&level=junior&language=ru'
    data=client.get(url).json();assert data['total']==2
    assert client.get(url+'&mode=task').json()['total']==1
    assert client.get(url+'&topic=empty').json()['total']==1
    assert client.get(url+'&search=missing').json()['total']==0
    assert client.get(url+'&status=done').json()['total']==0
    assert client.get(url.replace('python','qa')).json()['total']==0
    assert 'PRIVATE' not in str(get(client,q))
    with Session() as db:
        template=db.get(Record,q).data
        db.add_all([Record(kind='question',status='published',data=template) for _ in range(23)]);db.commit()
    first=client.get(url).json();second=client.get(url+'&offset=20').json()
    assert len(first['items'])==20 and first['next_offset']==20
    assert len(second['items'])==5 and second['next_offset'] is None
    assert not set(i['id'] for i in first['items']) & set(i['id'] for i in second['items'])
    client.post('/api/v1/auth/logout');assert client.get(url).status_code==401


def test_progress_languages_modes_owners_conflicts_and_no_cost(client,user):
    q,en,m=seed();ru=get(client,q)
    assert save(client,q,ru).status_code==200
    assert save(client,q,ru,answer='stale').status_code==409
    eng=get(client,en);assert eng['progress']['status']=='done' and eng['progress']['answer']==''
    assert save(client,en,eng,answer='English draft',status='repeat').status_code==200
    ru=get(client,q);assert ru['progress']['answer']=='my answer' and ru['progress']['status']=='repeat'
    task=get(client,q,'task');assert task['progress']['status']=='new' and task['task_solution']==''
    assert save(client,q,task,answer='code',mode='task').status_code==200
    assert get(client,q)['progress']['status']=='repeat'
    client.post('/api/v1/auth/logout');register(client,'other@example.com')
    assert get(client,q)['progress']['answer']==''
    assert save(client,q,ru).status_code==409
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Job))==0
        assert db.scalar(select(func.count()).select_from(Usage))==0


def test_updated_content_preserves_old_answer_and_history(client,user):
    q,en,m=seed();assert save(client,q,get(client,q)).status_code==200
    old=get(client,q)
    with Session() as db:
        row=db.get(Record,q);row.data={**row.data,'task_solution':'Reviewed solution','version':2};db.commit()
    updated=get(client,q)
    assert updated['progress']['updated'] and updated['progress']['status']=='new'
    assert updated['progress']['answer']=='my answer'
    assert save(client,q,old).status_code==409
    assert client.get('/api/v1/study/items?language=ru&status=done').json()['total']==0
    saved=save(client,q,updated,answer='revised').json()
    assert saved['progress']['history'][0]['answer']=='my answer'
    assert not saved['progress']['updated']
    with Session() as db:
        row=db.get(Record,m);row.data={**row.data,'version':2};db.commit()
    assert client.get(f'/api/v1/study/items/{q}').status_code==404
    assert save(client,q,saved).status_code==409


def test_account_deletion_cascades_study(client,user):
    q,en,m=seed();assert save(client,q,get(client,q)).status_code==200
    response=client.delete('/api/v1/account')
    assert response.status_code==200,response.text
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Record).where(Record.kind=='study_progress'))==0


def test_concurrent_first_save_and_publish_solution(client,user):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from app.main import app
    q,en,m=seed();card=get(client,q)
    def attempt(answer):
        with TestClient(app) as other:
            other.cookies.update(client.cookies)
            other.headers['x-csrf-token']=client.headers['x-csrf-token']
            return save(other,q,card,answer=answer).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,['first','second']))
    assert sorted(results)==[200,409]
    client.post('/api/v1/auth/logout');register(client,'owner@example.com')
    with Session() as db:
        row=db.get(Record,q)
        body={k:v for k,v in row.data.items() if k in __import__('app.schemas',fromlist=['QuestionInput']).QuestionInput.model_fields}
    body.update(task_solution='A reviewed practical solution.',needs_context=False)
    edited=client.put(f'/api/v1/admin/questions/{q}',json=body)
    assert edited.status_code==200,edited.text
    assert client.get(f'/api/v1/study/items/{q}').status_code==404
    published=client.post(f'/api/v1/admin/publish/{q}')
    assert published.status_code==200,published.text
    assert get(client,q,'task')['task_solution']=='A reviewed practical solution.'
