import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import path from 'node:path';
import { extractContracts } from '../tools/extract_spa_contracts.mjs';

const require = createRequire(process.env.BABEL_MODULE_ROOT
  ? path.join(path.resolve(process.env.BABEL_MODULE_ROOT), 'package.json') : import.meta.url);
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const extract = body => extractContracts(`({42(e,t,r){${body}}})`, {
  parser, traverse, file: 'offline-fixture.js', digest: 'offline-fixture',
});

test('resolves pinned module import and sequence callee', () => {
  const rows = extract('var a=r(86344); (0,a.hc)("/wapi/example/read");');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].method, 'POST');
  assert.equal(rows[0].encoding, 'form_spa');
});
test('does not mistake shadowed parameter for an imported helper', () => {
  const rows = extract('var a=r(86344); function f(a){a.hc("/wapi/example/not-helper")}');
  assert.deepEqual(rows, []);
});
test('does not mistake shadowed block binding for an imported helper', () => {
  const rows = extract('const a=r(86344); {let a={};a.Jt("/wapi/example/not-helper")}');
  assert.deepEqual(rows, []);
});
test('rejects reassigned imported alias', () => {
  const rows = extract('var a=r(86344);a={};a.Jt("/wapi/example/not-helper");');
  assert.deepEqual(rows, []);
});
test('rejects a nested function that shadows the webpack loader', () => {
  const rows = extract('function f(r){var a=r(86344);a.Jt("/wapi/example/not-helper")}');
  assert.deepEqual(rows, []);
});
test('preserves a legitimate imported helper inside a nested closure', () => {
  const rows = extract('var a=r(86344);function f(){return a.Jt("/wapi/example/read")}');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].method, 'GET');
});
test('unknown options do not establish JSON or form encoding', () => {
  const rows = extract('var a=r(86344);a.bE("/wapi/example/read",{},options)');
  assert.equal(rows[0].encoding, 'UNKNOWN_OVERRIDE');
});
test('explicit header overrides remain unresolved', () => {
  const rows = extract('var a=r(86344);a.hc("/wapi/example/read",{headers:h})');
  assert.equal(rows[0].encoding, 'UNKNOWN_OVERRIDE');
});
test('does not interpret a dynamic URL as a complete contract', () => {
  const rows = extract('var a=r(86344);a.Jt("/wapi/example/"+name)');
  assert.deepEqual(rows, []);
});
test('does not resolve arbitrary imports or computed helper names', () => {
  assert.deepEqual(extract('var a=r(12);a.Jt("/wapi/example/read")'), []);
  assert.deepEqual(extract('var a=r(86344);a["Jt"]("/wapi/example/read")'), []);
});
