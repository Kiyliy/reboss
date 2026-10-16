#!/usr/bin/env node
// Offline AST/CFG inspection of the terminal bootstrap only.
// No target import, eval, Function constructor, VM dispatch, host access or calls.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

export const IDENTITY = {
  filename: 'e5a1794d.original.js',
  sha256: '641c23791eddaceea84d307930bf90a2ccd2d0c93eaa07175426b085d87fa65a',
  public_url: 'https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js',
};
const require = createRequire(import.meta.url);
for (const name of ['@babel/parser', '@babel/traverse']) {
  if (require(`${name}/package.json`).version !== '7.29.0') throw new Error('Pinned Babel 7.29.0 required');
}
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const property = p => p?.isMemberExpression() && !p.node.computed && p.get('property').isIdentifier()
  ? p.node.property.name : null;
const bind = p => p?.isIdentifier() ? p.scope.getBinding(p.node.name) : null;
const nodeId = p => p?.node ? `${p.node.type}@${p.node.start}` : null;

export function prepare(source, { enforceIdentity = true } = {}) {
  if (enforceIdentity && hash(Buffer.from(source)) !== IDENTITY.sha256) throw new Error('Source identity mismatch');
  const ast = parser.parse(source, { sourceType: 'script', errorRecovery: false });
  const loops = [];
  traverse(ast, {
    ForStatement(p) {
      const init = p.get('init');
      if (init.isVariableDeclaration() && init.node.declarations[0]?.init?.type === 'NumericLiteral'
          && init.node.declarations[0].init.value === 217) loops.push(p);
    },
  });
  if (loops.length !== 1) throw new Error('Expected one terminal 217-initialized bootstrap loop');
  const loop = loops[0], first = loop.get('init.declarations.0');
  const stateBinding = bind(first.get('id'));
  if (!stateBinding || loop.node.update !== null) throw new Error('Unexpected control-state binding/update');
  const test = loop.get('test');
  if (!test.isBinaryExpression({ operator: '!==' }) || bind(test.get('left')) !== stateBinding
      || !test.get('right').isUnaryExpression({ operator: 'void' })) throw new Error('Unexpected loop guard');
  const parts = new Map();
  for (const stmt of loop.get('body.body')) {
    if (!stmt.isVariableDeclaration()) continue;
    for (const d of stmt.get('declarations')) {
      const init = d.get('init');
      if (!init.isBinaryExpression({ operator: '&' }) || !init.get('left').isNumericLiteral({ value: 3 })) continue;
      const rhs = init.get('right');
      const shift = bind(rhs) === stateBinding ? 0
        : rhs.isBinaryExpression({ operator: '>>' }) && bind(rhs.get('left')) === stateBinding
          && rhs.get('right').isNumericLiteral() ? rhs.node.right.value : -1;
      if ([0, 2, 4, 6].includes(shift)) parts.set(bind(d.get('id')), { shift, source: d });
    }
  }
  if (new Set([...parts.values()].map(x => x.shift)).size !== 4) throw new Error('Unproved dispatcher bit-slice decomposition');
  const vmBinding = loop.scope.getBinding('l');
  if (!vmBinding?.constant || !vmBinding?.path.isFunctionDeclaration()) throw new Error('No immutable scoped VM function declaration');
  const vm = vmBinding.path;
  let vmEntryParameter;
  for (const st of vm.get('body.body')) {
    if (!st.isTryStatement()) continue;
    const f = st.get('block.body').find(q => q.isForStatement());
    if (!f?.get('init').isVariableDeclaration()) continue;
    const d = f.get('init.declarations.0');
    const i = d.get('init');
    if (i.isMemberExpression() && i.node.computed && i.get('object').isIdentifier({ name: 'arguments' })
        && i.get('property').isNumericLiteral({ value: 0 })) vmEntryParameter = d;
  }
  if (!vmEntryParameter) throw new Error('VM first argument is not a demonstrated initial state');
  const evidence = p => ({
    ...IDENTITY,
    source_sha256: hash(Buffer.from(source)),
    offset: {
      start_utf16: p.node.start, end_utf16: p.node.end,
      start_utf8: Buffer.byteLength(source.slice(0, p.node.start)),
      end_utf8: Buffer.byteLength(source.slice(0, p.node.end)),
      end_exclusive: true,
    },
    original_line: p.node.loc.start.line,
  });
  return { ast, source, loop, stateBinding, parts, vmBinding, vm, vmEntryParameter, evidence };
}

