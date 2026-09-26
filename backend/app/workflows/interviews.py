from ..revisions import match_current
from ..ports import TextPort
import shutil
from pathlib import Path
from .. import ai, ingest
from ..db import Session, now
from ..schemas import Evaluation
from ..store import owned, save_data
from ..retrieval import retrieve, evidence, practiced_questions, prioritize_questions, canonical, lexical_relevant


from .output import result_record

def plan(job, *, sessions=Session):
    with sessions() as db:
        vacancy = owned(db, job.payload['vacancy_id'], job.owner_id, 'vacancy')
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        if cv.status != 'confirmed':
            raise ValueError('Подтвердите профиль CV')
        profile = job.payload['profile']
        match = vacancy.data.get('match', {})
        if not match_current(match, cv, vacancy):
            match = {}
        query = vacancy.data.get('title', '') + ' ' + ' '.join(match.get('missing_skills', [])) + ' ' + vacancy.data['description']
        # Availability is free and uses the same policy as interview creation.
        if not retrieve(db, query, profile['direction'], profile['level'], profile['language'], 1, kind='question'):
            raise ValueError('Нет опубликованных вопросов с актуальными основаниями')
        vector = None
        rows = retrieve(db, query, profile['direction'], profile['level'], profile['language'], 100, vector, kind='question')
        history = practiced_questions(db, job.owner_id)
        questions = prioritize_questions(rows, history)
        if not questions:
            raise ValueError('Нет опубликованных вопросов для выбранных направления, уровня и языка. Администратор должен проверить и опубликовать базу.')
        days = []
        for day in range(7):
            question = questions[day % len(questions)]
            q = question.data
            days.append({'day': day + 1, 'title': q['topic'], 'question_id': question.id, 'question': q['question'],
                'fallback': not lexical_relevant(db, question, query),
                'repeat': day >= len(questions) or canonical(question) in history,
                'repeat_reason': 'Повторение в этом плане' if day >= len(questions) else 'Уже встречался в интервью' if canonical(question) in history else '',
                'example': q['reference_answer'], 'task': q.get('task') or ('Объясните решение на собственном примере.' if profile['language'] == 'ru' else 'Explain using your own example.'),
                'materials': [{'id': m['id'], 'url': m['url']} for m in evidence(db, q)], 'done': False})
    return result_record(job, 'plan', {'vacancy_id': vacancy.id, 'days': days, 'profile': profile,
        'available_questions': len(questions), 'shortage': max(0, 7 - len(questions)),
        'gaps': match.get('missing_skills', []),
        'review': f'Подходящих вопросов: {len(questions)}. Повторения отмечены отдельно.'}, 'ready')


def evaluate(job, *, sessions=Session, text: TextPort = ai):
    with sessions() as db:
        session = owned(db, job.payload['interview_id'], job.owner_id, 'interview')
        index = job.payload['index']
        turn = session.data['turns'][index]
        if turn.get('evaluation'):
            return {'record_id': session.id}
        q = turn['question']
        materials = turn['materials']
    if not materials or not q.get('rubric'):
        evaluation = Evaluation(reliable=False, correctness=None, completeness=None, reasoning=None,
            feedback='Недостаточно проверенных оснований для надёжной оценки.', errors=[], missing_points=[], improved_answer='')
    else:
        evaluation = text.structured(job.id, 'evaluate', 'Evaluate technical correctness, completeness and reasoning from 0 to 4. '
            'Accept correct paraphrases and alternative solutions. Ignore accent, pronunciation and style. '
            'Use only provided reviewed reference, rubric and materials. If evidence conflicts or is insufficient, '
            'set reliable=false and all scores=null. Explain errors, gaps, and a better example in interview language.',
            {'question': q, 'materials': materials, 'answer': job.payload['text'], 'language': session.data['language']}, Evaluation)
        if not evaluation.reliable:
            evaluation.correctness = evaluation.completeness = evaluation.reasoning = None
        elif any(x is None for x in [evaluation.correctness, evaluation.completeness, evaluation.reasoning]):
            raise ValueError('Неполная оценка модели')
    with sessions.begin() as db:
        session = owned(db, session.id, job.owner_id, 'interview', lock=True)
        turns = list(session.data['turns'])
        turns[index] = {**turns[index], 'answer': job.payload['text'], 'evaluation': evaluation.model_dump(), 'evaluated_at': now().isoformat()}
        save_data(session, turns=turns)
        if all(t.get('evaluation') for t in turns):
            session.status = 'completed'
    return {'record_id': session.id}


def audio_answer(job, *, sessions=Session):
    path = Path(job.payload['path'])
    directory = path.parent / job.id
    directory.mkdir(exist_ok=True)
    transcript = ai.checkpoint(job.id, 'transcript')
    if transcript is None:
        transcript = ingest.audio_transcript(job.id, path, directory, diarize=False)
        ai.save_checkpoint(job.id, 'transcript', transcript)
    path.unlink(missing_ok=True)
    shutil.rmtree(directory, ignore_errors=True)
    result = {'text': ' '.join(p['text'] for p in transcript['segments']), 'requires_confirmation': True,
        'interview_id': job.payload['interview_id'], 'index': job.payload.get('index', 0)}
    with sessions.begin() as db:
        row = owned(db, result['interview_id'], job.owner_id, 'interview', lock=True)
        turns = list(row.data['turns'])
        index = result['index']
        if turns[index].get('audio_job_id') == job.id and not turns[index].get('submitted'):
            turns[index] = {**turns[index], 'transcript': result['text']}
            save_data(row, turns=turns)
    return result
