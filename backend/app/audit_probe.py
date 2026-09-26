"""Opt-in bounded audit checks: fictional CV + synthetic speech, never truncates DB."""
import json
import subprocess
from sqlalchemy.engine import make_url
from .config import settings

settings.database_url = make_url(settings.database_url).set(database='jobfinder_test').render_as_string(hide_password=False)
settings.live_check_mode = True
settings.text_provider = 'openai'

from sqlalchemy import select
from .db import Session, User, Job, Usage
from . import ai
from .schemas import CVFacts
from .probe_checks import speech_terms, exit_status


def main():
    with Session.begin() as db:
        owner=db.scalar(select(User).where(User.email=='synthetic-live-probe@example.invalid'))
        if owner is None:
            owner=User(email='synthetic-live-probe@example.invalid',password_hash='login-disabled',profile={})
            db.add(owner);db.flush()
        job=db.scalar(select(Job).where(Job.owner_id==owner.id,Job.request_key=='audit-live-v1'))
        if job is None:
            job=Job(owner_id=owner.id,kind='live_probe',request_key='audit-live-v1',payload={},status='paused')
            db.add(job);db.flush()
        jid=job.id
    report={'synthetic':True,'checks':{},'cached_checks':{}}
    try:
        facts=ai.structured(jid,'date-facts','Extract explicitly stated CV facts. Preserve exact factual wording and dates. '
            'Do not invent facts. Remove contact details.', {'cv':'Fictional Python developer. Experience: built a synthetic task tracker '
            'from 2020-01-01 to 2024-01-01. Skills: Python, SQL. Phone: +7 (777) 123-45-67.'},CVFacts)
        rendered=json.dumps(facts.model_dump(),ensure_ascii=False)
        report['checks']['dates_preserved']=all(d in rendered for d in ['2020-01-01','2024-01-01'])
        report['checks']['phone_excluded']='777' not in rendered
        path=settings.storage_path/'live-fixtures'/'synthetic-en.wav'
        if path.exists():
            duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
                '-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True))
            transcript=ai.transcribe(jid,'english-technical-terms',path,duration)
            report['checks']['english_technical_terms']=speech_terms(transcript.get('text',''),['python','function','context'])
        else:
            report['checks']['english_technical_terms']='skipped_missing_fixture'
        # Audit previously paid Russian response without paying again. The reference
        # synthetic sentence names enter/exit; a misspelling is a quality failure.
        with Session() as db:
            previous=db.scalar(select(Job).where(Job.request_key=='openai-live-v1',Job.owner_id==owner.id))
            russian=previous.checkpoints.get('speech-ru') if previous else None
        report['cached_checks']['russian_technical_terms']=(speech_terms(russian.get('text',''),['контекст','энтер','экзит'])
            if russian else 'skipped_missing_checkpoint')
        report['checks']['cached_russian_technical_terms']=report['cached_checks']['russian_technical_terms']
    except (ai.Paused,ai.Uncertain,ValueError) as exc:
        report['stopped']=str(exc)
    with Session() as db:
        rows=db.scalars(select(Usage).where(Usage.key.like(jid+':%'))).all()
        report['calculated_usd']=float(sum(u.actual or 0 for u in rows))
        report['open_reservations_usd']=float(sum(u.reserved for u in rows if u.state in ('reserved','uncertain')))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return exit_status(report)


if __name__=='__main__':
    raise SystemExit(main())
