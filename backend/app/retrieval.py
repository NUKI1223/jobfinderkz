"""Knowledge selection with partial lexical matches and current reviewed evidence."""
import re
from sqlalchemy import select, text as sql
from .db import Record, Knowledge


def lexical_query(value):
    words = list(dict.fromkeys(re.findall(r'[\w]+', value.lower(), flags=re.UNICODE)))
    return ' | '.join(words[:200]) or 'emptyquery'


def retrieve(db, query, direction, level, language, limit=12, embedding=None, kind=None):
    params = {'query': lexical_query(query), 'direction': direction, 'level': level, 'language': language, 'kind': kind}
    rows = db.execute(sql("""
        SELECT k.record_id, ts_rank_cd(to_tsvector('simple', k.text), to_tsquery('simple', :query)) AS rank
        FROM knowledge k JOIN records r ON r.id=k.record_id
        WHERE r.status='published' AND k.direction=:direction AND k.level=:level AND k.language=:language
        AND (CAST(:kind AS text) IS NULL OR r.kind=:kind)
        ORDER BY rank DESC, k.record_id
    """), params).all()
    scores = {r.record_id: (1 / (60 + i) if r.rank > 0 else 0) for i, r in enumerate(rows)}
    if embedding is not None:
        vectors = db.scalars(select(Knowledge).join(Record, Record.id == Knowledge.record_id)
            .where(Record.status == 'published', Knowledge.direction == direction, Knowledge.level == level,
                   Knowledge.language == language, Knowledge.embedding.is_not(None),
                   Record.kind == kind if kind else True)
            .order_by(Knowledge.embedding.cosine_distance(embedding)).limit(limit)).all()
        for i, row in enumerate(vectors):
            scores[row.record_id] = scores.get(row.record_id, 0) + 1 / (60 + i)
    results = []
    for key in sorted(scores, key=scores.get, reverse=True):
        record = db.get(Record, key)
        if record.kind == 'question' and not evidence(db, record.data):
            continue
        results.append(record)
        if len(results) == limit:
            break
    return results


def canonical(question):
    return question.data.get('translation_of') or question.id


def practiced_questions(db, owner_id):
    history = {}
    for interview in db.scalars(select(Record).where(Record.kind == 'interview', Record.owner_id == owner_id)
                               .order_by(Record.created_at)):
        for turn in interview.data.get('turns', []):
            evaluation = turn.get('evaluation')
            if evaluation:
                scores = [evaluation.get(k) for k in ('correctness', 'completeness', 'reasoning')]
                key = turn.get('question', {}).get('translation_of') or turn['question_id']
                history[key] = sum(scores) / 3 if evaluation.get('reliable') and all(s is not None for s in scores) else 0
    return history


def prioritize_questions(rows, history):
    unique = {canonical(q): q for q in rows}
    return sorted(unique.values(), key=lambda q: (canonical(q) in history, history.get(canonical(q), 0)))


def evidence(db, question):
    if question.get('translation_of'):
        original = db.get(Record, question['translation_of'])
        if not original or original.status != 'published' or question.get('translation_version', original.data.get('version', 1)) != original.data.get('version', 1):
            return []
    ids = question.get('material_ids', [])
    records = db.scalars(select(Record).where(Record.id.in_(ids),
        Record.kind == 'material', Record.status == 'published')).all()
    if not ids or len(records) != len(set(ids)):
        return []
    versions = question.get('material_versions', {})
    if any(str(r.id) in versions and versions[r.id] != r.data.get('version', 1) for r in records):
        return []
    return [{'id': r.id, 'version': r.data.get('version', 1), 'url': r.data['url'], 'text': r.data['text'][:10000]} for r in records]


def lexical_relevant(db, record, query):
    item = db.get(Knowledge, record.id)
    terms = set(re.findall(r'[\w]+', query.lower(), flags=re.UNICODE))
    return bool(item and terms.intersection(re.findall(r'[\w]+', item.text.lower(), flags=re.UNICODE)))
