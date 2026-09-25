"""HeadHunter adapter helpers. Region IDs are resolved from the provider tree."""
FORMAT_IDS = {'remote': 'REMOTE', 'office': 'ON_SITE', 'hybrid': 'HYBRID'}
FORMATS = {value: key for key, value in FORMAT_IDS.items()}


def region_index(tree):
    by_name, by_id = {}, {}
    def visit(nodes, parents):
        for node in nodes:
            item = {'id': str(node['id']), 'name': node['name'], 'parents': parents}
            by_name.setdefault(node['name'].strip().casefold(), []).append(item)
            by_id[item['id']] = item
            visit(node.get('areas', []), parents + [node['name']])
    visit(tree, [])
    return by_name, by_id


def resolve_regions(regions, by_name):
    result = []
    for name in regions:
        name = name.strip()
        if not name:
            continue
        matches = by_name.get(name.casefold(), [])
        if not matches:
            raise ValueError('Регион не найден в HeadHunter. Укажите полное название страны или города в профиле.')
        if len(matches) > 1:
            raise ValueError('Название региона неоднозначно в HeadHunter. Выберите другой регион или используйте его точный ID.')
        if matches[0]['id'] not in result:
            result.append(matches[0]['id'])
    return result


def work_formats(item):
    formats = [FORMATS[f['id']] for f in item.get('work_format', []) if f.get('id') in FORMATS]
    # Only remote can safely be inferred from the legacy schedule field.
    if not formats and (item.get('schedule') or {}).get('id') == 'remote':
        formats = ['remote']
    return list(dict.fromkeys(formats))
