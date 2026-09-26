from ..ports import TextPort
from .. import ai
from ..db import Session
from ..schemas import DocumentResult, DocumentReview
from ..documents import fragment_issues, render
from ..large_inputs import byte_size, fact_parts, text_parts
from ..store import owned


from .output import result_record
from .resumes import fact_catalog

def document(job, *, sessions=Session, text: TextPort = ai):
    payload = ai.checkpoint(job.id, 'document-input')
    with sessions() as db:
        cv = owned(db, job.payload['cv_id'], job.owner_id, 'cv')
        vacancy = owned(db, job.payload['vacancy_id'], job.owner_id, 'vacancy')
        if cv.status != 'confirmed':
            raise ValueError('Подтвердите профиль CV')
        catalog = fact_catalog(cv.data['facts'])
        if payload is None:
            payload = {**job.payload, 'facts': catalog, 'vacancy': vacancy.data}
            ai.save_checkpoint(job.id, 'document-input', payload)
        catalog = payload['facts']
    instruction = ('Select and order existing fact IDs relevant to the vacancy. '
        'Translate and rephrase each selected fact into the requested language in fragments. '
        'Every fragment must reference its exact fact_ids. Cover all selected IDs and use no other IDs. '
        'Do not introduce any new skill, employer, achievement, duration or experience. '
        'Do not strengthen responsibility, proficiency or results. Preserve names, dates and numbers. '
        'Introduction and closing may express only interest in the role, no factual claims about candidate. '
        'Write in requested language. Explain structural changes.')
    inputs = [payload]
    if byte_size(payload) > 75000:
        inputs = [{**payload, 'facts': facts, 'vacancy': {**payload['vacancy'], 'description': description}}
            for facts in fact_parts(catalog) for description in text_parts(payload['vacancy']['description'])]
    drafts = [text.structured(job.id, 'document' if len(inputs)==1 else f'document-part-{i}',
        instruction, part, DocumentResult) for i, part in enumerate(inputs)]
    if len(drafts)==1:
        result = drafts[0]
    else:
        # Preserve source identity across selections; never invent a merged assertion.
        selected = list(dict.fromkeys(k for draft in drafts for k in draft.selected_fact_ids))
        distinct = {}
        for draft in drafts:
            for fragment in draft.fragments:
                distinct.setdefault(tuple(fragment.fact_ids), fragment)
        result = DocumentResult(title=drafts[0].title, introduction='', closing='', selected_fact_ids=selected,
            changes=list(dict.fromkeys(x for draft in drafts for x in draft.changes)) + ['Большой вход обработан частями; проверьте порядок фрагментов.'],
            fragments=list(distinct.values()))
    if any(key not in catalog for key in result.selected_fact_ids):
        raise ValueError('Модель предложила неподтверждённый факт')
    fragments = []
    if result.fragments:
        referenced = {key for fragment in result.fragments for key in fragment.fact_ids}
        if referenced != set(result.selected_fact_ids) or any(key not in catalog for key in referenced):
            raise ValueError('Фрагменты документа ссылаются на неподтверждённые факты')
        review_instruction = ('Audit each numbered proposed fragment against ONLY its linked source facts. '
            'Allow faithful translation/paraphrase. Reject invented employers, skills, dates, numbers, '
            'achievements, proficiency or stronger responsibility. Require the requested language. '
            'Uncertainty means supported=false; explain issues in Russian. Return each index exactly once.')
        review_items = [{'index': i, 'source': [catalog[k] for k in f.fact_ids], 'proposal': f.text}
            for i, f in enumerate(result.fragments)]
        batches, current = [], []
        for item in review_items:
            if current and byte_size(current + [item]) > 60000:
                batches.append(current)
                current = []
            current.append(item)
        if current:
            batches.append(current)
        reviews_by_part = [text.structured(job.id, 'document-review' if len(batches)==1 else f'document-review-{i}',
            review_instruction, {'language': job.payload['language'], 'fragments': batch}, DocumentReview)
            for i, batch in enumerate(batches)]
        review = DocumentReview(fragments=[r for part in reviews_by_part for r in part.fragments])
        if len(review.fragments) != len(result.fragments) or {r.index for r in review.fragments} != set(range(len(result.fragments))):
            raise ValueError('Неполная проверка фактов документа')
        reviews = {r.index: r for r in review.fragments}
        for i, fragment in enumerate(result.fragments):
            source = '\n'.join(catalog[k] for k in fragment.fact_ids)
            issues = fragment_issues(source, fragment.text)
            if not reviews[i].supported or reviews[i].issues:
                issues += reviews[i].issues or ['Смысл не подтверждён исходными фактами.']
            fragments.append({'fact_ids': fragment.fact_ids, 'source_text': source,
                'text': fragment.text, 'proposed_text': fragment.text, 'issues': issues})
    else:
        # Backward compatibility with paid checkpoints created before translation.
        fragments = [{'fact_ids': [key], 'source_text': catalog[key], 'text': catalog[key],
            'proposed_text': catalog[key], 'issues': []} for key in dict.fromkeys(result.selected_fact_ids)]
    en = job.payload['language'] == 'en'
    if job.payload['kind'] == 'cover_letter':
        intro = 'I would like to apply for this position.' if en else 'Хочу откликнуться на эту вакансию.'
        closing = 'I would welcome the opportunity to discuss the role.' if en else 'Буду рад обсудить задачи и ожидания на интервью.'
    else:
        intro, closing = ('Relevant experience' if en else 'Релевантный опыт'), ''
    rendered = render(intro, fragments, closing)
    return result_record(job, 'document', {**job.payload, 'title': result.title, 'text': rendered,
        'original_facts': catalog, 'selected_fact_ids': result.selected_fact_ids, 'changes': result.changes,
        'fragments': fragments, 'introduction': intro, 'closing': closing,
        'requires_confirmation': bool(result.fragments), 'approved': False,
        'versions': [], 'language_note': 'Сверьте каждый перевод с источником; автоматическая проверка может ошибаться.'
            if result.fragments else 'Старый результат: факты сохранены на исходном языке.'},
        'review' if result.fragments else 'draft')