export function forwardingWrapper(fn, ctx) {
  if (!fn?.isFunctionExpression() || fn.node.params.length || fn.node.body.body.length !== 1) return null;
  const ret = fn.get('body.body.0');
  if (!ret.isReturnStatement()) return null;
  const call = ret.get('argument');
  if (!call.isCallExpression() || property(call.get('callee')) !== 'apply'
      || bind(call.get('callee.object')) !== ctx.vmBinding
      || call.node.arguments.length !== 2 || !call.get('arguments.0').isThisExpression()) return null;
  const args = call.get('arguments.1');
  if (!args.isCallExpression() || property(args.get('callee')) !== 'concat') return null;
  const prefix = args.get('callee.object');
  if (!prefix.isArrayExpression() || prefix.node.elements.length !== 1
      || !prefix.get('elements.0').isNumericLiteral()) return null;
  const sliced = args.get('arguments.0');
  if (args.node.arguments.length !== 1 || !sliced?.isCallExpression()
      || property(sliced.get('callee')) !== 'call'
      || property(sliced.get('callee.object')) !== 'slice'
      || property(sliced.get('callee.object.object')) !== 'prototype') return null;
  const array = sliced.get('callee.object.object.object');
  if (!array.isIdentifier({ name: 'Array' }) || bind(array)
      || sliced.node.arguments.length !== 1 || !sliced.get('arguments.0').isIdentifier({ name: 'arguments' })) return null;
  return {
    kind: 'vm_forwarding_wrapper',
    entry: prefix.node.elements[0].value,
    function_source: ctx.evidence(fn),
    entry_literal_source: ctx.evidence(prefix.get('elements.0')),
    forwarding_source: ctx.evidence(call),
    preserves_this: true,
    arguments: 'prepends one literal state number, then Array.prototype.slice.call(arguments)',
    vm_function_source: ctx.evidence(ctx.vm),
    vm_state_initialization_source: ctx.evidence(ctx.vmEntryParameter),
    target_code_executed: false,
  };
}

function stateConstraint(test, ctx) {
  if (!test?.isBinaryExpression({ operator: '===' })) return null;
  const a = test.get('left'), b = test.get('right');
  if (a.isNumericLiteral() && ctx.parts.has(bind(b))) return { binding: bind(b), value: a.node.value };
  if (b.isNumericLiteral() && ctx.parts.has(bind(a))) return { binding: bind(a), value: b.node.value };
  return null;
}
function constrain(input, binding, value, ctx) {
  const result = new Map(input);
  if (!ctx.parts.has(binding) || !Number.isInteger(value) || value < 0 || value > 3) throw new Error('Invalid two-bit constraint');
  if (result.has(binding) && result.get(binding) !== value) return null;
  result.set(binding, value);
  return result;
}
function statesFor(constraints, ctx) {
  const states = [];
  for (let n = 0; n < 256; n++) {
    if ([...constraints].every(([binding, value]) => (3 & (n >> ctx.parts.get(binding).shift)) === value)) states.push(n);
  }
  return states;
}

