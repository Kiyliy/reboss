// Independently authored arithmetic reference, not extracted target code.
// No target imports, network, browser environment, or session inputs.
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export function utf16Units(text) {
  const units = [];
  for (let i = 0; i < text.length; i++) units.push(text.charCodeAt(i));
  return units;
}

export function repeatedXor(bytes, key) {
  return bytes.map((value, index) => (value + 3) ^ key[index % key.length]);
}

export function stagedOffset(values) {
  const result = values.map(value => value ^ 1);
  for (let i = 0; i < result.length; i++) result[i] += 1;
  result.reverse();
  for (let i = 0; i < result.length; i++) result[i] += 8;
  return result.reverse();
}

export function numericEncoding(values) {
  const output = [];
  for (const value of values) {
    if (value < 128) output.push(value);
    else if (value < 2048) output.push((value >> 6) | 192, (value & 63) | 128);
    else output.push((value >> 12) | 224, ((value >> 6) & 63) | 128, (value & 63) | 128);
  }
  return output;
}

export function arrayBase64(bytes) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let result = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
    result += alphabet[a >> 2];
    result += alphabet[((a & 3) << 4) | ((b ?? 0) >> 4)];
    result += b === undefined ? '=' : alphabet[((b & 15) << 2) | ((c ?? 0) >> 6)];
    result += c === undefined ? '=' : alphabet[c & 63];
  }
  return result;
}

export function fixture() {
  const cases = [
    { name: 'empty-values', input: [], key: '0' },
    { name: 'single-zero', input: [0], key: '0' },
    { name: 'byte-boundaries', input: [0, 1, 2, 126, 127, 128, 254, 255], key: '123' },
    { name: 'all-byte-values', input: Array.from({length: 256}, (_, i) => i), key: '54321' },
    { name: 'non-ascii-key', input: [1, 2, 3, 254], key: '\u00e9\u4f60\ud83d\ude00' },
    { name: 'unpaired-surrogate-key', input: [0, 7, 255], key: '\ud800' },
    { name: 'no-byte-truncation', input: [255], key: '0' },
  ];
  return {
    schema_version: 1,
    provenance: 'independent JS arithmetic reference; synthetic inputs only; not target-runtime equivalence',
    target_code_executed: false,
    real_session_values: false,
    cases: cases.map(item => {
      const units = utf16Units(item.key);
      const mixed = repeatedXor(item.input, units);
      const transformed = stagedOffset(mixed);
      const encoded = numericEncoding(transformed);
      return { ...item, units, mixed, transformed, encoded, base64: arrayBase64(encoded) };
    }),
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.length !== 2 || args[0] !== '--output' || path.extname(args[1]) !== '.json') {
    throw new Error('Usage: node tests/security_codec_reference.mjs --output <new.json>');
  }
  fs.writeFileSync(args[1], JSON.stringify(fixture(), null, 2) + '\n', { flag: 'wx' });
  console.log('Synthetic reference fixture created; no target code or session data used.');
}
