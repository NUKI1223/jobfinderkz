export type Data = Record<string, any>
export type Entry = {id: string; kind: string; status: string; data: Data; created_at: string; updated_at: string}
let csrf = ''
export function setCSRF(value: string) { csrf = value }
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (csrf) headers['X-CSRF-Token'] = csrf
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch('/api/v1' + path, {method, credentials: 'same-origin', headers,
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body)})
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: 'Сервер недоступен'}))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Проверьте заполненные поля: ' + (error.detail?.map((x: Data) => x.msg).join(', ') || response.status))
  }
  return response.json()
}
export function fileBody(file: File) { const data = new FormData(); data.append('file', file); return data }
export const directionName: Data = {frontend: 'Frontend', python: 'Python backend', qa: 'QA'}
export const statusName: Data = {draft:'Черновик', review:'На проверке', confirmed:'Подтверждено', saved:'Сохранено', ready:'Готово', active:'В процессе', completed:'Завершено', queued:'В очереди', running:'Выполняется', paused:'Приостановлено', failed:'Ошибка', needs_review:'Нужна проверка расходов', published:'Опубликовано', merged:'Объединено'}
