import React, { useEffect, useRef, useState } from 'react'
import { api, directionName } from './api'
import { ProfileData } from './models'
import { Field } from './ui'
import './study.css'

type Status = 'new'|'repeat'|'done'
type Item = {id:string;question:string;topic:string;direction:string;level:string;language:string;status:Status;updated:boolean}
type Catalog = {items:Item[];total:number;done:number;repeat:number;topics:string[];next_offset:number|null}
type Card = {item:Item;content_version:string;task:string;task_solution:string;reference_answer:string;rubric:string[];materials:{id:string;url:string;text:string}[];progress:{revision:string;answer:string;status:Status;updated:boolean;history:{answer:string;content_version:string}[]}}
export type StudyGuard = React.MutableRefObject<null|(()=>Promise<boolean>)>
export function Study({mode,profile,active,guard}:{mode:'question'|'task';profile:ProfileData;active:boolean;guard:StudyGuard}) {
  const [filters,setFilters]=useState({direction:profile.direction as string,level:profile.level as string,language:profile.language as string,topic:'',search:'',status:''})
  const [catalog,setCatalog]=useState<Catalog|null>(null),[card,setCard]=useState<Card|null>(null)
  const [answer,setAnswer]=useState(''),[status,setStatus]=useState<Status>('new'),[revealed,setRevealed]=useState(false)
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false)
  const dialog=useRef<HTMLDialogElement>(null),resolve=useRef<((value:boolean)=>void)|null>(null),scroll=useRef(0),epoch=useRef(0),heading=useRef<HTMLHeadingElement>(null)
  const dirty=!!card&&(answer!==card.progress.answer||status!==card.progress.status)
  const labels:Record<Status,string>={new:mode==='question'?'Не изучено':'Не начато',repeat:'Повторить',done:mode==='question'?'Знаю':'Решено'}
  const query=(offset=0)=>new URLSearchParams(Object.fromEntries(Object.entries({...filters,mode,offset:String(offset)}).filter(([,v])=>v!==''))).toString()
  async function load(offset=0) {
    const request=++epoch.current;setLoading(true)
    try { const data=await api<Catalog>('/study/items?'+query(offset));if(request===epoch.current)setCatalog(old=>({...data,items:offset?[...(old?.items||[]),...data.items]:data.items})) }
    catch(e){if(request===epoch.current)setError((e as Error).message)}finally{if(request===epoch.current)setLoading(false)}
  }
  useEffect(()=>{if(active)load();else setCatalog(null)},[JSON.stringify(filters)])
  useEffect(()=>{if(active&&!catalog)load();if(!active)setRevealed(false)},[active])
  useEffect(()=>{setFilters(f=>({...f,direction:profile.direction,level:profile.level,language:profile.language,topic:''}))},[profile.direction,profile.level,profile.language])
  async function save() {
    if(!card||busy)return false
    setBusy(true);setError('');setNotice('')
    try { const saved=await api<Card>(`/study/items/${card.item.id}/progress?mode=${mode}`,'PUT',{answer,status,content_version:card.content_version},card.progress.revision)
      setCard(saved);setAnswer(saved.progress.answer);setStatus(saved.progress.status);setNotice('Ответ и самооценка сохранены')
      setCatalog(old=>old?{...old,items:old.items.map(i=>i.id===saved.item.id?saved.item:i).filter(i=>!filters.status||i.status===filters.status),total:old.total-Number(!!filters.status&&saved.item.status!==filters.status),next_offset:old.next_offset===null?null:old.next_offset-Number(!!filters.status&&saved.item.status!==filters.status),done:old.done+Number(saved.item.status==='done')-Number(card.item.status==='done'),repeat:old.repeat+Number(saved.item.status==='repeat')-Number(card.item.status==='repeat')}:old)
      return true
    }catch(e){setError((e as Error).message);return false}finally{setBusy(false)}
  }
  async function canLeave() {if(busy)return false;if(!dirty)return true;dialog.current?.showModal();return new Promise<boolean>(r=>{resolve.current=r})}
  function settle(value:boolean){dialog.current?.close();resolve.current?.(value);resolve.current=null}
  useEffect(()=>{if(active){guard.current=canLeave;return()=>{if(guard.current===canLeave)guard.current=null}}},[active,dirty,busy,card,answer,status])
  useEffect(()=>{if(!active||!dirty)return;const block=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',block);return()=>window.removeEventListener('beforeunload',block)},[active,dirty])
  async function open(id:string) {
    if(!await canLeave())return
    setError('');setNotice('');setBusy(true)
    try {const data=await api<Card>(`/study/items/${id}?mode=${mode}`);if(!card)scroll.current=window.scrollY;setCard(data);setAnswer(data.progress.answer);setStatus(data.progress.status);setRevealed(false);requestAnimationFrame(()=>{heading.current?.focus();window.scrollTo(0,0)})}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function back(){if(await canLeave()){setCard(null);setRevealed(false);setNotice('');requestAnimationFrame(()=>window.scrollTo(0,scroll.current))}}
  const change=(key:string,value:string)=>{setFilters(f=>({...f,[key]:value,...(key==='direction'||key==='level'||key==='language'?{topic:''}:{})}));setError('')}
  if(!active)return null
  return <div>
    <p className="muted">Бесплатная самопроверка без CV и вакансии. Отметки — ваша самооценка, они не входят в оценки интервью.{mode==='task'?' Код не выполняется.':''}</p>
    {error&&<div role="alert" className="alert error">{error}</div>}{notice&&<p className="study-save-notice" role="status">{notice}</p>}
    <div hidden={!!card}>
      <section className="panel study-filters">
        <Field label="Направление"><select value={filters.direction} onChange={e=>change('direction',e.target.value)}>{Object.entries(directionName).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field>
        <Field label="Уровень"><select value={filters.level} onChange={e=>change('level',e.target.value)}><option>junior</option><option>middle</option></select></Field>
        <Field label="Язык"><select value={filters.language} onChange={e=>change('language',e.target.value)}><option value="ru">RU</option><option value="en">EN</option></select></Field>
        <Field label="Тема"><select value={filters.topic} onChange={e=>change('topic',e.target.value)}><option value="">Все темы</option>{catalog?.topics.map(t=><option key={t}>{t}</option>)}</select></Field>
        <Field label="Поиск"><input value={filters.search} onChange={e=>change('search',e.target.value)} placeholder="Вопрос или тема"/></Field>
        <Field label="Личный статус"><select value={filters.status} onChange={e=>change('status',e.target.value)}><option value="">Все отметки</option>{Object.entries(labels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></Field>
        <div className="study-filter-actions"><p className="muted">Выберите карточку и ответьте своими словами.</p><button className="text-button" disabled={!filters.topic&&!filters.search&&!filters.status} onClick={()=>setFilters(f=>({...f,topic:'',search:'',status:''}))}>Сбросить фильтры</button></div>
      </section>
      <p aria-live="polite">{loading?'Загружаем…':`Найдено: ${catalog?.total||0} · ${mode==='question'?'Изучено':'Решено'}: ${catalog?.done||0} · На повторение: ${catalog?.repeat||0}`}</p>
      {!loading&&catalog?.total===0&&<section className="panel"><h2>Пока нет опубликованных карточек</h2><p>Попробуйте другое направление, язык или фильтр. Здесь появляется только проверенное содержимое базы.</p></section>}
      <div className="study-list">{catalog?.items.map(i=><button className="panel study-item" data-status={i.status} key={i.id} onClick={()=>open(i.id)} disabled={busy||loading}><span className="muted">{i.topic} · {i.level} · {i.language.toUpperCase()}</span><strong>{i.question}</strong><span>{i.updated?'Материал обновлён':labels[i.status]}</span></button>)}</div>
      {catalog?.next_offset!=null&&<button className="btn secondary space-top" disabled={loading} onClick={()=>load(catalog.next_offset!)}>Показать ещё 20</button>}
    </div>
    {card&&<section className="panel study-card">
      <button className="text-button" disabled={busy} onClick={back}>Назад к списку</button>
      <p className="muted">{card.item.topic} · {card.item.language.toUpperCase()}</p><h2 ref={heading} tabIndex={-1}>{card.item.question}</h2>
      {card.progress.updated&&<p className="alert">Материал обновлён. Прежняя отметка больше не считается актуальной. Старый ответ сохранён в поле ниже для повторной проверки.</p>}
      {mode==='task'&&<><h3>Условие</h3><pre>{card.task}</pre></>}
      <Field label={mode==='question'?'Ваш ответ':'Ваше решение — текст или код'}><textarea rows={9} value={answer} maxLength={50000} onChange={e=>setAnswer(e.target.value)} disabled={busy}/></Field>
      <fieldset className="study-rating" disabled={busy}><legend>Самооценка</legend><div className="button-row">{Object.entries(labels).map(([id,label])=><button type="button" key={id} aria-pressed={status===id} onClick={()=>setStatus(id as Status)}>{label}</button>)}</div></fieldset>
      <div className="button-row"><button className="btn primary" disabled={busy} onClick={save}>{busy?'Сохраняем…':'Сохранить ответ и отметку'}</button><span role="status">{dirty?'Есть несохранённые изменения':''}</span></div>
      <button className="btn secondary space-top" aria-expanded={revealed} onClick={()=>setRevealed(!revealed)}>{revealed?'Скрыть разбор':mode==='question'?'Раскрыть проверенный эталон':'Раскрыть решение и разбор'}</button>
      {revealed&&<div className="study-reference">{mode==='task'&&<><h3>Проверенное решение практики</h3><pre>{card.task_solution||'Отдельное проверенное решение пока не опубликовано.'}</pre></>}<h3>{mode==='task'?'Теоретический разбор':'Проверенный эталон'}</h3><pre>{card.reference_answer}</pre><h3>{mode==='task'?'Критерии теоретического ответа':'Критерии самопроверки'}</h3><ul>{card.rubric.map((r,i)=><li key={i}>{r}</li>)}</ul></div>}
      <h3>Материалы</h3>{card.materials.map((m,i)=><details key={m.id}><summary>Материал {i+1}</summary><a href={/^https?:\/\//.test(m.url)?m.url:undefined} target="_blank" rel="noreferrer">Открыть источник</a><pre>{m.text}</pre></details>)}
      {!!card.progress.history.length&&<details><summary>Ответы к прежним версиям</summary>{card.progress.history.map((h,i)=><pre key={i}>{h.answer||'Пустой ответ'}</pre>)}</details>}
    </section>}
    <dialog ref={dialog} className="study-dialog" onCancel={e=>{e.preventDefault();settle(false)}}><h2>Сохранить изменения?</h2><p>В ответе или самооценке есть несохранённые изменения.</p><div className="button-row"><button className="btn primary" disabled={busy} onClick={async()=>{if(await save())settle(true);else settle(false)}}>Сохранить</button><button className="btn secondary" disabled={busy} onClick={()=>{if(card){setAnswer(card.progress.answer);setStatus(card.progress.status)}settle(true)}}>Не сохранять</button><button className="btn secondary" disabled={busy} onClick={()=>settle(false)}>Остаться</button></div></dialog>
  </div>
}
