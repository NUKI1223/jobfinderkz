import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Bookmark, BriefcaseBusiness, ChevronDown, ChevronUp, ExternalLink, Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { api, directionName, statusName, type Entry } from './api'
import type { Connections, ProfileData } from './models'
import type { Action } from './shared'
import { Empty, Field } from './ui'

const PAGE_SIZE = 12
const workFormatName: Record<string, string> = { remote: 'Удалённо', office: 'Офис', hybrid: 'Гибрид', any: 'Любой формат' }

export function Vacancies({ rows, cv, profile, connections, act, select }: {
  rows: Entry<'vacancy'>[]
  cv?: Entry<'cv'>
  profile: ProfileData
  connections: Connections
  act: Action
  select: (id: string) => void
}) {
  const [search, setSearch] = useState('')
  const [hhText, setHhText] = useState('')
  const [onlyFavorites, setOnlyFavorites] = useState(false)
  const [region, setRegion] = useState('')
  const [format, setFormat] = useState('')
  const [direction, setDirection] = useState('')
  const [level, setLevel] = useState('')
  const [maxResults, setMaxResults] = useState(50)
  const [experienceScope, setExperienceScope] = useState<'strict' | 'broader'>('broader')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [searchExpanded, setSearchExpanded] = useState(rows.length === 0)
  const [sort, setSort] = useState<'match' | 'newest' | 'company'>('match')
  const autoCollapsed = useRef(rows.length > 0)

  useEffect(() => {
    if (rows.length && !autoCollapsed.current) {
      setSearchExpanded(false)
      autoCollapsed.current = true
    }
  }, [rows.length])

  const filtered = useMemo(() => rows.filter(r =>
    (!onlyFavorites || r.data.favorite) &&
    (!direction || r.data.direction === direction) &&
    (!level || r.data.level === level) &&
    (!format || (r.data.work_formats || [r.data.work_format]).includes(format)) &&
    (!region || [r.data.region, ...(r.data.region_parents || [])].join(' ').toLocaleLowerCase().includes(region.toLocaleLowerCase())) &&
    (r.data.title + ' ' + r.data.company).toLocaleLowerCase().includes(search.toLocaleLowerCase())
  ).sort((a, b) => sort === 'company'
    ? a.data.company.localeCompare(b.data.company, 'ru') || a.data.title.localeCompare(b.data.title, 'ru')
    : sort === 'newest'
      ? b.created_at.localeCompare(a.created_at)
      : (b.data.match?.score || 0) - (a.data.match?.score || 0) || b.created_at.localeCompare(a.created_at)),
  [rows, onlyFavorites, direction, level, format, region, search, sort])

  useEffect(() => setVisibleCount(PAGE_SIZE), [onlyFavorites, direction, level, format, region, search, sort])
  const shown = filtered.slice(0, visibleCount)
  const clearFilters = () => { setSearch(''); setOnlyFavorites(false); setRegion(''); setFormat(''); setDirection(''); setLevel('') }

  return <>
    <section className="panel vacancy-search-panel" aria-labelledby="hh-search-title">
      <div className="section-heading">
        <div className="vacancy-search-heading"><span className="source-icon"><BriefcaseBusiness size={21}/></span><div><span className="eyebrow">ИСТОЧНИК ВАКАНСИЙ</span><h2 id="hh-search-title">Поиск в HeadHunter</h2></div></div>
        <div className="vacancy-search-controls"><span className={'source-status ' + (connections.hh ? 'connected' : 'disconnected')}>
          <span className="live-dot"/>{connections.hh ? 'Подключён' : 'Не подключён'}
        </span><button className="btn secondary vacancy-search-toggle" type="button" aria-expanded={searchExpanded} aria-controls="hh-search-settings" onClick={() => setSearchExpanded(value => !value)}>{searchExpanded ? 'Свернуть поиск' : 'Настроить поиск'}{searchExpanded ? <ChevronUp size={17}/> : <ChevronDown size={17}/>}</button></div>
      </div>
      {!searchExpanded && <p className="vacancy-search-summary">{directionName[direction || profile.direction]} · {level || profile.level} · {region.trim() || profile.regions.join(', ') || 'Казахстан'}</p>}
      <div id="hh-search-settings" hidden={!searchExpanded}>
      <p className="muted">Укажите требования к роли. Найденные вакансии сохранятся здесь, чтобы вы могли сравнить их и подготовить отклик.</p>
      <div className="vacancy-search-fields">
        <Field label="Поисковая фраза HH"><input aria-label="Поисковая фраза HH" value={hhText} onChange={e => setHhText(e.target.value)} placeholder={directionName[direction || profile.direction]}/></Field>
        <Field label="Направление"><select aria-label="Фильтр направления" value={direction} onChange={e => setDirection(e.target.value)}><option value="">Из профиля · {directionName[profile.direction]}</option>{Object.entries(directionName).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></Field>
        <Field label="Уровень"><select aria-label="Фильтр уровня" value={level} onChange={e => setLevel(e.target.value)}><option value="">Из профиля · {profile.level}</option><option value="junior">Junior</option><option value="middle">Middle</option></select></Field>
        <Field label="Регион"><input value={region} onChange={e => setRegion(e.target.value)} placeholder={profile.regions.join(', ') || 'Казахстан'}/></Field>
        <Field label="Формат работы"><select aria-label="Формат работы" value={format} onChange={e => setFormat(e.target.value)}><option value="">Из профиля · {workFormatName[profile.work_format]}</option><option value="remote">Удалённо</option><option value="office">Офис</option><option value="hybrid">Гибрид</option></select></Field>
      </div>
      <div className="vacancy-search-actions">
        <div className="vacancy-search-options">
          <Field label="Требуемый опыт"><select aria-label="Опыт для поиска" value={experienceScope} onChange={e => setExperienceScope(e.target.value as 'strict' | 'broader')}><option value="broader">Расширенный</option><option value="strict">Точный</option></select></Field>
          <Field label="Размер подборки"><select aria-label="Сколько вакансий загрузить" value={maxResults} onChange={e => setMaxResults(Number(e.target.value))}><option value={20}>До 20</option><option value={50}>До 50</option><option value={100}>До 100</option></select></Field>
        </div>
        <button className="btn primary" disabled={!connections.hh} onClick={() => act(() => api('/vacancies/hh/sync', 'POST', {
          text: hhText.trim() || directionName[direction || profile.direction],
          regions: region.trim() ? [region.trim()] : profile.regions,
          direction: direction || profile.direction, level: level || profile.level,
          work_format: format || profile.work_format, max_results: maxResults, experience_scope: experienceScope
        }))}>Обновить вакансии <ArrowRight size={17}/></button>
      </div>
      <p className="source-helper">Расширенный опыт: junior включает 1–3 года, middle — 3–6 лет. Оценка соответствия выполняется отдельно по выбранному CV.</p>
      {connections.hh_last && <p className="source-last">Последняя попытка: {new Date(connections.hh_last.created_at).toLocaleString('ru-RU')} · {statusName[connections.hh_last.status]}{connections.hh_last.error && <span className="error-text"> · {connections.hh_last.error}</span>}</p>}
      </div>
    </section>

    <section className="vacancy-results" aria-labelledby="vacancy-results-title">
      <div className="section-heading vacancy-results-heading"><div><span className="eyebrow">ВАША ПОДБОРКА</span><h2 id="vacancy-results-title">Сохранённые вакансии <span className="result-count" aria-live="polite">{filtered.length} из {rows.length}</span></h2></div><button className="btn secondary" disabled={!cv || !filtered.length} onClick={() => act(() => api('/vacancies/rank', 'POST', {cv_id: cv?.id, vacancy_ids: filtered.slice(0, 20).map(r => r.id)}))}><Sparkles size={17}/>Оценить соответствие · до 20</button></div>
      {!cv && <p className="muted">Чтобы оценить соответствие, сначала подтвердите резюме. Смотреть вакансии и готовить отклик можно уже сейчас.</p>}
      <div className="vacancy-toolbar"><div className="search"><Search size={19}/><input aria-label="Поиск среди сохранённых вакансий" placeholder="Название или компания в сохранённом списке" value={search} onChange={e => setSearch(e.target.value)}/></div><label className="sort-control"><span>Сортировка</span><select aria-label="Сортировка вакансий" value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="match">По соответствию</option><option value="newest">Сначала новые</option><option value="company">По компании</option></select></label><button className={'btn secondary favorites-filter ' + (onlyFavorites ? 'selected' : '')} aria-pressed={onlyFavorites} onClick={() => setOnlyFavorites(!onlyFavorites)}><Bookmark size={17} fill={onlyFavorites ? 'currentColor' : 'none'}/>Избранное</button></div>
      <p className="filter-context"><SlidersHorizontal size={16}/>Направление, уровень, регион и формат из поиска HH также фильтруют эту подборку.</p>
      <div className="vacancy-grid">{shown.map(r => <article className="panel vacancy-card" key={r.id}>
        <div className="section-heading"><span className="company-avatar" aria-hidden="true">{(r.data.company || 'К')[0]}</span><button className={'icon-button ' + (r.data.favorite ? 'bookmarked' : '')} aria-label={r.data.favorite ? 'Убрать из избранного' : 'В избранное'} aria-pressed={r.data.favorite} onClick={() => act(() => api('/vacancies/' + r.id + '/favorite', 'POST', undefined, r.updated_at))}><Bookmark size={20} fill={r.data.favorite ? 'currentColor' : 'none'}/></button></div>
        <p className="company-name">{r.data.company || 'Компания не указана'}</p><h3>{r.data.title}</h3>
        <div className="tags"><span>{r.data.region}</span><span>{r.data.level}</span>{r.data.hh_experience && <span>Опыт HH: {r.data.hh_experience}</span>}<span>{workFormatName[r.data.work_format] || r.data.work_format}</span></div>
        {r.data.match ? <div className="match"><strong>{r.data.match.score}% соответствие{(r.data.match_stale || r.data.match.cv_id !== cv?.id) ? ' · устарело для выбранного CV' : ''}</strong><p>{r.data.match.reasons.join(' ')}</p><small>Совпадает: {r.data.match.matching_skills.join(', ') || '—'}</small><small>Развить: {r.data.match.missing_skills.join(', ') || '—'}</small></div> : <p className="vacancy-excerpt">{r.data.description.slice(0, 210)}{r.data.description.length > 210 && '…'}</p>}
        <details><summary>Полное описание</summary><p className="pre-wrap">{r.data.description}</p></details>
        <div className="card-actions"><button className="text-button" onClick={() => select(r.id)}>Подготовить отклик <ArrowRight size={17}/></button>{r.data.url && <a className="icon-button" href={r.data.url} target="_blank" rel="noreferrer" aria-label="Оригинал вакансии в HeadHunter"><ExternalLink size={18}/></a>}</div>
      </article>)}</div>
      {filtered.length > visibleCount && <div className="load-more"><p>Показано {shown.length} из {filtered.length}</p><button className="btn secondary" onClick={() => setVisibleCount(count => count + PAGE_SIZE)}>Показать ещё {Math.min(PAGE_SIZE, filtered.length - visibleCount)}</button></div>}
      {!filtered.length && (rows.length ? <div className="panel filter-empty"><Empty icon={Search} title="По этим условиям вакансий нет" text="Измените поисковую фразу или фильтры, чтобы увидеть сохранённые предложения."/><button className="btn secondary" onClick={clearFilters}>Сбросить фильтры</button></div> : <Empty icon={BriefcaseBusiness} title="Здесь появятся ваши возможности" text={connections.hh ? 'Нажмите «Обновить вакансии»: найдём предложения по вашему направлению и уровню.' : 'После подключения HeadHunter здесь появятся вакансии для вашего профиля.'}/>)}
    </section>
  </>
}
