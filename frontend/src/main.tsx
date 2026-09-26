import { Study, StudyGuard } from './Study'
import { ProfileData, User, AuthResult, CVFacts, ParseDraft, Fragment, DocumentBlock, Turn, Job, Connections, Availability, Statistics, UsageSummary, UsageOperation, QuestionInput, SourceRef, Segment, Workspace, Direction, Level, Language, Evaluation } from './models'
import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowUpRight, ArrowRight, BriefcaseBusiness, Check, ChevronRight, FileText, GraduationCap, LayoutDashboard, LogOut, Mic, Plus, Search, Settings, ShieldCheck, Sparkles, TrendingUp, Upload, X, Play, Square, Bookmark, ExternalLink, LoaderCircle, CheckCircle2, Clock3, Headphones } from 'lucide-react'
import { api, setCSRF, setRequestScope, fileBody, Entry, directionName, statusName } from './api'
import { Field, Badge, Empty } from './ui'
import { Action, defaultProfile } from './shared'
import { CVPage } from './CVPage'
import { Vacancies } from './Vacancies'
import { Documents } from './Documents'
import { Plans } from './Plans'
import { Interviews } from './Interviews'
import { Stats } from './Stats'
import { Profile } from './Profile'
import { Jobs } from './Jobs'
import { Admin } from './Admin'
import './styles.css'
import '@fontsource-variable/onest'
import './typography.css'
import './design-refresh.css'
import './organic.css'

const tabs = [ ['home','Обзор',LayoutDashboard], ['cv','Моё резюме',FileText], ['vacancy','Вакансии',BriefcaseBusiness], ['document','Документы',FileText], ['question','Вопросы',GraduationCap], ['task','Практические задания',FileText], ['plan','Подготовка',GraduationCap], ['interview','Интервью',Headphones], ['stats','Мой прогресс',TrendingUp] ] as const
const titles: Record<string,string> = {home:'Обзор',cv:'Резюме',vacancy:'Вакансии',document:'Документы',plan:'План подготовки',interview:'Тренировочное интервью',stats:'Прогресс',profile:'Профиль',admin:'База знаний',jobs:'Операции',question:'Вопросы',task:'Практические задания'}

