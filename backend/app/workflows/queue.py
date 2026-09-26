"""Queue submission transaction boundary for HTTP and maintenance actions."""
from ..store import enqueue


def submit_job(db, owner_id, kind, payload, request_key):
    result = enqueue(db, owner_id, kind, payload, request_key)
    db.commit()
    return result
