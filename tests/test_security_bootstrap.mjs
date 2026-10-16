import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import { prepare, collectBlocks, forwardingWrapper, analyze, compactSummary, IDENTITY } from '../tools/analyze_security_bootstrap.mjs';

const vm = `function l(){try{for(var p=arguments[0];p!==void 0;){p=void 0}}catch(e){}}`;
function fixture(body = 'p=28', extra = '') {
  return `(function(){${vm}${extra}try{for(var p=217,c,ql,Ql,lp,pp,_p,ep,root;
    p!==void 0;){var rp=3&p,np=3&(p>>2),ip=3&(p>>4),sp=3&(p>>6);
    switch(rp){
      case 1:switch(np){case 2:switch(ip){case 1:3===sp?(${body}):void 0;break}break}break;
      case 0:switch(np){case 3:switch(ip){case 1:0===sp?(p=void 0):void 0;break}break}break;
    }}}catch(e){}})();`;
}
const wrapper = (entry = '6375') => `function p(){return l.apply(this,[${entry}].concat(Array.prototype.slice.call(arguments)))}`;
const chain = `c=Function,ql=${wrapper()},Ql=new c(),lp="proto"+"type",pp=Ql[lp],ep="ABC",_p="z",root=window,root[ep]=Ql,pp[_p]=ql,p=28`;
const inspect = source => analyze(source, { enforceIdentity: false });
function findWrapper(ctx) {
  const { blocks } = collectBlocks(ctx);
  const seq = blocks.get(217).path;
  return seq.get('expressions').find(p => p.isAssignmentExpression() && p.get('right').isFunctionExpression()).get('right');
}

