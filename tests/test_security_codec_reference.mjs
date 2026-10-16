import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  utf16Units, repeatedXor, stagedOffset, numericEncoding, arrayBase64, fixture,
} from './security_codec_reference.mjs';

test('UTF-16 units and numeric encoding do not silently become full Unicode UTF-8', () => {
  assert.deepEqual(utf16Units('\ud83d\ude00'), [0xd83d, 0xde00]);
  assert.equal(Buffer.from(numericEncoding([0xd83d, 0xde00])).toString('hex'), 'eda0bdedb880');
});

test('independent staged reverse operations agree with the simplified bounded value model', () => {
  const values = [...Array.from({length: 256}, (_, i) => i), 256, 2047, 2048, 65535];
  assert.deepEqual(stagedOffset(values), values.map(x => (x ^ 1) + 9));
  assert.deepEqual(repeatedXor([255], [48]), [306]);
  assert.deepEqual(stagedOffset([306]), [316]);
});

test('independent Base64 arithmetic agrees with Node on all byte values and padding boundaries', () => {
  const allBytes = Array.from({length: 256}, (_, i) => i);
  for (let length = 0; length <= allBytes.length; length++) {
    const sample = allBytes.slice(0, length);
    assert.equal(arrayBase64(sample), Buffer.from(sample).toString('base64'));
  }
});

test('checked-in synthetic vectors reproduce without target execution or session material', () => {
  const stored = JSON.parse(fs.readFileSync(new URL('./fixtures/security_codec_vectors.json', import.meta.url)));
  assert.deepEqual(stored, fixture());
  assert.equal(stored.target_code_executed, false);
  assert.equal(stored.real_session_values, false);
});
