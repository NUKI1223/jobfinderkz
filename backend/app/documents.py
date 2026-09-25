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
