import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fixtures, referenceTraceId} from './trace_id_reference.mjs';

test('committed synthetic vectors match the JS Number reference', () => {
  const saved = JSON.parse(fs.readFileSync(new URL('./fixtures/trace_id_vectors.json', import.meta.url)));
  assert.equal(saved.target_runtime_executed, false);
  assert.deepEqual(saved.vectors, fixtures());
});

test('synthetic clock and random inputs both affect the trace ID', () => {
  const zeros = [0, 0, 0, 0, 0, 0];
  const first = referenceTraceId(1, zeros);
  assert.notEqual(referenceTraceId(2, zeros), first);
  assert.notEqual(referenceTraceId(1, [0, 0, 0, 0, 0, 0.5]), first);
});

test('browser multiplication rounds before unsigned conversion', () => {
  const exactLow32 = Number((0x9e3779b1n * 0x7fffffffn) & 0xffffffffn);
  assert.equal((0x9e3779b1 * 0x7fffffff) >>> 0, 3788015616);
  assert.notEqual((0x9e3779b1 * 0x7fffffff) >>> 0, exactLow32);
});
