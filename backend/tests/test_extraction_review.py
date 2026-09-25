from sqlalchemy import select

from app import ai, tasks
from app.db import Session, Record, Job
from app.schemas import ExtractedQuestions, QuestionInput
from app.worker import run_once


def test_missing_roles_require_review_and_resume_does_not_duplicate(user, monkeypatch):
    with Session.begin() as db:
        source = Record(kind='source', data={
            'video_id': 'zibAC8HkGFk', 'direction': 'python', 'level': 'junior', 'language': 'ru',
            'transcript': {'segments': [{'start': 10, 'end': 20, 'text': 'Is a list mutable? No.'}]}})
        db.add(source)
        db.flush()
        job = Job(owner_id=user['id'], kind='extract_questions', request_key='review-test',
                  payload={'source_id': source.id})
        db.add(job)
        db.flush()

    def fixed_response(*args):
        return ExtractedQuestions(questions=[QuestionInput(
            question='Is a list mutable?', candidate_answer='No.',
            topic='Mutability', direction='python', level='junior', language='ru',
            start=10, end=20, roles='  ', needs_context=False,
            reference_answer='Unreviewed answer', rubric=['Invented criterion'], material_ids=['fake'])])

    monkeypatch.setattr(ai, 'structured', fixed_response)
    assert run_once()
    with Session() as db:
        row = db.scalar(select(Record).where(Record.kind == 'question'))
        assert row.status == 'draft'
        assert row.data['needs_context'] is True
        assert row.data['candidate_answer'] == 'No.'
        assert row.data['reference_answer'] == ''
        assert row.data['rubric'] == [] and row.data['material_ids'] == []
        assert db.get(Job, job.id).status == 'completed'
        resumed = db.get(Job, job.id)
    assert tasks.extract_questions(resumed)['created'] == 0