test('input SHA pin rejects changed bytes before analysis', () => {
  assert.throws(() => prepare('throw new Error("do not execute")'), /identity mismatch/);
});
test('two-bit branch reduction recovers the correct literal states', () => {
  const ctx = prepare(fixture(), { enforceIdentity: false });
  assert.deepEqual([...collectBlocks(ctx).blocks.keys()].sort((a,b) => a-b), [28,217]);
});
test('non-default initial state does not select an unrelated loop', () => {
  assert.throws(() => prepare(fixture().replace('p=217','p=216'), { enforceIdentity: false }), /one terminal/);
});
test('changed mask fails the reviewed state decomposition', () => {
  assert.throws(() => prepare(fixture().replace('rp=3&p','rp=7&p'), { enforceIdentity: false }), /decomposition/);
});
test('explicit same-scope wrapper preserves this and prepends the entry', () => {
  const ctx = prepare(fixture(`ql=${wrapper()},p=28`), { enforceIdentity: false });
  const fact = forwardingWrapper(findWrapper(ctx), ctx);
  assert.equal(fact.entry, 6375); assert.equal(fact.preserves_this, true);
});
test('a same-named inner function is not the outer dispatcher binding', () => {
  const ctx = prepare(fixture(`ql=${wrapper().replace('function p','function l')},p=28`), { enforceIdentity: false });
  assert.equal(forwardingWrapper(findWrapper(ctx), ctx), null);
});
test('shadowed Array rejects the standard forwarding profile', () => {
  const ctx = prepare(fixture(`ql=${wrapper()},p=28`, 'var Array=other;'), { enforceIdentity: false });
  assert.equal(forwardingWrapper(findWrapper(ctx), ctx), null);
});
test('nonliteral VM entry remains unknown', () => {
  const ctx = prepare(fixture(`ql=${wrapper('entry')},p=28`), { enforceIdentity: false });
  assert.equal(forwardingWrapper(findWrapper(ctx), ctx), null);
});
test('changed this binding is not accepted as the same forwarding wrapper', () => {
  const ctx = prepare(fixture(`ql=${wrapper().replace('.apply(this,','.apply(null,')},p=28`), { enforceIdentity: false });
  assert.equal(forwardingWrapper(findWrapper(ctx), ctx), null);
});
test('changed arguments source is not accepted as full argument forwarding', () => {
  const ctx = prepare(fixture(`ql=${wrapper().replace('.call(arguments)','.call(other)')},p=28`), { enforceIdentity: false });
  assert.equal(forwardingWrapper(findWrapper(ctx), ctx), null);
});
test('reassigned l is not treated as immutable dispatch code', () => {
  assert.throws(() => prepare(fixture(`ql=${wrapper()},p=28`, 'l=other;'), { enforceIdentity: false }), /immutable scoped/);
});
test('synthetic constructor, prototype and method chain is statically recovered', () => {
  const r = inspect(fixture(chain));
  assert.match(r.proof.status, /^STATIC_BINDING_CHAIN_PROVED/);
  assert.equal(r.proof.vm_entry_number, 6375);
  assert.equal(r.proof.constructor.argument_count, 0);
  assert.equal(r.proof.constructor.native_Function_identity, 'UNKNOWN');
  assert.equal(r.proof.constructor.evaluated, false);
});
test('changed constructor binding invalidates the demonstrated constructor chain', () => {
  const r = inspect(fixture(chain.replace('Ql=new c()', 'c=Other,Ql=new c()')));
  assert.equal(r.proof.status, 'UNKNOWN');
});
test('changed z key is not recovered from an earlier literal or an endpoint name', () => {
  const r = inspect(fixture(chain.replace('pp[_p]=ql', '_p="other",pp[_p]=ql')));
  assert.equal(r.proof.status, 'UNKNOWN');
});
test('different function allocation for prototype is not aliased to exported ABC', () => {
  const r = inspect(fixture(chain.replace('pp=Ql[lp]', 'pp=(new c())[lp]')));
  assert.equal(r.proof.status, 'UNKNOWN');
});
test('target globals, constructor, calls and VM body are never executed', () => {
  globalThis.__dynamicBootstrapProbe = 0;
  const s = `globalThis.__dynamicBootstrapProbe=99;${fixture(chain, 'throw new Error("never run");')}`;
  const r = inspect(s);
  assert.equal(globalThis.__dynamicBootstrapProbe, 0);
  assert.equal(r.coverage.opaque_calls_executed, 0);
  assert.equal(r.coverage.vm_states_analyzed, 0);
  delete globalThis.__dynamicBootstrapProbe;
});
test('Function can be a modified external global; native identity is not asserted', () => {
  const r = inspect(fixture(chain));
  assert.ok(r.proof.conditions.some(x => x.includes('global Function')));
});
test('entry number is never relabelled as a recovered stoken algorithm', () => {
  const r = inspect(fixture(chain));
  assert.match(r.proof.entry_is, /not a recovered algorithm/);
  assert.ok(r.proof.conditions.some(x => x.includes('valid real token')));
});
test('compact results do not claim a solved algorithm or include complete target code', () => {
  const result = compactSummary(inspect(fixture(chain)));
  assert.equal(result.binding.entry_state, 6375);
  assert.equal(result.core_dynamic_validation_solved, false);
  assert.equal(result.server_acceptance_verified, false);
  assert.equal(result.token_generated, false);
  assert.equal(result.target_code_executed, false);
  assert.equal(result.leaf_blocks, undefined);
});

test('original artifact ranges and inherited REA limitation are retained', {
  skip: process.env.BOSS_DYNAMIC_SCRIPT ? false : 'Optional: set BOSS_DYNAMIC_SCRIPT to an independently acquired matching artifact',
}, () => {
  const bytes = fs.readFileSync(process.env.BOSS_DYNAMIC_SCRIPT);
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), IDENTITY.sha256);
  const out = analyze(bytes.toString('utf8'));
  assert.equal(out.proof.vm_entry_number, 6375);
  assert.equal(out.coverage.populated_state_blocks, 118);
  assert.equal(out.coverage.vm_states_analyzed, 0);
  assert.equal(out.inherited_rea.full_record_read, false);
  assert.equal(out.inherited_rea.rerun, false);
  assert.match(out.inherited_rea.parent_reported_limitation, /incomplete/);
  assert.ok(out.relevant_binding_lexical_write_audit.every(x => !x.writes_outside_bootstrap.length));
  const range = out.proof.prototype_method_write.source.offset;
  assert.equal(bytes.subarray(range.start_utf8, range.end_utf8).toString(), 'pp[_p]=ql');
});