// Structural reduction only: descend anonymous dispatch IIFEs syntactically,
// select branch labels from bit-slice equalities, retain every effect as AST.
export function collectBlocks(ctx) {
  const blocks = new Map();
  const ignoredReturnPropagators = [];
  const dispatchResults = new Set();
  function add(p, constraints, isReturn = false) {
    for (const state of statesFor(constraints, ctx)) {
      const existing = blocks.get(state);
      if (existing && existing.path.node !== p.node) throw new Error(`Overlapping leaf statements for state ${state}`);
      blocks.set(state, { state, path: p, isReturn, source: ctx.evidence(p) });
    }
  }
  function expression(p, constraints) {
    if (p.isConditionalExpression()) {
      const c = stateConstraint(p.get('test'), ctx);
      if (c) {
        const yes = constrain(constraints, c.binding, c.value, ctx);
        if (yes) expression(p.get('consequent'), yes);
        const alternative = p.get('alternate');
        if (alternative.isConditionalExpression()) expression(alternative, constraints);
        else if (!(alternative.isUnaryExpression({ operator: 'void' }))) throw new Error('Unhandled state-chain alternate');
        return;
      }
    }
    if (p.isUnaryExpression({ operator: 'void' })) return;
    add(p, constraints);
  }
  function statement(p, constraints) {
    if (p.isSwitchStatement()) {
      const b = bind(p.get('discriminant'));
      if (!ctx.parts.has(b)) throw new Error('Nested switch does not use the same scoped state decomposition');
      for (const c of p.get('cases')) {
        if (!c.get('test').isNumericLiteral()) throw new Error('Unexpected default switch case');
        const next = constrain(constraints, b, c.node.test.value, ctx);
        if (next) for (const s of c.get('consequent')) statement(s, next);
      }
    } else if (p.isVariableDeclaration()) {
      for (const d of p.get('declarations')) {
        const init = d.get('init');
        if (!init.isCallExpression() || property(init.get('callee')) !== 'apply') continue;
        const fn = init.get('callee.object');
        if (!fn.isFunctionExpression() || fn.node.id || fn.node.params.length
            || init.node.arguments.length !== 2 || !init.get('arguments.0').isThisExpression()
            || !init.get('arguments.1').isIdentifier({ name: 'arguments' })) throw new Error('Non-structural dispatcher IIFE');
        dispatchResults.add(bind(d.get('id')));
        for (const child of fn.get('body.body')) statement(child, constraints);
      }
    } else if (p.isExpressionStatement()) expression(p.get('expression'), constraints);
    else if (p.isIfStatement()) {
      // These are only compiler-generated propagation of an inner leaf return.
      if (!p.get('test').isIdentifier() || !p.get('consequent').isReturnStatement() || p.node.alternate) {
        throw new Error('Unexpected dispatcher if statement');
      }
      const tested = bind(p.get('test')), returned = p.get('consequent.argument');
      const same = bind(returned) === tested;
      const unbox = returned.isMemberExpression() && returned.node.computed
        && bind(returned.get('object')) === tested && returned.get('property').isNumericLiteral({ value: 0 });
      if (!tested || !dispatchResults.has(tested) || (!same && !unbox)) throw new Error('Unproved return propagation');
      ignoredReturnPropagators.push(ctx.evidence(p));
    } else if (p.isReturnStatement()) add(p, constraints, true);
    else if (!p.isBreakStatement()) throw new Error(`Unsupported dispatcher statement ${p.node.type}`);
  }
  for (const p of ctx.loop.get('body.body')) {
    if (p.isSwitchStatement()) statement(p, new Map());
  }
  return { blocks, ignoredReturnPropagators };
}

export function describeExpr(p, ctx) {
  if (!p?.node) return { kind: 'missing' };
  if (p.isStringLiteral() || p.isNumericLiteral() || p.isBooleanLiteral()) return { kind: 'literal', value: p.node.value };
  if (p.isNullLiteral()) return { kind: 'literal', value: null };
  if (p.isIdentifier()) return { kind: 'binding', name: p.node.name, binding_start: bind(p)?.identifier.start ?? null };
  if (p.isThisExpression()) return { kind: 'this' };
  if (p.isFunctionExpression()) {
    const wrapper = forwardingWrapper(p, ctx);
    return wrapper || {
      kind: 'function', name: p.node.id?.name || null,
      empty_body: p.node.body.body.length === 0, source: ctx.evidence(p),
    };
  }
  if (p.isMemberExpression()) return {
    kind: 'member', object: describeExpr(p.get('object'), ctx),
    property: p.node.computed ? describeExpr(p.get('property'), ctx) : { kind: 'literal', value: p.node.property.name },
  };
  if (p.isAssignmentExpression()) return {
    kind: 'assignment', operator: p.node.operator,
    target: describeExpr(p.get('left'), ctx), value: describeExpr(p.get('right'), ctx),
    source: ctx.evidence(p),
  };
  if (p.isSequenceExpression()) return { kind: 'sequence', expressions: p.get('expressions').map(q => describeExpr(q, ctx)) };
  if (p.isConditionalExpression()) return {
    kind: 'conditional', test: describeExpr(p.get('test'), ctx),
    consequent: describeExpr(p.get('consequent'), ctx), alternate: describeExpr(p.get('alternate'), ctx),
  };
  if (p.isBinaryExpression() || p.isLogicalExpression()) return {
    kind: 'binary', operator: p.node.operator,
    left: describeExpr(p.get('left'), ctx), right: describeExpr(p.get('right'), ctx),
  };
  if (p.isUnaryExpression()) return { kind: 'unary', operator: p.node.operator, argument: describeExpr(p.get('argument'), ctx) };
  if (p.isNewExpression() || p.isCallExpression()) return {
    kind: p.isNewExpression() ? 'new_opaque' : 'call_opaque',
    callee: describeExpr(p.get('callee'), ctx),
    arguments: p.get('arguments').map(q => describeExpr(q, ctx)), source: ctx.evidence(p),
  };
  if (p.isObjectExpression()) return {
    kind: 'object_literal', empty: p.node.properties.length === 0, source: ctx.evidence(p),
  };
  if (p.isArrayExpression()) return { kind: 'array', elements: p.get('elements').map(q => describeExpr(q, ctx)) };
  if (p.isReturnStatement()) return { kind: 'return', value: describeExpr(p.get('argument'), ctx) };
  return { kind: 'UNKNOWN', node_type: p.node.type, source: ctx.evidence(p) };
}

