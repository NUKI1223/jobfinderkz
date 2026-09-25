import { Data, Entry } from './api'

function timestamp(seconds:number) {
  const value=Math.max(0,Math.floor(seconds))
  return `${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`
}

export function SourceReview({question,sources,start,end}:{question:Entry;sources:Entry[];start:number;end:number}) {
  return <section className="source-review" aria-label="Сверка с источником">
    <h3>Сверка с источником</h3>
    {question.data.review_note&&<p>{question.data.review_note}</p>}
    {question.data.review_scope&&<p className="muted">{question.data.review_scope}</p>}
    {(question.data.sources||[]).map((reference:Data,index:number)=>{
      const source=sources.find(s=>s.id===reference.source_id)
      const from=question.data.sources.length===1?start:reference.start
      const until=question.data.sources.length===1?end:reference.end
      const segments=(source?.data.transcript?.segments||[]).filter((s:Data)=>s.end>=from&&s.start<=until)
      const video=String(reference.video_id||'')
      const validVideo=/^[A-Za-z0-9_-]{11}$/.test(video)
      const link=(seconds:number)=>`https://www.youtube.com/watch?v=${encodeURIComponent(video)}&t=${Math.max(0,Math.floor(seconds))}s`
      return <div key={`${reference.source_id}-${index}`}>
        {validVideo&&<a className="material-link" href={link(from)} target="_blank" rel="noreferrer">Открыть видео · {timestamp(from)}–{timestamp(until)}</a>}
        <details className="space-top"><summary>Субтитры этого обсуждения · {segments.length} фрагментов</summary>
          <p className="muted">Проверьте спорные слова по видео. Субтитры могут содержать ошибки; ответ кандидата и эталон редактируются отдельно.</p>
          <div className="transcript">{segments.map((segment:Data,i:number)=><p key={i}>
            {validVideo?<a href={link(segment.start)} target="_blank" rel="noreferrer">{timestamp(segment.start)}</a>:<span>{timestamp(segment.start)}</span>}
            <span>{segment.speaker&&<strong>{segment.speaker}: </strong>}{segment.text}</span>
          </p>)}</div>
          {!segments.length&&<p className="muted">В этом интервале нет сохранённых субтитров. Проверьте таймкоды и источник.</p>}
        </details>
      </div>
    })}
  </section>
}
