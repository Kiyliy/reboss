#!/usr/bin/env node
// Inert, scope-aware AST extraction for the reviewed v6763 module-86344 helper.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const methods = {
  Jt: ['GET', 'query'], ZV: ['GET', 'query'],
  hc: ['POST', 'form_spa'], bE: ['POST', 'json'], pD: ['POST', 'json'],
};
export const HELPER_DIGEST = '92814a7eae376741b6cef3bf732066abb7f979e61c0a9a37ad5033a78d8dc437';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

export function extractContracts(source, { parser, traverse, file, digest }) {
  const ast = parser.parse(source, { sourceType: 'unambiguous' });
  const contracts = [];
  traverse(ast, {
    CallExpression(call) {
      let callee = call.get('callee');
      if (callee.isSequenceExpression()) callee = callee.get('expressions').at(-1);
      if (!callee.isMemberExpression() || callee.node.computed) return;
      const object = callee.get('object');
      const helper = callee.node.property.name;
      if (!object.isIdentifier() || !methods[helper]) return;
      const binding = object.scope.getBinding(object.node.name);
      if (!binding?.constant || !binding.path.isVariableDeclarator()) return;
      const init = binding.path.get('init');
      if (!init.isCallExpression() || !init.get('callee').isIdentifier()
          || init.node.arguments.length !== 1 || init.node.arguments[0].value !== 86344) return;
      const loader = init.get('callee');
      const loaderBinding = loader.scope.getBinding(loader.node.name);
      if (!loaderBinding?.constant || loaderBinding.kind !== 'param') return;
      const factory = loaderBinding.scope.path;
      if (!factory.isObjectMethod() || factory.node.params.length < 3
          || factory.node.params[2] !== loaderBinding.identifier) return;
      const moduleId = String(factory.node.key.value ?? factory.node.key.name ?? '');
      if (!/^\d+$/.test(moduleId)) return;
      const arg = call.node.arguments[0];
      if (arg?.type !== 'StringLiteral' || !arg.value.startsWith('/wapi/')) return;
      const pathname = arg.value.split(/[?#]/, 1)[0];
      if (!/^\/wapi\/[A-Za-z0-9_./-]+$/.test(pathname) || pathname.includes('..')) return;
      let [method, encoding] = methods[helper];
      const options = call.node.arguments[helper === 'hc' || helper === 'pD' ? 1 : 2];
      // Options supplied indirectly could replace method, headers or transforms.
      // Do not infer a body codec from an unseen value.
      if (options && options.type !== 'ObjectExpression') encoding = 'UNKNOWN_OVERRIDE';
      if (options?.type === 'ObjectExpression') {
        for (const property of options.properties) {
          const key = property.key?.value ?? property.key?.name;
          if (property.type === 'SpreadElement' || property.computed
              || ['headers', 'transformRequest', 'method', 'data'].includes(key)) {
            encoding = 'UNKNOWN_OVERRIDE';
          }
        }
      }
      contracts.push({
        path: pathname, method, encoding, helper, relative_file: file,
        sha256: digest, module_id: moduleId, helper_module_id: 86344,
        helper_source_sha256: HELPER_DIGEST,
        start_utf16: arg.start, end_utf16: arg.end,
        source_line: arg.loc.start.line, raw_source_not_included: true,
        caveat: helper === 'bE' || helper === 'pD'
          ? 'Default JSON; FormData or request overrides require endpoint-specific capture' : null,
      });
    },
  });
  return contracts;
}

function main() {
  const { values } = parseArgs({ options: {
    scripts: { type: 'string' }, output: { type: 'string' },
    'module-root': { type: 'string' },
  } });
  if (!values.scripts || !values.output) throw new Error('--scripts and --output required');
  const require = createRequire(values['module-root']
    ? path.join(path.resolve(values['module-root']), 'package.json') : import.meta.url);
  const parser = require('@babel/parser');
  const traverse = require('@babel/traverse').default;
  if (require('@babel/parser/package.json').version !== '7.29.0'
      || require('@babel/traverse/package.json').version !== '7.29.0') {
    throw new Error('Use the pinned Babel 7.29.0 dependencies');
  }
  const helperFile = path.join(values.scripts, 'app_2.4f650b7a.js');
  if (sha(fs.readFileSync(helperFile)) !== HELPER_DIGEST) {
    throw new Error('Helper mapping is pinned to the reviewed v6763 source digest');
  }
  const files = fs.readdirSync(values.scripts).filter(name =>
    /^(app_\d\.|job_\d\.)/.test(name) && name.endsWith('.js'));
  const contracts = [];
  for (const file of files) {
    const bytes = fs.readFileSync(path.join(values.scripts, file));
    contracts.push(...extractContracts(bytes.toString('utf8'), {
      parser, traverse, file, digest: sha(bytes),
    }));
  }
  fs.mkdirSync(path.dirname(values.output), { recursive: true });
  fs.writeFileSync(values.output, JSON.stringify({
    parser: '@babel/parser@7.29.0', binding_analysis: '@babel/traverse@7.29.0',
    provenance: 'source-assisted AST; no JS execution',
    helper_profile: 'geek_spa_v6763_module_86344', contracts,
  }, null, 2) + '\n');
  console.log(JSON.stringify({ ast_contracts: contracts.length, files: files.length }));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
