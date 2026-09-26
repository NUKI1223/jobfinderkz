import { ProfileData, User, AuthResult, CVFacts, ParseDraft, Fragment, DocumentBlock, Turn, Job, Connections, Availability, Statistics, UsageSummary, UsageOperation, QuestionInput, SourceRef, Segment, Workspace, Direction, Level, Language, Evaluation } from './models'
import { useState } from 'react'
import { api } from './api'
import { Action } from './shared'
import { Field } from './ui'

export function ReconcileUsage({operation,act}:{operation:string;act:Action}) {
  const [outcome,setOutcome]=useState('not_charged'),[amount,setAmount]=useState(''),[evidence,setEvidence]=useState('')
  return <details><summary>Сверить расход</summary><form onSubmit={e=>{e.preventDefault();act(()=>api(`/admin/usage/${encodeURIComponent(operation)}/reconcile`,'POST',{
    outcome,amount:amount||null,evidence}),'Сверка сохранена. Автоматический повтор запроса не выполняется.')}}>
    <Field label="Результат сверки"><select value={outcome} onChange={e=>setOutcome(e.target.value)}><option value="not_charged">Провайдер подтвердил: не списано</option><option value="charged">Списано, сумма известна</option><option value="result_lost">Результат утрачен</option></select></Field>
    {outcome!=='not_charged'&&<Field label="Сумма USD по данным провайдера"><input type="number" min="0" step="0.000000001" required={outcome==='charged'} value={amount} onChange={e=>setAmount(e.target.value)}/></Field>}
    <Field label="Основание сверки: идентификатор запроса или подтверждение провайдера"><textarea required minLength={10} maxLength={2000} value={evidence} onChange={e=>setEvidence(e.target.value)}/></Field>
    <p className="muted">Без известной суммы резерв сохраняется. После подтверждённого списания повтор заблокирован.</p><button className="btn secondary">Сохранить сверку</button>
  </form></details>
}
