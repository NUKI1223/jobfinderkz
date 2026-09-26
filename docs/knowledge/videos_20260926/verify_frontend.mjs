import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
const batch = JSON.parse(readFileSync(new URL('./frontend_junior.json', import.meta.url)));
const q = batch.questions.find(q => q.key === 'type-guard');
const dir = mkdtempSync(join(tmpdir(), 'jobfinder-video-typescript-'));
try {
  const file = join(dir, 'guard.ts');
  writeFileSync(file, q.task_solution + '\n' + `
if (format(' hi ') !== 'hi') throw new Error('string branch');
if (format(2) !== '2.00') throw new Error('number branch');
if (format('') !== '') throw new Error('empty string');
if (format(-1.5) !== '-1.50') throw new Error('negative');
`);
  let result = spawnSync(resolve('frontend/node_modules/.bin/tsc'),
    ['--strict', '--target', 'ES2020', '--module', 'commonjs', '--skipLibCheck', '--outDir', dir, file], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr + result.stdout);
  result = spawnSync(process.execPath, [join(dir, 'guard.js')], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr + result.stdout);
  console.log('Reviewed type-guard solution: strict TypeScript and 4 runtime cases passed.');
} finally { rmSync(dir, { recursive: true, force: true }); }