export function analyze(source, options) {
  const ctx = prepare(source, options);
  const { blocks, ignoredReturnPropagators } = collectBlocks(ctx);
  const serialized = [...blocks.values()].sort((a, b) => a.state - b.state).map(b => ({
    state: b.state, source: b.source, is_return: b.isReturn,
    operation: describeExpr(b.path, ctx),
  }));
  const relevantBindings = ['c', 'ql', 'Ql', 'lp', 'pp', '_p', 'ep', 'yp', 'Nl', '_', 'cl', 'op', 'W', 'w', 'q'];
  const lexicalWriteAudit = relevantBindings.map(name => {
    const b = ctx.loop.scope.getBinding(name);
    return {
      name, binding_start: b?.identifier.start ?? null,
      writes_outside_bootstrap: (b?.constantViolations || [])
        .filter(p => p.node.start < ctx.loop.node.start || p.node.end > ctx.loop.node.end)
        .map(ctx.evidence),
    };
  });
  const result = {
    source: IDENTITY,
    provenance: 'source-assisted, static bootstrap branch recovery; not VM execution',
    inherited_rea: {
      evidence_id: 'ev_a41f8954521227ed6bf92d76d6748b0be29f00e7e569291478a1090c0ff196e4',
      version: '6.5.0', parent_reported_ast_nodes: 134062,
      parent_reported_limitation: 'AST parse succeeded; semantic analysis exhausted heap; graph is incomplete.',
      full_record_read: false, rerun: false,
    },
    bootstrap_source: ctx.evidence(ctx.loop),
    state_initialization: ctx.evidence(ctx.loop.get('init.declarations.0')),
    initial_state: 217,
    bit_slices: [...ctx.parts].map(([b, d]) => ({ name: b.identifier.name, shift: d.shift, mask: 3, source: ctx.evidence(d.source) })),
    vm_source: ctx.evidence(ctx.vm),
    vm_initial_state_source: ctx.evidence(ctx.vmEntryParameter),
    leaf_blocks: serialized,
    relevant_binding_lexical_write_audit: lexicalWriteAudit,
    coverage: {
      possible_state_values: 256, populated_state_blocks: serialized.length,
      opaque_calls_executed: 0, vm_states_analyzed: 0,
      structurally_recognized_return_propagators: ignoredReturnPropagators.length,
    },
  };
  result.proof = recoverBindingProof(result);
  return result;
}

