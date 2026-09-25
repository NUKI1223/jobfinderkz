"""One durable Linux ledger for live checks across main/test databases.

Mount the same storage volume everywhere. A crash retains the reservation.
The separate lock inode plus atomic replace prevents truncated ledger recovery.
"""
import fcntl
import json
import os
from decimal import Decimal
from .config import settings


def update(key, ceiling=None, actual=None):
    if not settings.live_check_mode:
        return
    from .ai import Paused, Uncertain
    path = settings.live_check_ledger
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = json.loads(path.read_text()) if path.exists() else {}
        if ceiling is not None:
            if key in entries and entries[key]['state'] != 'rejected':
                raise Uncertain('Контрольный запрос уже учтён в общем журнале; нужна сверка.')
            total = sum(Decimal(e['amount']) for e in entries.values())
            if total + Decimal(str(ceiling)) > Decimal(str(settings.live_check_budget_usd)):
                raise Paused('Общий бюджет контрольных вызовов $2 исчерпан.')
            entries[key] = {'amount': str(ceiling), 'state': 'reserved'}
        else:
            entries[key] = {'amount': str(actual), 'state': 'rejected' if actual == 0 else 'completed'}
        temporary = path.with_suffix('.tmp')
        with open(temporary, 'w') as output:
            json.dump(entries, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
