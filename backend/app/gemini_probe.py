"""Explicit live smoke test; synthetic input only, isolated test database."""
from . import ai
from .config import settings
from .db import Session, User, Job, engine, uid
from .schemas import CVFacts


def main():
    assert engine.url.database == 'jobfinder_test', 'Probe requires jobfinder_test'
    assert settings.text_provider == 'gemini' and settings.gemini_api_key
    with Session.begin() as db:
        user = User(email=f'probe-{uid()}@example.invalid', password_hash='login-disabled')
        db.add(user)
        db.flush()
        job = Job(owner_id=user.id, kind='parse_cv', request_key=uid(), payload={})
        db.add(job)
        db.flush()
        user_id, job_id = user.id, job.id
    try:
        result = ai.structured(job_id, 'facts', 'Extract only explicit facts. Use empty arrays for missing sections.',
            {'text': 'Fictional test resume. Skills: Python, SQL. Projects: educational task tracker. Languages: English B1.'}, CVFacts)
        assert any('Python' in skill for skill in result.skills)
        assert not result.experience and not result.education
        print('LIVE GEMINI PASS: schema validated, skills extracted, absent experience/education empty')
    except (ai.Paused, ai.Uncertain) as exc:
        print(f'LIVE GEMINI INCOMPLETE: {exc}')
        raise SystemExit(2) from None
    finally:
        with Session.begin() as db:
            db.delete(db.get(User, user_id))


if __name__ == '__main__':
    main()
