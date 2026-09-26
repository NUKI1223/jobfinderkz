"""Import a manually reviewed, source-linked question batch without provider calls.

Usage: python -m app.import_reviewed_bank [--apply] < reviewed-batch.json
Dry-run is the default. Apply is additive and idempotent; it never edits prior cards.
"""
import argparse
import hashlib
import json
import sys
from urllib.parse import urlparse

from sqlalchemy import select, text

from .db import Knowledge, Record, Session, now
from .revisions import fingerprint
from .schemas import QuestionInput


TRUSTED_DOC_HOSTS = {'developer.mozilla.org', 'www.postgresql.org', 'docs.stripe.com',
    'docs.python.org', 'react.dev', 'playwright.dev', 'docs.pytest.org',
    'www.rfc-editor.org', 'docs.sqlalchemy.org', 'wstg.owasp.org',
    'istqb.org', 'www.typescriptlang.org', 'www.selenium.dev',
    'bugzilla.mozilla.org', 'coverage.readthedocs.io'}


def import_batch(batch: dict, *, apply: bool = False, sessions=Session) -> dict:
    batch_id = batch['batch']
    if not isinstance(batch_id, str) or not batch_id.startswith('reviewed-'):
        raise ValueError('A stable reviewed-* batch identifier is required')
    materials = batch['materials']
    questions = batch['questions']
    if not materials or not questions or len({m['key'] for m in materials}) != len(materials) or len({q['key'] for q in questions}) != len(questions):
        raise ValueError('Batch needs unique material and question keys')
    with sessions.begin() as db:
        if apply:
            db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': 'knowledge-edit'})
        source = None
        source_kind = batch.get('source_kind', 'video')
        if source_kind not in ('video', 'documentation'):
            raise ValueError('Unknown source kind')
        if source_kind == 'video':
            source = db.scalar(select(Record).where(Record.kind == 'source', Record.owner_id.is_(None),
                Record.data['video_id'].as_string() == batch['video_id']))
            if source is None or not source.data.get('transcript'):
                raise ValueError('Saved transcript for source video is required')
            segments = source.data['transcript']['segments']
            if not segments:
                raise ValueError('Source transcript is empty')
            max_end = max(s['end'] for s in segments)
        elif not batch.get('review_method'):
            raise ValueError('Documentation review method is required')
        material_versions = {}
        material_ids, created_materials, created_questions = {}, 0, 0
        for item in materials:
            url = item['url']
            if urlparse(url).scheme != 'https' or urlparse(url).hostname not in TRUSTED_DOC_HOSTS:
                raise ValueError(f'Unapproved documentation URL: {url}')
            if len(item['text'].strip()) < 40:
                raise ValueError(f'Material {item["key"]} is too short')
            dedup = fingerprint([url, batch['direction'], batch['level'], batch['language']] +
                ([item['text']] if source_kind == 'documentation' else []))
            row = db.scalar(select(Record).where(Record.kind == 'material', Record.owner_id.is_(None), Record.dedup_key == dedup))
            if row and row.status != 'published':
                raise ValueError(f'Material {item["key"]} exists but is not published')
            if row is None:
                created_materials += 1
                if apply:
                    row = Record(kind='material', status='published', dedup_key=dedup, data={
                        'url': url, 'title': item['title'], 'text': item['text'],
                        'direction': batch['direction'], 'level': batch['level'], 'language': batch['language'],
                        'version': 1, 'reviewed_at': now().isoformat(), 'review_note': item['review_note'],
                        'import_batch': batch_id})
                    db.add(row)
                    db.flush()
                    db.add(Knowledge(record_id=row.id, text=item['text'], direction=batch['direction'],
                        level=batch['level'], language=batch['language']))
            material_ids[item['key']] = row.id if row else None
            if row:
                material_versions[row.id] = row.data.get('version', 1)
        for item in questions:
            if source_kind == 'video':
                if not 0 <= item['start'] < item['end'] <= max_end + 1:
                    raise ValueError(f'Invalid source interval for {item["key"]}')
                if not any(s['start'] < item['end'] and s['end'] > item['start'] for s in segments):
                    raise ValueError(f'No transcript segments for {item["key"]}')
            elif item.get('start', 0) or item.get('end', 0) or item.get('candidate_answer') or item.get('interviewer_notes'):
                raise ValueError('Documentation questions must not invent video discussion')
            if not item.get('roles') or not item.get('review_note'):
                raise ValueError(f'Review context missing for {item["key"]}')
            if not item.get('material_keys') or any(key not in material_ids for key in item['material_keys']):
                raise ValueError(f'Unknown material for {item["key"]}')
            data = {key: value for key, value in item.items() if key in QuestionInput.model_fields}
            data.update(direction=batch['direction'], level=batch['level'], language=batch['language'],
                material_ids=[material_ids[key] for key in item['material_keys']] if apply else ['dry-run'] * len(item['material_keys']),
                needs_context=False, translation_of=None)
            question = QuestionInput.model_validate(data)
            if len(question.reference_answer) < 30 or len(question.rubric) < 3:
                raise ValueError(f'Incomplete answer or rubric for {item["key"]}')
            identity = source.id if source else ':'.join([batch['direction'], batch['language'], 'documentation'])
            dedup = hashlib.sha256((identity + question.question.strip().lower()).encode()).hexdigest()
            existing = db.scalar(select(Record).where(Record.kind == 'question', Record.owner_id.is_(None), Record.dedup_key == dedup))
            if existing and existing.data.get('import_batch') != batch_id:
                raise ValueError(f'Question already exists outside batch: {item["key"]}')
            if existing and existing.data.get('import_digest') and existing.data['import_digest'] != fingerprint(item):
                raise ValueError(f'Batch content changed: {item["key"]}; edit through review instead')
            if existing is None:
                created_questions += 1
                if apply:
                    qdata = {**question.model_dump(), 'version': 1, 'reviewed_at': now().isoformat(),
                        'review_note': item['review_note'], 'import_batch': batch_id,
                        'import_digest': fingerprint(item), 'source_kind': source_kind,
                        'review_method': batch.get('review_method', ''),
                        'material_versions': {material_ids[key]: material_versions[material_ids[key]] for key in item['material_keys']},
                        'sources': [{'source_id': source.id, 'video_id': batch['video_id'],
                            'start': item['start'], 'end': item['end']}] if source else []}
                    row = Record(kind='question', status='published', dedup_key=dedup, data=qdata)
                    db.add(row)
                    db.flush()
                    db.add(Knowledge(record_id=row.id,
                        text=question.question + '\n' + question.reference_answer + '\n' + ' '.join(question.rubric),
                        direction=question.direction, level=question.level, language=question.language))
        return {'batch': batch_id, 'applied': apply, 'new_materials': created_materials,
            'new_questions': created_questions, 'source_video': batch.get('video_id')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit reviewed records')
    args = parser.parse_args()
    print(json.dumps(import_batch(json.load(sys.stdin), apply=args.apply), ensure_ascii=False))


if __name__ == '__main__':
    main()
