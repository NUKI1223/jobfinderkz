// Durable, secret-free source snapshots. Run from any working directory.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const docs = path.join(root, 'docs')
const stateFile = path.join(docs, '.source-state.json')
const extensions = new Set(['.py','.ts','.tsx','.css','.html','.json','.ini','.yaml','.yml','.mjs','.ps1','.txt','.conf','.sql'])
const skipped = new Set(['node_modules','dist','__pycache__','.pytest_cache','test-results','playwright-report','.git','.venv','storage'])
const named = new Set(['Dockerfile','.dockerignore'])
const files = ['AGENTS.md','README.md','.gitignore','.env.example','compose.yaml']
function collect(relative) {
  for(const item of fs.readdirSync(path.join(root,relative), {withFileTypes:true})) {
    if(skipped.has(item.name) || item.name.startsWith('.env')) continue
    const next = relative + '/' + item.name
    if(item.isDirectory()) collect(next)
    else if(extensions.has(path.extname(item.name)) || named.has(item.name)) files.push(next)
  }
}
for(const folder of ['backend','frontend','scripts']) if(fs.existsSync(path.join(root,folder))) collect(folder)
const previous = fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile,'utf8')) : {}
const current = {}
const timestamp = new Date().toISOString()
let snapshot = '# Полный текущий код JobFinderKZ\n\nСнимок: '+timestamp+'\n\nСекреты, .env, пользовательские данные и зависимости node_modules исключены.\n'
let changes = '\n## '+timestamp+'\n'
let count=0
for(const relative of [...new Set(files)].sort()) {
  if(!fs.existsSync(path.join(root,relative))) continue
  const content = fs.readFileSync(path.join(root,relative),'utf8')
  const hash = crypto.createHash('sha256').update(content).digest('hex')
  current[relative] = hash
  const block = '\n### '+relative+'\n\nSHA-256: `'+hash+'`\n\n````'+path.extname(relative).slice(1)+'\n'+content+'\n````\n'
  snapshot += block
  if(previous[relative] !== hash) {
    count++
    changes += '\n'+(previous[relative] ? 'Изменён. Предыдущий SHA-256: `'+previous[relative]+'`.' : 'Добавлен в журнал.')+'\n'+block
  }
}
for(const relative of Object.keys(previous)) if(!current[relative]) {count++;changes+='\nУдалён: `'+relative+'` (SHA-256 `'+previous[relative]+'`).\n'}
fs.writeFileSync(path.join(docs,'CODE_SNAPSHOT.md'),snapshot,'utf8')
if(count) {
  const target=path.join(docs,'CODE_CHANGES.md')
  if(!fs.existsSync(target)) fs.writeFileSync(target,'# История кода\n\nПолные версии изменённых файлов после каждого снимка; секреты исключены.\n','utf8')
  fs.appendFileSync(target,changes,'utf8')
}
fs.writeFileSync(stateFile,JSON.stringify(current,null,2)+'\n','utf8')
console.log(`Snapshot: ${Object.keys(current).length} files; ${count} changes recorded.`)