function operations(block) {
  return block.operation.kind === 'sequence' ? block.operation.expressions : [block.operation];
}
function setMapEqual(a, b) {
  const keys = new Set([...a.keys(), ...b.keys()]);
  for (const k of keys) {
    const x = a.get(k) || new Set(), y = b.get(k) || new Set();
    if (x.size !== y.size || [...x].some(v => !y.has(v))) return false;
  }
  return true;
}
const cloneFacts = env => new Map([...env].map(([k, s]) => [k, new Set(s)]));
function unionFacts(envs) {
  const result = new Map();
  for (const env of envs) for (const [k, values] of env) {
    const set = result.get(k) || new Set();
    for (const v of values) set.add(v);
    result.set(k, set);
  }
  return result;
}
function short(v) {
  if (!v || typeof v !== 'object') return v;
  if (v.kind === 'vm_forwarding_wrapper') return {
    kind: v.kind, entry: v.entry, function_source: v.function_source, entry_literal_source: v.entry_literal_source,
    preserves_this: true, argument_forwarding: v.arguments,
  };
  const out = {};
  for (const [k, value] of Object.entries(v)) if (k !== 'vm_function_source' && k !== 'vm_state_initialization_source') {
    out[k] = Array.isArray(value) ? value.map(short) : short(value);
  }
  return out;
}

