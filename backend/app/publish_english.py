"""Idempotent admin API import of the five reviewed English translations."""
import json
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import select
from .db import Session, User, Login, Record
from .security import new_session, digest
from .main import app


def main():
    entries = json.loads(Path(sys.argv[1]).read_text())
    with Session() as db:
        owner = db.scalar(select(User).where(User.role == 'admin'))
        if owner is None:
            raise SystemExit('No admin account available')
        response = Response()
        identity = new_session(db, owner, response)
    cookie = SimpleCookie()
    cookie.load(response.headers['set-cookie'])
    token = cookie['jf_session'].value
    created = 0
    try:
        with TestClient(app, headers={'X-CSRF-Token': identity['csrf']}, cookies={'jf_session': token}) as client:
            for item in entries:
                with Session() as db:
                    original = db.get(Record, item['translation_of'])
                    if not original or original.kind != 'question' or original.status != 'published':
                        raise ValueError('Unpublished translation source')
                    if db.scalar(select(Record).where(Record.kind == 'question',
                        Record.data['translation_of'].as_string() == original.id,
                        Record.data['language'].as_string() == 'en')):
                        continue
                    material = db.scalar(select(Record).where(Record.kind == 'material',
                        Record.data['url'].as_string() == item['url'],
                        Record.data['language'].as_string() == 'en'))
                if not material:
                    with Session.begin() as db:
                        material = Record(kind='material', data={'url': item['url'], 'title': item['topic'] + ' — Python documentation',
                            'text': item['reference_answer'], 'direction': 'python', 'level': 'junior',
                            'language': 'en', 'review_scope': 'Official Python documentation and reference summary checked 2026-09-25',
                            'version': 1})
                        db.add(material)
                        db.flush()
                        material_id = material.id
                    published = client.post('/api/v1/admin/publish/' + material_id)
                    published.raise_for_status()
                else:
                    material_id = material.id
                question = {'question': item['question'], 'topic': item['topic'], 'direction': 'python',
                    'level': 'junior', 'language': 'en', 'reference_answer': item['reference_answer'],
                    'rubric': item['rubric'], 'material_ids': [material_id], 'needs_context': False,
                    'translation_of': original.id, 'roles': original.data.get('roles', ''),
                    'start': original.data.get('start', 0), 'end': original.data.get('end', 0)}
                draft = client.post('/api/v1/admin/questions', json=question)
                draft.raise_for_status()
                published = client.post('/api/v1/admin/publish/' + draft.json()['id'])
                published.raise_for_status()
                created += 1
    finally:
        with Session.begin() as db:
            db.delete(db.get(Login, digest(token)))
    print('Reviewed English translations published:', created)


if __name__ == '__main__':
    main()
