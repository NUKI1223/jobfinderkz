"""Unpaid integration smoke test for the owner's three supplied videos."""
import json
from pathlib import Path
from .ingest import fetch_youtube
from .config import settings

VIDEOS = ['zibAC8HkGFk', 'UYmA6p7UwOo', 'GlK6nGzAK8E']

if __name__ == '__main__':
    for video in VIDEOS:
        directory = settings.storage_path / 'probes' / video
        directory.mkdir(parents=True, exist_ok=True)
        try:
            # Never spend money in this smoke test, even when a key is configured.
            settings.openai_api_key = ''
            result = fetch_youtube(video, 'ru', directory)
            (directory / 'transcript.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            print(json.dumps({'video': video, 'method': result['method'], 'segments': len(result['segments']),
                  'seconds': result['segments'][-1]['end'] if result['segments'] else 0}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({'video': video, 'error': str(exc)}, ensure_ascii=False), flush=True)