// Standard reaching-definitions on a syntactically reduced CFG. This only
// manipulates AST descriptions; it is not an interpreter for the target's VM.
// Calls, new, getters, global state and property effects remain opaque.
export function recoverBindingProof(result) {
  const byState = new Map(result.leaf_blocks.map(b => [b.state, b]));
  const edges = new Map(), predecessors = new Map(), definitions = new Map();
  const scopeIds = new Map();
  for (const b of result.leaf_blocks) {
    const ops = operations(b);
    ops.forEach((op, i) => {
      if (op.kind === 'assignment' && op.operator === '=' && op.target.kind === 'binding') {
        const id = `${b.state}:${i}`;
        definitions.set(id, { id, state: b.state, order: i, op, before: null });
        scopeIds.set(op.target.name, op.target.binding_start);
      }
    });
    const last = ops.at(-1);
    if (last?.kind !== 'assignment' || last.target.kind !== 'binding'
        || last.target.name !== 'p' || last.operator !== '=') throw new Error('Unsupported CFG terminator');
    const v = last.value;
    let successors;
    if (v.kind === 'literal' && Number.isInteger(v.value)) successors = [v.value];
    else if (v.kind === 'conditional' && v.consequent.kind === 'literal' && v.alternate.kind === 'literal') {
      successors = [v.consequent.value, v.alternate.value];
    } else if (v.kind === 'unary' && v.operator === 'void') successors = [];
    else throw new Error('Dynamic next state remains unresolved');
    edges.set(b.state, successors);
    for (const to of successors) {
      if (!byState.has(to)) throw new Error(`Unmapped reachable successor ${to}`);
      const pred = predecessors.get(to) || [];
      pred.push(b.state); predecessors.set(to, pred);
    }
  }
  const reachable = new Set(), pending = [result.initial_state];
  while (pending.length) {
    const n = pending.pop();
    if (reachable.has(n)) continue;
    reachable.add(n); pending.push(...(edges.get(n) || []));
  }
  const ins = new Map(), outs = new Map();
  for (const n of reachable) { ins.set(n, new Map()); outs.set(n, new Map()); }
  let changed = true, passes = 0;
  while (changed) {
    if (++passes > reachable.size * 4 + 4) throw new Error('Reaching definitions did not converge');
    changed = false;
    for (const n of reachable) {
      const input = unionFacts((predecessors.get(n) || []).filter(p => reachable.has(p)).map(p => outs.get(p)));
      const output = cloneFacts(input);
      operations(byState.get(n)).forEach((op, i) => {
        if (op.kind === 'assignment' && op.target.kind === 'binding') output.set(op.target.binding_start, new Set([`${n}:${i}`]));
      });
      if (!setMapEqual(ins.get(n), input) || !setMapEqual(outs.get(n), output)) changed = true;
      ins.set(n, input); outs.set(n, output);
    }
  }
  for (const n of reachable) {
    const env = cloneFacts(ins.get(n));
    operations(byState.get(n)).forEach((op, i) => {
      const definition = definitions.get(`${n}:${i}`);
      if (definition) { definition.before = cloneFacts(env); env.set(op.target.binding_start, new Set([definition.id])); }
    });
  }
  function expand(expr, env, trail = new Set()) {
    if (!expr || typeof expr !== 'object') return { kind: 'UNKNOWN' };
    if (expr.kind === 'binding') {
      if (expr.binding_start === null) return { kind: 'external_global_identifier', name: expr.name };
      const ids = [...(env.get(expr.binding_start) || [])];
      if (!ids.length) return { kind: 'UNKNOWN', binding: expr.name, reason: 'no_reaching_definition' };
      const values = ids.map(id => {
        if (trail.has(id)) return { kind: 'UNKNOWN', reason: 'cyclic_definition', definition: id };
        const d = definitions.get(id), next = new Set(trail); next.add(id);
        return { definition: id, source: d.op.source, value: expand(d.op.value, d.before, next) };
      });
      return values.length === 1
        ? { kind: 'resolved_binding', name: expr.name, binding_start: expr.binding_start, ...values[0] }
        : { kind: 'PHI', name: expr.name, binding_start: expr.binding_start, alternatives: values };
    }
    if (expr.kind === 'literal') return expr;
    if (expr.kind === 'vm_forwarding_wrapper') return short(expr);
    if (expr.kind === 'unary' && expr.operator === 'void') return { kind: 'undefined_literal' };
    if (expr.kind === 'binary') {
      const left = expand(expr.left, env, trail), right = expand(expr.right, env, trail);
      const unbox = v => v.kind === 'resolved_binding' ? unbox(v.value) : v;
      const a = unbox(left), b = unbox(right);
      if (expr.operator === '+' && a.kind === 'literal' && b.kind === 'literal'
          && ['number', 'string'].includes(typeof a.value) && ['number', 'string'].includes(typeof b.value)) {
        return { kind: 'constant_fold', operator: '+', value: a.value + b.value, operands: [left, right] };
      }
      return { kind: 'symbolic_binary', operator: expr.operator, left, right };
    }
    const out = { kind: expr.kind };
    for (const [k, value] of Object.entries(expr)) {
      if (k === 'kind') continue;
      if (k === 'source') out[k] = value;
      else if (Array.isArray(value)) out[k] = value.map(v => expand(v, env, trail));
      else if (value && typeof value === 'object') out[k] = expand(value, env, trail);
      else out[k] = value;
    }
    return out;
  }
  const propertyWrites = [], opaqueDependencies = [], branchTests = [];
  for (const n of reachable) {
    const env = cloneFacts(ins.get(n));
    operations(byState.get(n)).forEach((op, i) => {
      if (op.kind !== 'assignment') return;
      if (op.target.kind === 'member') propertyWrites.push({
        state: n, source: op.source,
        target: expand(op.target, env),
        value: expand(op.value, env),
        claim: 'syntactic_write_on_normal_completion_only',
      });
      if (op.value.kind === 'call_opaque' || op.value.kind === 'new_opaque') opaqueDependencies.push({
        state: n, assigned_binding: op.target.name, source: op.source,
        expression: expand(op.value, env),
        return_value: 'UNKNOWN', side_effects: 'UNKNOWN', executed: false,
      });
      if (op.target.name === 'p' && op.value.kind === 'conditional') branchTests.push({
        state: n, predicate: expand(op.value.test, env),
        true_successor: op.value.consequent.value, false_successor: op.value.alternate.value,
        source: op.source,
      });
      if (op.target.kind === 'binding') env.set(op.target.binding_start, new Set([`${n}:${i}`]));
    });
  }
  const unwrap = v => v.kind === 'resolved_binding' ? unwrap(v.value) : v;
  const propertyValue = v => {
    v = unwrap(v);
    return v.kind === 'literal' || v.kind === 'constant_fold' ? v.value : undefined;
  };
  const exportWrite = propertyWrites.find(w => propertyValue(w.target.property) === 'ABC');
  const methodWrite = propertyWrites.find(w => propertyValue(w.target.property) === 'z');
  const methodValue = methodWrite && unwrap(methodWrite.value);
  const prototype = methodWrite && unwrap(methodWrite.target.object);
  const ctor = exportWrite && unwrap(exportWrite.value);
  const ctorCallee = ctor?.callee && unwrap(ctor.callee);
  const proved = !!exportWrite && !!methodWrite && methodValue.kind === 'vm_forwarding_wrapper'
    && prototype?.kind === 'member' && propertyValue(prototype.property) === 'prototype'
    && ctor?.kind === 'new_opaque' && ctor.arguments.length === 0
    && ctorCallee.kind === 'external_global_identifier' && ctorCallee.name === 'Function'
    && unwrap(prototype.object)?.source?.offset?.start_utf16 === ctor.source.offset.start_utf16;
  return {
    status: proved ? 'STATIC_BINDING_CHAIN_PROVED_UNDER_EXPLICIT_NORMAL_COMPLETION_ASSUMPTIONS' : 'UNKNOWN',
    method_name: proved ? 'z' : 'UNKNOWN',
    vm_entry_number: proved ? methodValue.entry : 'UNKNOWN',
    entry_is: 'literal first argument used as l() initial dispatcher state; not a recovered algorithm',
    constructor: proved ? {
      expression: 'new (unshadowed global Function)()', argument_count: 0,
      source: ctor.source,
      native_Function_identity: 'UNKNOWN',
      evaluated: false,
    } : 'UNKNOWN',
    export_write: exportWrite || null, prototype_method_write: methodWrite || null,
    branch_tests: branchTests,
    property_writes: propertyWrites,
    opaque_initialization_dependencies: opaqueDependencies,
    cfg: {
      initial_state: result.initial_state, reachable_states: reachable.size, all_leaf_states_reachable: reachable.size === byState.size,
      reaching_definitions_passes: passes,
      edges: [...edges].map(([from, to]) => ({ from, to })),
    },
    conditions: [
      'Static normal-completion CFG only; exceptions can be swallowed by the surrounding catch.',
      'Calls/new are opaque and not executed, including VM entries reached during initialization.',
      'No claim that the global Function, Array.prototype.slice/concat, apply/call or window are unmodified at runtime.',
      'Opaque side effects, proxies/getters, environment-dependent branch outcomes, CSP and runtime reachability remain UNKNOWN.',
      'Reaching definitions preserve direct lexical bindings; opaque effects are not assumed to prove full behavioral equivalence.',
      'The method-entry mapping does not recover the l() body, stoken algorithm, environmental inputs or a valid real token.',
    ],
  };
}

