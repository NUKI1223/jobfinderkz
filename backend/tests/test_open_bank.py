"""Reviewed local content only: no downloads, provider calls or live Selenium claims."""
import hashlib
import itertools
import json
import math
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.db import Job, Record, Session, Usage
from app.import_reviewed_bank import import_batch
from app.retrieval import evidence, retrieve

ROOT = Path('/reviewed/open_20260926')


def packages(direction='*'):
    directions = ['frontend', 'python', 'qa'] if direction == '*' else [direction]
    return [json.loads((ROOT / f'{name}_{level}.json').read_text())
            for name in directions for level in ['junior', 'middle']]


def test_open_packages_preserve_license_and_publish_only_reviewed_content(client, user):
    sources = {s['repository']: s for s in json.loads((ROOT / 'source_manifest.json').read_text())}
    batches = packages()
    assert len(batches) == 6
    for batch in batches:
        assert len(batch['questions']) == 4
        for q in batch['questions']:
            source = sources[q['upstream']['repository']]
            assert q['upstream']['commit'] == source['commit']
            license_text = (ROOT / source['license_file']).read_text()
            assert hashlib.sha256(license_text.encode()).hexdigest() == source['license_sha256']
            material = next(m for m in batch['materials'] if m['key'] in q['material_keys'])
            assert license_text in material['text']
            assert source['commit'] in material['text'] and q['upstream']['item'] in material['text']
        assert import_batch(batch)['new_questions'] == 4
        assert import_batch(batch, apply=True)['new_questions'] == 4
        assert import_batch(batch, apply=True)['new_questions'] == 0
    with Session() as db:
        rows = db.scalars(select(Record).where(Record.kind == 'question')).all()
        assert len(rows) == 24 and all(evidence(db, q.data) for q in rows)
        for batch in batches:
            direction, level = batch['direction'], batch['level']
            assert retrieve(db, 'test', direction, level, 'ru', kind='question')
            for mode in ['question', 'task']:
                response = client.get('/api/v1/study/items', params={
                    'direction': direction, 'level': level, 'language': 'ru', 'mode': mode})
                assert response.status_code == 200
                assert response.json()['total'] == 4
        for row in rows:
            assert row.status == 'published' and row.data['task_solution']
            assert row.data['candidate_answer'] == '' and row.data['sources'] == []
            for mode in ['question', 'task']:
                response = client.get(f'/api/v1/study/items/{row.id}?mode={mode}')
                assert response.status_code == 200
                detail = response.json()
                assert detail['reference_answer'] == row.data['reference_answer']
                assert 'review_note' not in detail and 'candidate_answer' not in detail
                assert any('MIT License' in m['text'] and 'Copyright (c)' in m['text']
                           for m in detail['materials'])
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Usage)) == 0


def test_reviewed_python_solutions_match_brute_force_and_edge_contracts():
    functions = {}
    for batch in packages('python'):
        for q in batch['questions']:
            namespace = {}
            # Execute only the committed, reviewed educational solutions, never remote input.
            exec(compile(q['task_solution'], q['key'], 'exec'), namespace)
            name = 'is_anagram' if q['key'] == 'anagram' else q['key'].replace('-', '_')
            functions[q['key']] = namespace[name]
    assert len(functions) == 8
    adjacent, kadane = functions['adjacent-product'], functions['max-subarray']
    for values in [[], [7]]:
        with pytest.raises(ValueError):
            adjacent(values)
    with pytest.raises(ValueError):
        kadane([])
    for length in range(6):
        for values_tuple in itertools.product([-2, 0, 3], repeat=length):
            values = list(values_tuple)
            original = values.copy()
            if length >= 2:
                assert adjacent(values) == max(values[i] * values[i + 1] for i in range(length - 1))
            if length:
                expected = max(sum(values[i:j]) for i in range(length) for j in range(i + 1, length + 1))
                assert kadane(values) == expected
            assert functions['product-except-self'](values) == [
                math.prod(values[:i] + values[i + 1:]) for i in range(length)]
            for target in range(-4, 7):
                expected_pairs = sorted({tuple(sorted((values[i], values[j])))
                                         for i in range(length) for j in range(i + 1, length)
                                         if values[i] + values[j] == target})
                assert functions['pairs-sum'](values, target) == expected_pairs
                sorted_values = sorted(values)
                index = functions['binary-search'](sorted_values, target)
                assert (index == -1 and target not in sorted_values) or (
                    0 <= index < length and sorted_values[index] == target)
            assert values == original
            expected_zeros = [v for v in values if v != 0] + [0] * values.count(0)
            assert functions['move-zeros'](values) is values
            assert values == expected_zeros
    assert adjacent([9, 1, 8]) == 9
    assert adjacent([-2, 3, -4]) == -6
    assert kadane([4, -1, 2, -7, 3]) == 5
    assert functions['pairs-sum']([3], 6) == []
    assert functions['pairs-sum']([3, 3, 1, 5, 5], 6) == [(1, 5), (3, 3)]
    texts = ['', 'топот', 'топотя', 'AaA', 'é', 'e\u0301', '🙂🙂я']
    texts += [''.join(chars) for length in range(4) for chars in itertools.product('abя', repeat=length)]
    for value in texts:
        expected = next((char for char in value if value.count(char) == 1), None)
        assert functions['first-unique'](value) == expected
        assert functions['first-unique'](value) == expected  # no retained global state
        for other in texts:
            assert functions['anagram'](value, other) == (sorted(value) == sorted(other))


def test_reviewed_sql_solutions_handle_null_duplicates_and_empty_tables():
    solutions = {q['key']: q['task_solution'] for batch in packages('qa') for q in batch['questions']}
    with Session.begin() as db:
        assert db.scalar(text('SELECT current_database()')) == 'jobfinder_test'
        db.execute(text('CREATE TEMP TABLE a(id integer PRIMARY KEY) ON COMMIT DROP'))
        db.execute(text('CREATE TEMP TABLE b(a_id integer) ON COMMIT DROP'))
        db.execute(text('INSERT INTO a VALUES (1), (2), (3)'))
        assert db.scalars(text(solutions['sql-antijoin'])).all() == [1, 2, 3]
        db.execute(text('INSERT INTO b VALUES (2), (2), (NULL)'))
        assert db.scalars(text(solutions['sql-antijoin'])).all() == [1, 3]
        db.execute(text('INSERT INTO b VALUES (1), (3)'))
        assert db.scalars(text(solutions['sql-antijoin'])).all() == []
        db.execute(text('CREATE TEMP TABLE users(team text, active boolean, email text) ON COMMIT DROP'))
        assert db.execute(text(solutions['sql-group-filter'])).all() == []
        db.execute(text("""INSERT INTO users VALUES
            ('a', TRUE, 'one@example.com'), ('a', TRUE, NULL), ('a', FALSE, 'two@example.com'),
            ('b', TRUE, NULL), ('b', FALSE, 'three@example.com'),
            ('c', TRUE, NULL), ('c', TRUE, NULL)"""))
        assert db.execute(text(solutions['sql-group-filter'])).all() == [('a', 2, 1), ('c', 2, 0)]