function App() {
  const [user,setUser] = useState<User|null>(null), [loading,setLoading] = useState(true)
  const [tab,rawSetTab] = useState('home'), [error,setError] = useState(''), [notice,setNotice] = useState(''), [busy,setBusy] = useState(false), [version,setVersion] = useState(0)
  const [data,setData] = useState<Workspace>({cv:[],vacancy:[],document:[],plan:[],interview:[]})
  const [jobs,setJobs] = useState<Job[]>([]), [connections,setConnections] = useState<Connections>({})
  const [selectedVacancy,setSelectedVacancy] = useState(''),[selectedCV,setSelectedCV]=useState('')
  const studyGuard:StudyGuard=useRef(null)
  const setTab=async(next:string)=>{if(next===tab)return;if(studyGuard.current&&!await studyGuard.current())return;rawSetTab(next)}
  const refreshEpoch=useRef(0), knownJobs=useRef(''), actionRunning=useRef(false)
  const jobFingerprint=(items:Job[])=>JSON.stringify(items.map(j=>[j.id,j.status]))
  const refresh = async () => {
    const epoch=++refreshEpoch.current
    // Read job state BEFORE records: completion between these requests must never
    // leave a completed job paired with stale interview/document data.
    const freshJobs=await api<Job[]>('/jobs')
    const kinds = ['cv','vacancy','document','plan','interview']
    const results = await Promise.all(kinds.map(k=>api<Entry[]>('/records/'+k)))
    const freshConnections=await api('/connections')
    if(epoch!==refreshEpoch.current)return
    setData(Object.fromEntries(kinds.map((k,i)=>[k,results[i]])) as Workspace)
    setJobs(freshJobs);knownJobs.current=jobFingerprint(freshJobs)
    setConnections(freshConnections); setVersion(v=>v+1)
  }
  useEffect(()=>{api('/auth/me').then(r=>{setRequestScope(r.user.id);setUser(r.user);setCSRF(r.csrf)}).catch(()=>{}).finally(()=>setLoading(false))},[])
  useEffect(()=>{if(user) refresh().catch(e=>setError(e.message))},[user?.id])
  useEffect(()=>{
    if(!user) return
    const timer=setInterval(async()=>{
      try { const next = await api<Job[]>('/jobs')
        if (knownJobs.current!==jobFingerprint(next)) await refresh()
        else setJobs(next)
      } catch { /* next interaction will show the session error */ }
    },3500)
    return ()=>clearInterval(timer)
  },[user?.id])
  const act: Action = async (fn,message) => {
    if(actionRunning.current)return
    actionRunning.current=true
    setError('');setNotice('');setBusy(true)
    try { const result:any = await fn(); if(result?.job_id) setNotice('Операция добавлена. Результат появится автоматически; статус доступен в разделе «Операции».'); else if(message) setNotice(message); if(!result?.skipRefresh) await refresh() }
    catch(e) { setError((e as Error).message) } finally {setBusy(false);actionRunning.current=false}
  }
  const confirmed = data.cv.find(r=>r.id===selectedCV&&r.status==='confirmed')||data.cv.find(r=>r.status==='confirmed')
  const changeUser=(next:User|null)=>{
    setRequestScope(next?.id || '')
    setError('');setNotice('')
    if(next?.id!==user?.id){refreshEpoch.current++;setData({cv:[],vacancy:[],document:[],plan:[],interview:[]});setJobs([]);knownJobs.current='';rawSetTab('home')}
    setUser(next)
  }
  if(loading) return <div className="loading"><LoaderCircle className="spin"/> Загружаем рабочее пространство…</div>
  if(!user) return <Auth onLogin={r=>{changeUser(r.user);setCSRF(r.csrf)}}/>
  const selectVacancy = (id:string) => {setSelectedVacancy(id);setTab('document')}
  return <div className="app">
    <aside className="sidebar"><a className="brand" href="#" onClick={e=>{e.preventDefault();setTab('home')}}><span className="brand-symbol">j<span>.</span></span><span>jobfinder<span className="kz">kz</span></span></a>
      <div className="workspace-label">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav>{tabs.map(([id,label,Icon])=><button key={id} aria-current={tab===id?'page':undefined} className={tab===id?'nav active':'nav'} onClick={()=>{setTab(id);setError('')}}><Icon size={19}/>{label}{id==='vacancy'&&data.vacancy.length>0&&<span className="count">{data.vacancy.length}</span>}</button>)}</nav>
      <div className="sidebar-bottom">
      {user.role==='admin'&&<button className={'nav '+(tab==='admin'?'active':'')} onClick={()=>setTab('admin')}><ShieldCheck size={18}/>База знаний</button>}
      <button className={'nav '+(tab==='jobs'?'active':'')} onClick={()=>setTab('jobs')}><Clock3 size={18}/>Операции {jobs.some(j=>['queued','running'].includes(j.status))&&<span className="live-dot"/>}</button>
      <button className="account" onClick={()=>setTab('profile')}><span className="avatar">{user.email[0].toUpperCase()}</span><span><strong>{user.email.split('@')[0]}</strong><small>{directionName[user.profile.direction]} · {user.profile.level}</small></span><Settings size={16}/></button></div>
    </aside>
    <main><header className="topbar"><span>Карьера начинается с вас</span><span className="local-badge"><span className="live-dot"/>Локальное пространство</span><button className="icon-button" aria-label="Выйти" onClick={async()=>{if(studyGuard.current&&!await studyGuard.current())return;act(async()=>{await api('/auth/logout','POST');changeUser(null);setCSRF('');return {skipRefresh:true}})}}><LogOut size={18}/></button></header>
      <div className="page"><div className="page-heading"><div><h1>{titles[tab]}</h1></div><span className="date">{new Date().toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</span></div>
      {error&&<div className="alert error" role="alert">{error}<button aria-label="Закрыть ошибку" onClick={()=>setError('')}><X size={16}/></button></div>}
      {notice&&<div className="alert success" role="status">{notice}<button aria-label="Закрыть уведомление" onClick={()=>setNotice('')}><X size={16}/></button></div>}
      {busy&&<div className="working" role="status"><LoaderCircle size={16} className="spin"/>Сохраняем…</div>}
      <fieldset className="page-content" disabled={busy}>
      {connections.gemini_free_tier&&<div className="alert">Тестовый режим Gemini Free: используйте вымышленные резюме и ответы без персональных данных. Google может использовать запросы для улучшения моделей. Бесплатная квота зависит от проекта в Google AI Studio.</div>}
      {['vacancy','document','plan'].includes(tab)&&data.cv.some(r=>r.status==='confirmed')&&<Field label="Резюме для этого действия"><select value={confirmed?.id||''} onChange={e=>setSelectedCV(e.target.value)}>{data.cv.filter(r=>r.status==='confirmed').map(r=><option key={r.id} value={r.id}>{r.data.filename} · версия {r.data.version||1}</option>)}</select></Field>}
      <Study mode="question" profile={user.profile} active={tab==='question'} guard={studyGuard}/>
      <Study mode="task" profile={user.profile} active={tab==='task'} guard={studyGuard}/>
      {tab==='home'&&<Dashboard data={data} user={user} go={setTab} connections={connections}/>}
      {tab==='cv'&&<CVPage rows={data.cv} act={act} aiConnected={!!(connections.text_ai??connections.openai)}/>}
      {tab==='vacancy'&&<Vacancies rows={data.vacancy} cv={confirmed} profile={user.profile} connections={connections} act={act} select={selectVacancy}/>}
      {tab==='document'&&<Documents rows={data.document} vacancies={data.vacancy} cv={confirmed} selected={selectedVacancy} act={act}/>}
      {tab==='plan'&&<Plans rows={data.plan} vacancies={data.vacancy} cv={confirmed} act={act}/>}
      {tab==='interview'&&<Interviews rows={data.interview} vacancies={data.vacancy} profile={user.profile} jobs={jobs} audioAvailable={!!connections.audio} act={act}/>}
      {tab==='stats'&&<Stats profile={user.profile} version={version}/>}
      {tab==='profile'&&<Profile user={user} act={act} save={changeUser}/>}
      {tab==='admin'&&user.role==='admin'&&<Admin act={act} version={version}/>}
      {tab==='jobs'&&<Jobs jobs={jobs} act={act}/>}
      </fieldset><footer>JobFinderKZ</footer></div>
    </main>
  </div>
}

function Auth({onLogin}:{onLogin:(data:AuthResult)=>void}) {
  const [register,setRegister]=useState(false),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  return <div className="auth"><div className="auth-story"><div className="brand light"><span className="brand-symbol">j.</span>jobfinder<span className="kz">kz</span></div><h1>Ваша следующая<br/>работа начинается<br/><em>с уверенности.</em></h1><p>От сильного резюме до спокойного интервью.<br/>Пройдите этот путь с понятным планом.</p><div className="auth-path"><FileText/>Резюме<span>→</span><BriefcaseBusiness/>Вакансия<span>→</span><Headphones/>Интервью</div></div>
  <div className="auth-form"><form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try {onLogin(await api('/auth/'+(register?'register':'login'),'POST',{email,password}))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>
    <h2>{register?'Регистрация':'Вход в аккаунт'}</h2><p className="muted">{register?'Создайте аккаунт для сохранения резюме и вакансий.':'Введите email и пароль.'}</p>
    {error&&<div className="alert error" role="alert">{error}</div>}<Field label="Email"><input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} required/></Field><Field label="Пароль"><input type="password" autoComplete={register?'new-password':'current-password'} minLength={10} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} required/></Field><small className="muted">Минимум 10 символов</small>
    <button className="btn primary full" disabled={busy}>{busy?'Подождите…':register?'Создать аккаунт':'Войти'}<ArrowRight size={18}/></button><button type="button" className="text-button full" onClick={()=>setRegister(!register)}>{register?'Уже есть аккаунт? Войти':'Нет аккаунта? Зарегистрироваться'}</button>
  </form></div></div>
}

