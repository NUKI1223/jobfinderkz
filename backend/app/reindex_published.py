"""Queue missing vectors for published knowledge; never retry uncertain paid steps."""
from sqlalchemy import select
from .db import Session, User, Job, Record, Knowledge
from .store import enqueue

with Session() as db:
    admin = db.scalar(select(User).where(User.role == 'admin'))
    if not admin:
        raise SystemExit('No admin account')
    rows = db.scalars(select(Record).join(Knowledge, Knowledge.record_id == Record.id)
        .where(Record.status == 'published', Knowledge.embedding.is_(None))).all()
    count = 0
    for row in rows:
        key = f'index:{row.id}:{row.data.get("version", 1)}:v2'
        if db.scalar(select(Job).where(Job.owner_id == admin.id, Job.request_key == key)):
            continue
        enqueue(db, admin.id, 'index_knowledge', {'record_id': row.id,
            'version': row.data.get('version', 1)}, key)
        count += 1
print('New indexing jobs queued:', count)
