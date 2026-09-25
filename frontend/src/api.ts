export type Data = Record<string, any>
export type Entry = {id: string; kind: string; status: string; data: Data; created_at: string; updated_at: string}
let csrf = ''
let userScope = ''
export function setCSRF(value: string) { csrf = value }
export function setRequestScope(value: string) { userScope = value }
const pending = new Map<string, Promise<any>>()
const keys = new Map<string, string>()
const idempotentPaths = new Set(['/vacancies/rank','/vacancies/hh/sync','/documents','/plans','/admin/materials'])
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  if (method === 'POST' && idempotentPaths.has(path)) {
    // Persist only a digest and random key, never CVs or vacancy contents.
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(userScope + path + JSON.stringify(body)))
    const identity = 'jobfinder-request:' + Array.from(new Uint8Array(digest), b=>b.toString(16).padStart(2,'0')).join('')
    if (pending.has(identity)) return pending.get(identity)!
    let key = keys.get(identity)
    try { key ||= sessionStorage.getItem(identity) || undefined } catch { /* memory fallback */ }
    key ||= crypto.randomUUID()
    keys.set(identity, key)
    try { sessionStorage.setItem(identity, key) } catch { /* memory fallback */ }
    const request = send<T>(path, method, body, key).then(result=>{
      keys.delete(identity)
      try { sessionStorage.removeItem(identity) } catch { /* memory fallback */ }
      return result
    }).finally(()=>pending.delete(identity))
    pending.set(identity, request)
    return request
  }
  return send<T>(path, method, body)
}
async function send<T>(path: string, method: string, body?: unknown, key?: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (key) headers['Idempotency-Key'] = key
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
