import type { Direction } from './models'
import type { Entry } from './api'
import { directionName } from './api'

const directions: Direction[] = ['python', 'frontend', 'qa']

export function KnowledgeCoverage({ questions, selected, onSelect }: {
  questions: Entry<'question'>[]
  selected: string
  onSelect: (direction: string) => void
}) {
  const originals = questions.filter(question => question.status === 'published' && !question.data.translation_of)
  return <section className="knowledge-coverage" aria-labelledby="knowledge-coverage-title">
    <div className="knowledge-coverage-heading">
      <div><h2 id="knowledge-coverage-title">Покрытие базы вопросов</h2><p>Опубликованные оригиналы по направлениям. Переводы в счётчик не входят.</p></div>
      <button type="button" className="text-button" onClick={() => onSelect('')} disabled={!selected}>Все направления</button>
    </div>
    <div className="knowledge-coverage-grid">{directions.map(direction => {
      const items = originals.filter(question => question.data.direction === direction)
      const junior = items.filter(question => question.data.level === 'junior').length
      const middle = items.filter(question => question.data.level === 'middle').length
      return <button type="button" key={direction} className={'coverage-card ' + (selected === direction ? 'selected' : '')}
        aria-pressed={selected === direction} aria-label={`Показать вопросы ${directionName[direction]}`}
        onClick={() => onSelect(selected === direction ? '' : direction)}>
        <span className="coverage-top"><strong>{directionName[direction]}</strong><span>{items.length}<small> / 30</small></span></span>
        <progress max={30} value={Math.min(items.length, 30)} aria-label={`${directionName[direction]}: ${items.length} из 30`}/>
        <span className="coverage-levels"><span>Junior {junior}</span><span>Middle {middle}</span></span>
      </button>
    })}</div>
  </section>
}
