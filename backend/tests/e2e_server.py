"""Isolated browser-test server. Never imported by the production entry point.

External AI responses are fixed here; actual API, DB, sessions and worker run.
"""
import threading
import time
import uvicorn
from sqlalchemy import text
from app.db import engine, Session, Record, Knowledge
from app.main import app
from app.config import settings
from app import ai, tasks
from app.schemas import CVFacts, DocumentResult, Ranking, Evaluation, ExtractedQuestions, QuestionInput
from app.worker import run_once

assert engine.url.database == 'jobfinder_test'
settings.admin_email = 'owner@example.com'
settings.openai_api_key = 'e2e-fixed-provider'
settings.gemini_api_key = ''
settings.text_provider = 'openai'
settings.hh_access_token = 'e2e-fixed-provider'


def fixed_response(job_id, step, instruction, data, schema):
    if schema is CVFacts:
        return CVFacts(summary='Разработчик Python', skills=['Python', 'SQL'], experience=['Учебный проект'],
                       education=['Курс Python'], projects=['Трекер задач'], languages=['Русский'])
    if schema is DocumentResult:
        return DocumentResult(title='Сопроводительное письмо', introduction='', selected_fact_ids=['skills:0', 'projects:0'],
                              closing='', changes=['Выделены навыки Python и учебный проект'])
    if schema is Ranking:
        return Ranking(matches=[{'vacancy_id': v['id'], 'score': 75, 'reasons': ['Подходит опыт Python'],
             'matching_skills': ['Python'], 'missing_skills': ['pytest']} for v in data['vacancies']])
    if schema is Evaluation:
        return Evaluation(reliable=True, correctness=3, completeness=3, reasoning=2, feedback='Добавьте конкретный пример.',
                          errors=[], missing_points=['Пример'], improved_answer='Транзакция объединяет изменения: commit фиксирует их, rollback отменяет.')
    if schema is ExtractedQuestions:
        return ExtractedQuestions(questions=[QuestionInput(question='Что означает rollback в транзакции?',
            candidate_answer='Фиксирует изменения.', interviewer_notes='Нет, отменяет изменения.',
            topic='Транзакции', direction='python', level='junior', language='ru', start=1, end=15,
            needs_context=True, roles='Кандидат и интервьюер требуют проверки')])
    raise AssertionError(schema)


ai.structured = fixed_response
ai.embed = lambda *args, **kwargs: [0.01] * 1536
ai.transcribe = lambda *args, **kwargs: {'text': 'Транзакция фиксирует все изменения вместе или откатывает их.'}


def fixed_hh(job):
    tasks.result_record(job, 'vacancy', {'title': 'Python developer', 'company': 'Example team',
        'description': 'Python, SQL и PostgreSQL. Разработка сервисов, транзакции и автоматические тесты.',
        'direction': job.payload['direction'], 'level': job.payload['level'], 'region': 'Казахстан',
        'work_format': 'remote', 'source': 'hh', 'favorite': False}, 'saved')
    return {'count': 1}


tasks.HANDLERS['hh_sync'] = fixed_hh


def seed():
    with engine.begin() as connection:
        connection.execute(text('TRUNCATE users, records, jobs, knowledge, sessions, usage, budgets CASCADE'))
    with Session.begin() as db:
        material = Record(kind='material', status='published', data={'url': 'https://docs.python.org/3/library/sqlite3.html',
            'title': 'TEST FIXTURE — Transactions', 'text': 'A transaction commits or rolls back all changes together.',
            'direction': 'python', 'level': 'junior', 'language': 'ru'})
        db.add(material)
        db.flush()
        for i in range(5):
            q = Record(kind='question', status='published', data={'question': f'Вопрос {i+1}: как работает транзакция?',
                'topic': 'Транзакции', 'direction': 'python', 'level': 'junior', 'language': 'ru',
                'reference_answer': 'Транзакция объединяет изменения: commit фиксирует их, rollback отменяет.',
                'rubric': ['Атомарность', 'Commit', 'Rollback'], 'material_ids': [material.id],
                'version': 1, 'sources': [], 'task': '', 'needs_context': False})
            db.add(q)
            db.flush()
            db.add(Knowledge(record_id=q.id, text=q.data['question'], direction='python', level='junior', language='ru'))


def worker():
    while True:
        run_once()
        time.sleep(.2)


if __name__ == '__main__':
    seed()
    threading.Thread(target=worker, daemon=True).start()
    uvicorn.run(app, host='0.0.0.0', port=8000)
