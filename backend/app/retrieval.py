from sqlalchemy import select, text as sql
from .db import Record, Knowledge


def retrieve(db, query, direction, level, language, limit=12, embedding=None):
    params = {'query': query[:2000], 'direction': direction, 'level': level, 'language': language, 'limit': limit}
    rows = db.execute(sql("""
        SELECT k.record_id, ts_rank_cd(to_tsvector('simple', k.text), plainto_tsquery('simple', :query)) AS rank
        FROM knowledge k JOIN records r ON r.id=k.record_id
        WHERE r.status='published' AND k.direction=:direction AND k.level=:level AND k.language=:language
        ORDER BY rank DESC, k.record_id LIMIT :limit
    """), params).all()
    scores = {r.record_id: 1 / (60 + i) for i, r in enumerate(rows)}
    if embedding is not None:
        vectors = db.scalars(select(Knowledge).join(Record, Record.id == Knowledge.record_id)
            .where(Record.status == 'published', Knowledge.direction == direction, Knowledge.level == level,
                   Knowledge.language == language, Knowledge.embedding.is_not(None))
            .order_by(Knowledge.embedding.cosine_distance(embedding)).limit(limit)).all()
        for i, row in enumerate(vectors):
            scores[row.record_id] = scores.get(row.record_id, 0) + 1 / (60 + i)
    return [db.get(Record, key) for key in sorted(scores, key=scores.get, reverse=True)[:limit]]


def evidence(db, question):
    records = db.scalars(select(Record).where(Record.id.in_(question.get('material_ids', [])),
        Record.kind == 'material', Record.status == 'published')).all()
    return [{'id': r.id, 'url': r.data['url'], 'text': r.data['text'][:10000]} for r in records]
