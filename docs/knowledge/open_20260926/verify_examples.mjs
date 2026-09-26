// Executes only the reviewed local solutions, not downloaded code.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const questions = ['junior', 'middle'].flatMap(level =>
  JSON.parse(readFileSync(new URL(`frontend_${level}.json`, import.meta.url))).questions);
const expected = {
  unary: [1, false, 0, true],
  'number-wrapper': [true, false, false, 'object'],
  'duplicate-key': { a: 'three', b: 'two' },
  'iife-return': 'number',
  'sparse-array': [11, false, 4, 22],
  'reduce-seed': [1, 2, 0, 1, 2, 3],
  'map-return': [2, 4, 6],
  'throw-flow': ['Hello world!'],
};
assert.equal(questions.length, 8);
for (const q of questions) {
  let extra = '';
  if (q.key === 'map-return') extra = '\nassert.equal(broken.length, 3); for (let i=0;i<3;i++) { assert.equal(Object.hasOwn(broken,i),true); assert.equal(broken[i],undefined); }';
  if (q.key === 'sparse-array') extra = '\nassert.equal(Object.hasOwn(mapped,3),false); assert.equal(mapped[3],undefined); assert.equal(mapped.length,11);';
  if (q.key === 'reduce-seed') extra = '\nassert.deepEqual(input,[[0,1],[2,3]]); assert.deepEqual([].reduce((acc,cur)=>acc.concat(cur),[1,2]),[1,2]); assert.throws(()=>[].reduce((a,b)=>a+b),TypeError);';
  assert.deepEqual(new Function('assert', q.task_solution + extra + '\nreturn result;')(assert), expected[q.key], q.key);
}
console.log('8 reviewed JavaScript solutions passed (including holes, undefined and empty reduce).');