function Dashboard({data,user,go,connections}:{data:Workspace;user:User;go:(v:string)=>void;connections:Connections}) {
  const cv=data.cv.find(r=>r.status==='confirmed'), sessions=data.interview.filter(r=>r.status==='completed').length
  const days=data.plan.flatMap(p=>p.data.days).filter(d=>d.done).length
  const stages=[['Резюме',!!cv,'cv'],['Вакансия',data.vacancy.length>0,'vacancy'],['Подготовка',data.plan.length>0,'plan'],['Интервью',sessions>0,'interview']] as const
  const next=stages.find(s=>!s[1])||stages[3]
  return <><section className="hero"><div className="hero-copy"><span className="hero-tag"><span className="live-dot"/>РЕЗЮМЕ · ВАКАНСИИ · ПОДГОТОВКА</span><h2>Подготовка к<br/><em>следующей вакансии.</em></h2><p>Добавьте резюме, выберите вакансию и потренируйте ответы на вопросы интервью.</p><button className="btn cream" onClick={()=>go(next[2])}>{cv?'Продолжить':'Добавить резюме'}<ArrowUpRight size={18}/></button></div><div className="hero-visual" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="floating-card"><div className="mini-check"><Check size={22}/></div><div><strong>Следующий шаг</strong><span>{next[0]}</span></div><ArrowUpRight size={24}/></div></div></section>
  <section className="study-entry"><div><h2>Подготовка в своём темпе</h2><p>Вопросы и практика с самопроверкой. Можно начать без резюме и вакансии.</p></div><div className="button-row"><button className="btn primary" onClick={()=>go('question')}>Изучать вопросы<ArrowRight size={18}/></button><button className="btn secondary" onClick={()=>go('task')}>Перейти к практике</button></div></section><section className="metrics"><Metric icon={BriefcaseBusiness} value={data.vacancy.length} label="Сохранённых вакансий"/><Metric icon={CheckCircle2} value={days} label="Дней подготовки пройдено"/><Metric icon={Headphones} value={sessions} label="Интервью завершено"/></section>
  <div className="dashboard-grid"><section className="panel"><div className="section-heading"><div><h2>Ваш карьерный маршрут</h2></div><span className="muted">{stages.filter(s=>s[1]).length} из 4</span></div><div className="journey">{stages.map(([name,done,target],i)=><button key={target} onClick={()=>go(target)}><span className={'step-number '+(done?'done':'')}>{done?<Check size={16}/>:String(i+1).padStart(2,'0')}</span><span><strong>{name}</strong><small>{['Расскажите о своём опыте','Выберите подходящую роль','Заполните пробелы в знаниях','Отрепетируйте свои ответы'][i]}</small></span><ChevronRight size={18}/></button>)}</div></section>
  <section className="panel next-panel"><GraduationCap size={36}/><h2>{cv?'Тренировочное интервью':'Проверка резюме'}</h2><p>{cv?'Пять вопросов, оценка ответов и темы для повторения.':'Загрузите PDF или DOCX и подтвердите извлечённые факты перед подбором.'}</p><button className="text-button" onClick={()=>go(cv?'interview':'cv')}>{cv?'Начать практику':'Перейти к резюме'}<ArrowRight size={17}/></button></section></div>
  <div className="connection-note"><ShieldCheck size={19}/><span>Ваш профиль: <strong>{directionName[user.profile.direction]} · {user.profile.level}</strong>. {(connections.text_ai??connections.openai)?`Текстовый ИИ подключён: ${connections.text_provider==='gemini'?'Gemini':'OpenAI'}.`:'ИИ пока не подключён. Разделы резюме можно проверить самостоятельно.'}</span><button className="text-button" onClick={()=>go('profile')}>Настроить<ArrowUpRight size={15}/></button></div></>
}
function Metric({icon:Icon,value,label}:{icon:typeof FileText;value:number;label:string}) {return <div className="metric"><div className="metric-top"><span className="metric-icon"><Icon size={20}/></span><span className="metric-value">{value}</span></div><strong>{label}</strong></div>}

createRoot(document.getElementById('root')!).render(<App/>);
