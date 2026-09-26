import httpx
from sqlalchemy import select
from .. import ai, ingest
from ..config import settings
from ..db import Session, Record, now
from ..hh import FORMAT_IDS, region_index, resolve_regions, work_formats



def hh_sync(job, *, sessions=Session):
    if not settings.hh_access_token:
        raise ai.Paused('HeadHunter не подключён: добавьте HH_ACCESS_TOKEN и HH_USER_AGENT в .env')
    max_results = job.payload.get('max_results', 20)  # Older queued jobs keep their original scope.
    experience = ['noExperience'] if job.payload['level'] == 'junior' else ['between1And3']
    if job.payload.get('experience_scope') == 'broader':
        experience.append('between1And3' if job.payload['level'] == 'junior' else 'between3And6')
    params = {'text': job.payload['text'], 'per_page': min(50, max_results), 'experience': experience}
    if job.payload['work_format'] in FORMAT_IDS:
        params['work_format'] = FORMAT_IDS[job.payload['work_format']]
    saved = ai.checkpoint(job.id, 'hh')
    area_snapshot = ai.checkpoint(job.id, 'hh-areas')
    if saved is None:
        with httpx.Client(timeout=30, headers={'Authorization': f'Bearer {settings.hh_access_token}', 'HH-User-Agent': settings.hh_user_agent}) as client:
            if area_snapshot is None:
                response = client.get('https://api.hh.ru/areas')
                if response.status_code != 200:
                    raise ValueError(f'Справочник HeadHunter недоступен (HTTP {response.status_code})')
                by_name, by_id = region_index(response.json())
                areas = [job.payload['area']] if job.payload.get('area') else resolve_regions(job.payload.get('regions') or [], by_name)
                area_snapshot = {'ids': areas, 'regions': by_id}
                ai.save_checkpoint(job.id, 'hh-areas', area_snapshot)
            if area_snapshot['ids']:
                params['area'] = area_snapshot['ids']
            listings = ai.checkpoint(job.id, 'hh-list')
            if listings is None:
                listings = []
                for page in range((max_results + params['per_page'] - 1) // params['per_page']):
                    page_items = ai.checkpoint(job.id, f'hh-list:{page}')
                    if page_items is None:
                        response = client.get('https://api.hh.ru/vacancies', params={**params, 'page': page})
                        if response.status_code != 200:
                            raise ValueError(f'HeadHunter недоступен (HTTP {response.status_code}); полученные страницы сохранены')
                        result = response.json()
                        page_items = result.get('items', [])[:max_results - len(listings)]
                        ai.save_checkpoint(job.id, f'hh-list:{page}', page_items)
                        pages = result.get('pages')
                    else:
                        pages = None
                    listings.extend(page_items)
                    if not page_items or (pages is not None and page + 1 >= pages):
                        break
                listings = list({str(item['id']): item for item in listings}.values())[:max_results]
                ai.save_checkpoint(job.id, 'hh-list', listings)
            saved = []
            for item in listings:
                rid = str(item['id'])
                if not rid.isdigit():
                    continue
                detail = ai.checkpoint(job.id, 'hh-detail:' + rid)
                if detail is None:
                    response = client.get(f'https://api.hh.ru/vacancies/{rid}')
                    if response.status_code in (404, 410):
                        detail = {'unavailable': True}
                    elif response.status_code == 200:
                        detail = response.json()
                    else:
                        raise ValueError(f'Не удалось получить вакансию HeadHunter (HTTP {response.status_code}); полученные этапы сохранены')
                    ai.save_checkpoint(job.id, 'hh-detail:' + rid, detail)
                if not detail.get('unavailable') and not detail.get('archived'):
                    saved.append(detail)
        ai.save_checkpoint(job.id, 'hh', saved)
    count = 0
    with sessions.begin() as db:
        for item in saved:
            key = 'hh:' + str(item['id'])
            row = db.scalar(select(Record).where(Record.owner_id == job.owner_id, Record.kind == 'vacancy', Record.dedup_key == key).with_for_update())
            formats = work_formats(item)
            data = {
                'title': item['name'], 'company': (item.get('employer') or {}).get('name', ''),
                'description': ingest.BeautifulSoup(item['description'], 'html.parser').get_text(' ', strip=True),
                'url': item['alternate_url'], 'region': item['area']['name'], 'direction': job.payload['direction'],
                'region_parents': ((area_snapshot or {}).get('regions', {}).get(str(item['area']['id']), {})).get('parents', []),
                'level': job.payload['level'], 'work_format': formats[0] if formats else 'any', 'work_formats': formats,
                'hh_experience': (item.get('experience') or {}).get('name', ''),
                'source': 'hh', 'fetched_at': now().isoformat(), 'favorite': row.data.get('favorite', False) if row else False}
            if row:
                old = row.data
                if all(old.get(k) == data.get(k) for k in ('title', 'description', 'direction', 'level')):
                    for field in ('match', 'ranked_at'):
                        if field in old:
                            data[field] = old[field]
                row.data = data
            else:
                db.add(Record(kind='vacancy', owner_id=job.owner_id, dedup_key=key, status='saved', data=data))
            count += 1
    return {'count': count, 'synced_at': now().isoformat()}
