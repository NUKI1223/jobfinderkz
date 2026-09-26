"""Source-linked document drafting. Automated checks assist explicit user review."""
import re


def numeric_claims(value):
    return set(re.findall(r'\d+(?:[.,]\d+)?%?', value))


def fragment_issues(source, proposal):
    issues = []
    if numeric_claims(proposal) - numeric_claims(source):
        issues.append('Новые числа или даты: исправьте по исходному факту.')
    # Preserve named Latin technologies/employers; translated names need review.
    named = set(re.findall(r'\b(?:[A-Z][a-z]*[A-Z][A-Za-z0-9.+#-]*|[A-Z]{2,}[A-Za-z0-9.+#-]*)\b', proposal))
    if any(name.casefold() not in source.casefold() for name in named):
        issues.append('Новое название или технический термин: проверьте источник.')
    return issues


def render(introduction, fragments, closing):
    return '\n\n'.join([introduction] + [f['text'] for f in fragments] + ([closing] if closing else []))


def edited_blocks(data, text):
    """Conservative provenance: only an unchanged reviewed fragment keeps its origin.

    Editing is unrestricted. A human approval never upgrades automated validation.
    Older documents are read without mutation and their prior representation is kept.
    """
    known = {}
    for fragment in data.get('fragments', []):
        if fragment.get('issues'):
            continue
        original = fragment.get('proposed_text', fragment['text'])
        known[original] = {'origin': 'cv' if original == fragment.get('source_text') else 'model',
            'fact_ids': fragment.get('fact_ids', []), 'verified_by_cv': True}
    for block in data.get('blocks', []):
        known[block['text']] = {k: v for k, v in block.items() if k != 'text'}
    for field in ('introduction', 'closing'):
        if data.get(field):
            known[data[field]] = {'origin': 'template', 'fact_ids': [], 'verified_by_cv': False}
    return [{'text': paragraph, **known.get(paragraph,
        {'origin': 'user', 'fact_ids': [], 'verified_by_cv': False})} for paragraph in text.split('\n\n')]


def approve_edit(row, body):
    from fastapi import HTTPException
    from .db import now
    from .store import save_data
    blocks = edited_blocks(row.data, body.text)
    if row.data.get('requires_confirmation') and not body.confirmed:
        raise HTTPException(422, 'Подтвердите итоговый текст документа')
    if any(b['origin'] == 'user' for b in blocks) and not body.accept_user_claims:
        raise HTTPException(422, 'Подтвердите добавленные пользователем утверждения: они не проверены по CV')
    versions = row.data.get('versions', []) + [{k: row.data.get(k) for k in
        ('text', 'fragments', 'blocks', 'approved')} | {'saved_at': now().isoformat()}]
    save_data(row, text='\n\n'.join(b['text'] for b in blocks), blocks=blocks, approved=True,
              versions=versions, version=row.data.get('version', 1) + 1)
    row.status = 'saved'