export function compactSummary(result) {
  const proof = result.proof;
  const unbox = value => value?.kind === 'resolved_binding' ? unbox(value.value) : value;
  const method = unbox(proof.prototype_method_write?.value);
  return {
    schema_version: 1,
    source: result.source,
    provenance: result.provenance,
    inherited_rea: result.inherited_rea,
    coverage: result.coverage,
    bootstrap: {
      initial_state: result.initial_state,
      source_range: result.bootstrap_source.offset,
      populated_state_blocks: result.coverage.populated_state_blocks,
      possible_state_values: result.coverage.possible_state_values,
    },
    binding: {
      status: proof.status,
      method_name: proof.method_name,
      entry_state: proof.vm_entry_number,
      interpretation: proof.entry_is,
      method_wrapper_range: method?.function_source?.offset || null,
      entry_literal_range: method?.entry_literal_source?.offset || null,
      prototype_write_range: proof.prototype_method_write?.source?.offset || null,
      export_write_range: proof.export_write?.source?.offset || null,
      constructor: proof.constructor,
      assumptions_and_unknowns: proof.conditions,
    },
    lexical_writes_outside_bootstrap: result.relevant_binding_lexical_write_audit
      .filter(item => item.writes_outside_bootstrap.length).map(item => item.name),
    core_dynamic_validation_solved: false,
    target_code_executed: false,
    token_generated: false,
    server_acceptance_verified: false,
  };
}

function main() {
  const {values} = parseArgs({options: {
    input: {type: 'string'},
    output: {type: 'string'},
    'full-output': {type: 'boolean', default: false},
  }});
  if (!values.input) throw new Error('--input must name an existing local JavaScript file');
  if (fs.statSync(values.input).size > 1024 * 1024) throw new Error('Input exceeds the reviewed size bound');
  if (values.output && (!values.output.endsWith('.json') || fs.existsSync(values.output))) {
    throw new Error('--output requires a new .json path; existing files are never overwritten');
  }
  const bytes = fs.readFileSync(values.input);
  if (hash(bytes) !== IDENTITY.sha256) throw new Error('Input SHA mismatch');
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const result = analyze(source);
  const summary = compactSummary(result);
  if (values.output) {
    fs.writeFileSync(values.output, JSON.stringify(values['full-output'] ? result : summary, null, 2) + '\n',
      {flag: 'wx', mode: 0o600});
  }
  console.log(JSON.stringify(summary, null, 2));
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
