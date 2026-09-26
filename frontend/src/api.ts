export type {Entry} from './models'
let csrf = ''
let userScope = ''
export function setCSRF(value: string) { csrf = value }
export function setRequestScope(value: string) { userScope = value }
const pending = new Map<string, Promise<any>>()
const keys = new Map<string, string>()
const idempotentPaths = new Set(['/vacancies/rank','/vacancies/hh/sync','/documents','/plans','/admin/materials'])
export async function api<T = any>(path: string, method = 'GET', body?: unknown, revision?: string): Promise<T> {
  if (method === 'POST' && (idempotentPaths.has(path)||/^\/cv\/[^/]+\/parse$/.test(path))) {
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
  if (method === 'POST' && path.includes('/audio') && body instanceof FormData) {
    const file = body.get('file') as File
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    const key = Array.from(new Uint8Array(digest), b=>b.toString(16).padStart(2,'0')).join('')
    return send<T>(path, method, body, key)
  }
  return send<T>(path, method, body, undefined, revision)
}
async function send<T>(path: string, method: string, body?: unknown, key?: string, revision?: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (key) headers['Idempotency-Key'] = key
  if(revision)headers['If-Match']=revision
  if (csrf) headers['X-CSRF-Token'] = csrf
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch('/api/v1' + path, {method, credentials: 'same-origin', headers,
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body)})
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: 'Сервер недоступен'}))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Проверьте заполненные поля: ' + (error.detail?.map((x: {msg:string}) => x.msg).join(', ') || response.status))
  }
  return response.json()
}
export function fileBody(file: File) { const data = new FormData(); data.append('file', file); return data }
export const directionName: Record<string,string> = {frontend: 'Frontend', python: 'Python backend', qa: 'QA'}
export const statusName: Record<string,string> = {draft:'Черновик', review:'На проверке', confirmed:'Подтверждено', saved:'Сохранено', ready:'Готово', active:'В процессе', completed:'Завершено', queued:'В очереди', running:'Выполняется', paused:'Приостановлено', failed:'Ошибка', needs_review:'Нужна проверка расходов', published:'Опубликовано', merged:'Объединено'}
