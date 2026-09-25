"""Conservative, offline CV section extraction. Unclassified text stays separate."""
import re

ALIASES = {
    'summary': ('о себе', 'обо мне', 'кратко о себе', 'профиль', 'summary', 'professional summary', 'about me', 'profile'),
    'skills': ('навыки', 'ключевые навыки', 'технические навыки', 'skills', 'technical skills', 'technologies', 'стек технологий'),
    'experience': ('опыт', 'опыт работы', 'профессиональный опыт', 'experience', 'work experience', 'employment history'),
    'education': ('образование', 'образование и курсы', 'education', 'курсы', 'courses', 'certifications'),
    'projects': ('проекты', 'учебные проекты', 'projects', 'personal projects'),
    'languages': ('языки', 'знание языков', 'иностранные языки', 'languages'),
}
HEADINGS = {alias: field for field, aliases in ALIASES.items() for alias in aliases}
LIMITS = {'skills': 100, 'experience': 50, 'education': 30, 'projects': 50, 'languages': 20}


def section_draft(text):
    sections = {field: [] for field in ALIASES}
    unassigned, active = [], None
    for raw in text.splitlines():
        line = raw.strip().strip('•●▪').strip()
        if not line:
            continue
        heading, separator, remainder = line.partition(':')
        field = HEADINGS.get(heading.strip().lower())
        if field:
            active = field
            line = remainder.strip() if separator else ''
        elif line.endswith(':'):
            # Unknown headings must not contaminate the preceding section.
            active = None
        if not line:
            continue
        if active is None:
            unassigned.append(line)
        elif active in ('skills', 'languages'):
            sections[active].extend(part.strip() for part in re.split(r'[,;•]', line) if part.strip())
        else:
            sections[active].append(line)
    facts = {'summary': '\n'.join(sections.pop('summary'))}
    # Do not lose long/oddly formatted source text or put it all into summary.
    if len(facts['summary']) > 6000:
        unassigned.append(facts['summary'])
        facts['summary'] = ''
    for field, values in sections.items():
        limit = LIMITS[field]
        facts[field] = values if len(values) <= limit else values[:limit - 1] + ['\n'.join(values[limit - 1:])]
    return {'facts': facts, 'unassigned_text': '\n'.join(unassigned), 'parse_method': 'sections'}
