"""Opt-in live checks, synthetic data only, shared $2 ledger, jobfinder_test only.

Run in the API image with the SAME /storage volume as production:
  docker compose run --rm --no-deps api python -m app.openai_probe
Optional --audio-ru/--audio-en accept synthetic local speech fixtures.
Never import the fixture test server here; no database truncation occurs.
"""
import argparse
import json
import subprocess
from pathlib import Path
from sqlalchemy.engine import make_url
from .config import settings

settings.database_url = make_url(settings.database_url).set(database='jobfinder_test').render_as_string(hide_password=False)
settings.live_check_mode = True
settings.text_provider = 'openai'

from sqlalchemy import select
from .db import Session, User, Job, Usage
from . import ai
from .schemas import CVFacts, Evaluation, DocumentResult, DocumentReview
from .documents import fragment_issues
from .probe_checks import exit_status, speech_terms


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio-ru', type=Path)
    parser.add_argument('--audio-en', type=Path)
    parser.add_argument('--expected-ru', default='python,функц,контекст', help='Comma-separated expected technical terms/stems in synthetic RU fixture')
    parser.add_argument('--expected-en', default='python,function,context', help='Expected technical terms/stems in synthetic EN fixture')
    parser.add_argument('--documents-only', action='store_true', help='Resume only steps not previously attempted after an unknown result')
    args = parser.parse_args()
    if not settings.openai_api_key:
        raise SystemExit('OPENAI_API_KEY is missing')
    with Session.begin() as db:
        owner = db.scalar(select(User).where(User.email == 'synthetic-live-probe@example.invalid'))
        if not owner:
            owner = User(email='synthetic-live-probe@example.invalid', password_hash='login-disabled', profile={})
            db.add(owner)
            db.flush()
        job = db.scalar(select(Job).where(Job.owner_id == owner.id, Job.request_key == 'openai-live-v1'))
        if not job:
            job = Job(owner_id=owner.id, kind='live_probe', request_key='openai-live-v1', payload={}, status='paused')
            db.add(job)
            db.flush()
        job_id = job.id
    report = {'provider': 'openai', 'model': settings.text_model, 'synthetic': True, 'checks': {}}
    try:
        if not args.documents_only:
            facts = ai.structured(job_id, 'cv', 'Extract explicitly stated CV facts; no invented information.',
                {'text': 'Synthetic candidate. Python and SQL. Built a task tracker as a course project. No commercial experience.'}, CVFacts)
            report['checks']['text'] = 'Python' in ' '.join(facts.skills)
            vector = ai.embed(job_id, 'embedding', 'Python functions and context managers')
            report['checks']['embedding_dimensions'] = len(vector) == 1536
            rubric = ['Identifies __enter__ and __exit__', 'Explains cleanup after successful entry including exceptions',
                      'Explains truthy __exit__ return suppresses an exception']
            reference = ('A with statement calls __enter__, then __exit__ on leaving the block after successful entry. '
                '__exit__ gets exception information. A truthy return suppresses the exception; otherwise it propagates.')
            variants = {
                'en': ['It calls __enter__ first and always calls __exit__ after successful entry, including on exceptions. '
                       '__exit__ receives the exception; returning true suppresses it, otherwise it propagates.',
                       'After entering the resource via __enter__, leaving its block runs __exit__ for cleanup, even on failure. '
                       'That method gets error details and can swallow the error with a truthy return.',
                       'A with statement cleans up a resource.', 'It catches all exceptions automatically and never calls methods.'],
                'ru': ['with вызывает __enter__, а после успешного входа при выходе вызывает __exit__, в том числе при исключении. '
                       '__exit__ получает данные исключения; истинное возвращаемое значение подавляет его, иначе оно распространяется.',
                       'Сначала ресурс входит через __enter__. После удачного входа при завершении блока __exit__ освобождает ресурс, '
                       'даже при ошибке. Он получает информацию об ошибке и может поглотить её истинным результатом.',
                       'with помогает освободить ресурс.', 'with автоматически подавляет все ошибки и не вызывает методы.']}
            scores = {}
            for language, answers in variants.items():
                scores[language] = []
                for index, answer in enumerate(answers):
                    evaluation = ai.structured(job_id, f'evaluation-{language}-{index}',
                        'Score correctness, completeness and reasoning 0-4 using only evidence and rubric. '
                        'Accept paraphrases. No evidence means reliable=false and scores=null. Explain in requested language.',
                        {'question': 'How does the with statement work?', 'reference': reference, 'rubric': rubric,
                         'materials': [reference], 'answer': answer, 'language': language}, Evaluation)
                    scores[language].append(sum([evaluation.correctness, evaluation.completeness, evaluation.reasoning])/3
                        if evaluation.reliable and all(v is not None for v in
                            [evaluation.correctness, evaluation.completeness, evaluation.reasoning]) else None)
            report['scores_correct_paraphrase_partial_wrong'] = scores
            report['checks']['evaluation_order'] = all(all(v is not None for v in values)
                and abs(values[0]-values[1]) <= 1 and values[3] < values[0] and values[2] < values[0]
                for values in scores.values())
            insufficient = ai.structured(job_id, 'insufficient-evidence',
                'Use only provided evidence. If absent, reliable=false and ALL numeric scores=null.',
                {'question': 'What is the undocumented internal rule?', 'materials': [], 'rubric': [], 'answer': 'Unknown'}, Evaluation)
            report['checks']['insufficient_evidence'] = not insufficient.reliable and all(v is None for v in
                [insufficient.correctness, insufficient.completeness, insufficient.reasoning])
        source_facts = {'skills:0': 'Python и SQL',
                        'projects:0': 'В 2024 году сделал учебный трекер задач на Python и PostgreSQL.'}
        for language in ('ru', 'en'):
            draft = ai.structured(job_id, 'document-' + language,
                'Select relevant fact IDs and translate each selected source fact into requested language. '
                'Return a fragment for every selected ID; link each fragment to its source IDs. '
                'Preserve all numbers, employers, skills and qualifications, and add no claims.',
                {'facts': source_facts, 'vacancy': {'title': 'Junior Python developer',
                    'description': 'Python and SQL service development'}, 'language': language}, DocumentResult)
            valid_ids = {key for fragment in draft.fragments for key in fragment.fact_ids}
            review = ai.structured(job_id, 'document-review-' + language,
                'Audit each numbered proposal against its linked source. If claims are unsupported, '
                'mark supported=false with issues. Check requested language and facts.',
                {'language': language, 'fragments': [{'index': i,
                    'source': [source_facts[k] for k in fragment.fact_ids if k in source_facts],
                    'proposal': fragment.text} for i, fragment in enumerate(draft.fragments)]}, DocumentReview)
            report['checks']['document_' + language] = (
                bool(draft.fragments) and valid_ids == set(draft.selected_fact_ids)
                and valid_ids <= source_facts.keys() and len(review.fragments) == len(draft.fragments)
                and all(r.supported and not r.issues for r in review.fragments)
                and all(not fragment_issues(' '.join(source_facts[k] for k in f.fact_ids), f.text)
                    for f in draft.fragments))
        directory = settings.storage_path / 'live-fixtures'
        directory.mkdir(parents=True, exist_ok=True)
        english = args.audio_en or directory / 'synthetic-en.wav'
        if not args.audio_en and not english.exists():
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'flite=text=Python functions return values and context managers clean up resources:voice=slt',
                '-ar', '16000', str(english)], check=True)
        for language, path in ([('ru', args.audio_ru)] if args.documents_only else [('en', english), ('ru', args.audio_ru)]):
            if path is None:
                report['checks']['audio_' + language] = 'not_run_missing_synthetic_fixture'
                continue
            duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], text=True))
            transcription = ai.transcribe(job_id, 'speech-' + language, path, duration)
            report['checks']['audio_' + language] = speech_terms(transcription.get('text', ''), [t.strip() for t in getattr(args, 'expected_' + language).split(',') if t.strip()])
    except (ai.Paused, ai.Uncertain, ValueError) as exc:
        report['stopped'] = str(exc)
    with Session() as db:
        usage = db.scalars(select(Usage).where(Usage.key.like(job_id + ':%'))).all()
        report['calculated_usd'] = float(sum(u.actual or 0 for u in usage))
        report['open_reservations_usd'] = float(sum(u.reserved for u in usage if u.state in ('reserved', 'uncertain')))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_status(report)


if __name__ == '__main__':
    raise SystemExit(main())
