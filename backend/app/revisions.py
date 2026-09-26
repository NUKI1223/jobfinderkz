"""Stable identities for domain inputs; excludes presentation and user metadata."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def vacancy_input(data):
    return {k: data.get(k, '') for k in ('title', 'description', 'company', 'level', 'direction')}


def cv_revision(row):
    return {'cv_id': row.id, 'cv_version': row.data.get('version', 1),
            'facts_hash': fingerprint(row.data.get('facts', {}))}


def match_current(match, cv, vacancy):
    return all(match.get(k) == v for k, v in cv_revision(cv).items()) and match.get('vacancy_hash') == fingerprint(vacancy_input(vacancy.data))
