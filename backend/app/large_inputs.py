"""Deterministic, lossless input partitions; callers persist provider checkpoints."""
import json


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def fact_parts(facts, limit=20000):
    parts, current = [], {}
    for key, value in facts.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            # Validated individual items fit; preserve even empty sections.
            candidate = {**current, key: (current.get(key, []) + [item] if isinstance(value, list) else item)}
            if current and byte_size(candidate) > limit:
                parts.append(current)
                current = {}
                candidate = {key: [item] if isinstance(value, list) else item}
            current = candidate
    if current:
        parts.append(current)
    return parts or [{}]


def text_parts(value, length=12000):
    return [value[offset:offset+length] for offset in range(0,len(value),length)] or ['']
