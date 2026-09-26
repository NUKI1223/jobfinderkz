from ..ports import TextPort
import json
from .. import ai
from ..db import Session, now
from ..schemas import CVFacts, Ranking
from ..revisions import fingerprint, cv_revision, vacancy_input
from ..large_inputs import byte_size, fact_parts, text_parts
from ..store import owned, save_data



def parse_cv(job, *, sessions=Session, text: TextPort = ai):
    snapshot = ai.checkpoint(job.id, 'parse-input')
    if snapshot is None:
        with sessions() as db:
            cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
            snapshot = {'text': cv.data['text'], **cv_revision(cv)}
        ai.save_checkpoint(job.id, 'parse-input', snapshot)
    source_text = snapshot['text']
    parts = []
    for offset in range(0, len(source_text), 12000):
        step = 'parse' if len(source_text) <= 12000 else f'parse-{offset // 12000}'
        facts = text.structured(job.id, step, 'Extract only explicitly stated resume facts. Preserve exact factual wording. '
            'Return empty lists for missing sections. Remove contact details and personal identifiers.',
            {'cv': source_text[offset:offset + 12000]}, CVFacts)
        parts.append(facts.model_dump())
        ai.save_checkpoint(job.id, 'parse-parts', parts)
    merged = {k: ('\n'.join(p[k] for p in parts if p[k]) if k == 'summary'
                 else list(dict.fromkeys(x for p in parts for x in p[k]))) for k in CVFacts.model_fields}
    # Preserve every part even if the extracted result needs manual size reduction.
    try:
        CVFacts.model_validate(merged)
        warning = ''
    except ValueError:
        warning = 'Объединённый результат превышает ограничения полей. Сократите его перед подтверждением; все части сохранены.'
    with sessions.begin() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv', lock=True)
        drafts = cv.data.get('parse_drafts', [])
        if not any(d['job_id'] == job.id for d in drafts):
            save_data(cv, parse_drafts=drafts + [{'job_id': job.id, 'facts': merged, 'parts': parts,
                'base_version': snapshot['cv_version'], 'warning': warning, 'created_at': now().isoformat()}])
    return {'record_id': cv.id, 'draft_job_id': job.id}


def rank(job, *, sessions=Session, text: TextPort = ai):
    content = ai.checkpoint(job.id, 'rank-input')
    with sessions() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        if cv.status != 'confirmed':
            raise ValueError('Сначала подтвердите профиль резюме')
        vacancies = [owned(db, rid, job.owner_id, 'vacancy') for rid in job.payload['vacancy_ids'][:20]]
        if content is None:
            content = {**cv_revision(cv), 'facts': cv.data['facts'], 'vacancies': [{'id': v.id, **{k: v.data.get(k, '')
                for k in ('title', 'description', 'company', 'level', 'direction')}} for v in vacancies]}
            ai.save_checkpoint(job.id, 'rank-input', content)
    instruction = ('Rank vacancies by confirmed facts only. Give reasons, matching skills and gaps in Russian. '
        'Include each supplied vacancy ID exactly once. Score each independently on an absolute 0-100 scale.')
    # Deterministic batches use the frozen input so retries keep paid steps stable.
    batches, current = [], []
    for vacancy in content['vacancies']:
        candidate = {**content, 'vacancies': current + [vacancy]}
        if current and len(json.dumps(candidate, ensure_ascii=False).encode()) > 75000:
            batches.append(current)
            current = []
        current.append(vacancy)
    if current:
        batches.append(current)
    matches = []
    for index, batch in enumerate(batches):
        step = 'rank' if len(batches) == 1 else f'rank-batch-{index}'
        batch_input = {**content, 'vacancies': batch}
        if byte_size(batch_input) <= 80000:
            result = text.structured(job.id, step, instruction, batch_input, Ranking)
        else:
            # A single large vacancy/CV pair also needs bounded requests.
            partial_matches = []
            for v_index, vacancy in enumerate(batch):
                by_description = []
                for d_index, description in enumerate(text_parts(vacancy['description'])):
                    by_facts = []
                    for f_index, facts in enumerate(fact_parts(content['facts'])):
                        part = {**content, 'facts': facts, 'vacancies': [{**vacancy, 'description': description}]}
                        response = text.structured(job.id, f'{step}-v{v_index}-d{d_index}-f{f_index}',
                            instruction + ' This is a partial input; assess only the supplied requirements and facts.', part, Ranking)
                        if len(response.matches) != 1 or response.matches[0].vacancy_id != vacancy['id']:
                            raise ValueError('Неверный идентификатор частичной оценки')
                        by_facts.append(response.matches[0])
                    by_description.append(max(by_facts, key=lambda m: m.score))
                merged = by_description[0].model_copy(deep=True)
                merged.score = round(sum(m.score for m in by_description) / len(by_description))
                for field in ('reasons', 'matching_skills', 'missing_skills'):
                    setattr(merged, field, list(dict.fromkeys(x for m in by_description for x in getattr(m, field))))
                merged.reasons.insert(0, 'Большой вход оценён по частям; итог — среднее по требованиям, с лучшим совпадением разделов CV.')
                partial_matches.append(merged)
            result = Ranking(matches=partial_matches)
        if len(result.matches) != len(batch) or {m.vacancy_id for m in result.matches} != {v['id'] for v in batch}:
            raise ValueError('Ранжирование содержит неверные идентификаторы')
        matches.extend(result.matches)
    result = Ranking(matches=matches)
    if {m.vacancy_id for m in result.matches} != {v.id for v in vacancies} or len(result.matches) != len(vacancies):
        raise ValueError('Ранжирование содержит неверные идентификаторы')
    applied = 0
    with sessions.begin() as db:
        for match in result.matches:
            row = owned(db, match.vacancy_id, job.owner_id, 'vacancy', lock=True)
            current_cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv', lock=True)
            original = next(v for v in content['vacancies'] if v['id'] == row.id)
            if (content.get('facts_hash') != cv_revision(current_cv)['facts_hash']
                    or content.get('cv_version') != cv_revision(current_cv)['cv_version']
                    or fingerprint(vacancy_input(original)) != fingerprint(vacancy_input(row.data))):
                continue
            save_data(row, match={**match.model_dump(), **cv_revision(current_cv),
                'vacancy_hash': fingerprint(vacancy_input(row.data))}, ranked_at=now().isoformat())
            applied += 1
    return {'count': applied, 'stale': len(result.matches) - applied}


def fact_catalog(facts):
    catalog = {}
    for field, values in facts.items():
        for index, value in enumerate(values if isinstance(values, list) else [values]):
            if value:
                catalog[f'{field}:{index}'] = value
    return catalog
