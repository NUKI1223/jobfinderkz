"""Import only the three user-approved videos and their already fetched transcripts.

No accounts, fake questions or paid tasks are created. Safe to run repeatedly.
"""
import json
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from .db import Session, Record, Budget, now
from .config import settings

SOURCES = [
    ('zibAC8HkGFk', 'Собеседование Python Junior разработчик [2026]', 'junior'),
    ('UYmA6p7UwOo', 'Джун без коммерческого опыта | Собеседование Python Junior разработчик', 'junior'),
    ('GlK6nGzAK8E', 'Python-cобес. Senior из МТС сказал, что кандидат отлично справился! А ты бы смог ответить?', 'middle'),
]


def main():
    month = now().strftime('%Y-%m')
    for video, title, level in SOURCES:
        path = settings.storage_path / 'probes' / video / 'transcript.json'
        transcript = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        with Session.begin() as db:
            row = db.scalar(select(Record).where(Record.owner_id.is_(None), Record.kind == 'source', Record.dedup_key == video))
            if row:
                print(video, 'already imported')
                continue
            seconds = int(max((s['end'] for s in transcript['segments']), default=0)) + 1 if transcript else 0
            db.execute(insert(Budget).values(month=month, charged=0, video_seconds=0).on_conflict_do_nothing())
            budget = db.scalar(select(Budget).where(Budget.month == month).with_for_update())
            if budget.video_seconds + seconds > settings.monthly_video_hours * 3600:
                raise ValueError('Monthly video quota exceeded')
            budget.video_seconds += seconds
            db.add(Record(kind='source', dedup_key=video, status='review' if transcript else 'draft', data={
                'video_id': video, 'url': f'https://www.youtube.com/watch?v={video}', 'title': title,
                'direction': 'python', 'level': level, 'language': 'ru', 'duration_seconds': seconds,
                'classification_note': 'Предварительная классификация; проверьте уровень каждого вопроса.',
                **({'transcript': transcript, 'probe_imported_at': now().isoformat()} if transcript else {})}))
        print(video, 'review' if transcript else 'needs audio or manual transcript')


if __name__ == '__main__':
    main()
