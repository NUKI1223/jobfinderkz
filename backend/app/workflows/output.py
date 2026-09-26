from sqlalchemy import select
from ..db import Session, Record



def result_record(job, kind, data, status='draft', *, sessions=Session):
    """Idempotent final output: one result record per job."""
    with sessions.begin() as db:
        row = db.scalar(select(Record).where(Record.owner_id == job.owner_id, Record.kind == kind, Record.dedup_key == job.id))
        if not row:
            row = Record(owner_id=job.owner_id, kind=kind, dedup_key=job.id, data=data, status=status)
            db.add(row)
            db.flush()
        return {'record_id': row.id}
