#!/usr/bin/env node
// Passive capture attached to our disposable Chrome DevTools browser.
// It does not navigate, click, submit forms, modify headers, or alter page code.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { parseArgs } from 'node:util';

const { values } = parseArgs({
  options: {
    endpoint: { type: 'string', default: 'http://127.0.0.1:9224' },
    out: { type: 'string' },
    scripts: { type: 'string' },
    seconds: { type: 'string', default: '120' },
  },
});
if (!values.out) throw new Error('--out is required');
const endpoint = new URL(values.endpoint);
if (endpoint.hostname !== '127.0.0.1' || endpoint.protocol !== 'http:') {
  throw new Error('Only an explicitly owned loopback CDP endpoint is accepted');
}
const seconds = Number(values.seconds);
if (!Number.isFinite(seconds) || seconds < 1 || seconds > 600) {
  throw new Error('Capture must be bounded to 1..600 seconds');
}
process.umask(0o077);
const out = path.resolve(values.out);
fs.mkdirSync(out, { recursive: true, mode: 0o700 });
fs.chmodSync(out, 0o700);
if (values.scripts) fs.mkdirSync(values.scripts, { recursive: true });
const targets = await (await fetch(new URL('/json/list', endpoint))).json();
const target = targets.find(t => t.type === 'page');
if (!target?.webSocketDebuggerUrl) throw new Error('No inspectable page target');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});
let sequence = 0;
const pending = new Map();
const records = new Map();
const requestExtras = new Map();
const responseExtras = new Map();
const jobs = new Set();
const frames = [];
const failures = [];
const scripts = [];
let stopping = false;

function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, 8000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
function approved(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && (
      u.hostname === 'zhipin.com' || u.hostname.endsWith('.zhipin.com') ||
      u.hostname === 'bosszhipin.com' || u.hostname.endsWith('.bosszhipin.com')
    );
  } catch { return false; }
}
function saveRecord(id, record) {
  const name = 'request-' + crypto.createHash('sha256').update(id).digest('hex').slice(0, 20) + '.json';
  fs.writeFileSync(path.join(out, name), JSON.stringify(record, null, 2), { mode: 0o600 });
  record.captureFile = name;
}
function attachExtraHeaders(record, extra) {
  record.requestExtraInfo = extra;
  const headers = { ...record.networkRequest.requestHeaders };
  for (const [name, value] of Object.entries(extra.headers || {})) {
    for (const old of Object.keys(headers)) {
      if (old.toLowerCase() === name.toLowerCase()) delete headers[old];
    }
    headers[name] = value;
  }
  record.networkRequest.requestHeaders = headers;
  record.requestHeaderCompleteness = 'CDP extra-info captured; wire order not retained';
}
async function captureBody(id) {
  const record = records.get(id);
  if (!record) return;
  if (!['Script', 'Document', 'Fetch', 'XHR'].includes(record.resourceType)) {
    saveRecord(id, record);
    return;
  }
  try {
    const result = await call('Network.getResponseBody', { requestId: id });
    const body = result.base64Encoded ? Buffer.from(result.body, 'base64') : Buffer.from(result.body);
    record.bodySha256 = crypto.createHash('sha256').update(body).digest('hex');
    record.bodyBytes = body.length;
    if (body.length <= 16 * 1024 * 1024) {
      record.networkRequest.responseBody = result.base64Encoded
        ? { base64: result.body }
        : result.body;
    } else {
      record.bodyError = 'Body exceeded capture limit';
    }
    const u = new URL(record.networkRequest.url);
    if (values.scripts && record.resourceType === 'Script'
        && u.hostname === 'static.zhipin.com' && u.pathname.endsWith('.js')
        && body.length <= 16 * 1024 * 1024 && Number(record.networkRequest.status) === 200) {
      const basename = path.basename(u.pathname).replace(/[^A-Za-z0-9_.-]/g, '_');
      let destination = path.join(values.scripts, basename);
      if (fs.existsSync(destination) && !fs.readFileSync(destination).equals(body)) {
        destination = path.join(values.scripts, record.bodySha256.slice(0, 12) + '-' + basename);
      }
      fs.writeFileSync(destination, body);
      scripts.push({ file: path.basename(destination), url: u.origin + u.pathname,
        sha256: record.bodySha256, bytes: body.length });
    }
  } catch (error) {
    record.bodyError = String(error.message);
  }
  saveRecord(id, record);
}
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const request = pending.get(message.id);
    if (!request) return;
    clearTimeout(request.timer);
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result || {});
    return;
  }
  const p = message.params || {};
  if (message.method === 'Network.requestWillBeSent' && approved(p.request.url)) {
    if (records.has(p.requestId)) {
      const old = records.get(p.requestId);
      if (p.redirectResponse) old.redirectResponse = p.redirectResponse;
      saveRecord(p.requestId + '-redirect-' + p.timestamp, old);
    }
    const record = {
      requestId: p.requestId, resourceType: p.type, initiator: p.initiator,
      timestamp: p.timestamp, wallTime: p.wallTime,
      requestHeaderCompleteness: 'request event only; extra-info not yet observed',
      networkRequest: {
        url: p.request.url, method: p.request.method,
        requestHeaders: p.request.headers, requestBody: p.request.postData ?? null,
        status: null, responseBody: '<Response body not available anymore>',
      },
    };
    records.set(p.requestId, record);
    if (requestExtras.has(p.requestId)) attachExtraHeaders(record, requestExtras.get(p.requestId));
    if (responseExtras.has(p.requestId)) record.responseExtraInfo = responseExtras.get(p.requestId);
  } else if (message.method === 'Network.requestWillBeSentExtraInfo') {
    requestExtras.set(p.requestId, p);
    const record = records.get(p.requestId);
    if (record) attachExtraHeaders(record, p);
  } else if (message.method === 'Network.responseReceivedExtraInfo') {
    responseExtras.set(p.requestId, p);
    const record = records.get(p.requestId);
    if (record) record.responseExtraInfo = p;
  } else if (message.method === 'Network.responseReceived') {
    const record = records.get(p.requestId);
    if (record) {
      record.networkRequest.status = String(p.response.status);
      record.networkRequest.responseHeaders = p.response.headers;
      record.protocol = p.response.protocol;
      record.mimeType = p.response.mimeType;
    }
  } else if (message.method === 'Network.loadingFinished') {
    const job = captureBody(p.requestId);
    jobs.add(job);
    job.finally(() => jobs.delete(job));
  } else if (message.method === 'Network.loadingFailed') {
    const record = records.get(p.requestId);
    if (record) {
      record.failure = p.errorText;
      saveRecord(p.requestId, record);
    }
  } else if (message.method === 'Page.frameNavigated') {
    frames.push({ url: p.frame.url, main: !p.frame.parentId, at: Date.now() });
  }
});
await call('Network.enable', { maxTotalBufferSize: 128 * 1024 * 1024,
  maxResourceBufferSize: 16 * 1024 * 1024 });
await call('Page.enable');
fs.writeFileSync(path.join(out, 'recording.pid'), String(process.pid));
console.log(JSON.stringify({ ready: true, pid: process.pid, duration_seconds: seconds }));

async function finish() {
  if (stopping) return;
  stopping = true;
  clearTimeout(endTimer);
  await Promise.allSettled([...jobs]);
  for (const [id, record] of records) saveRecord(id, record);
  const index = {
    provenance: 'observed-behavior; passive CDP alongside Chrome DevTools MCP',
    recordedAt: new Date().toISOString(), frames, scripts, failures,
    networkRequests: [...records.values()].map(r => ({
      captureFile: r.captureFile, url: r.networkRequest.url,
      method: r.networkRequest.method, status: r.networkRequest.status,
      resourceType: r.resourceType, bodyBytes: r.bodyBytes ?? null,
      requestHeaderCompleteness: r.requestHeaderCompleteness,
      bodySha256: r.bodySha256 ?? null, bodyError: r.bodyError ?? null,
      failure: r.failure ?? null,
    })),
  };
  fs.writeFileSync(path.join(out, 'index.json'), JSON.stringify(index, null, 2));
  socket.close();
  console.log(JSON.stringify({ complete: true, requests: records.size,
    bodies: [...records.values()].filter(r => r.bodySha256).length, scripts: scripts.length }));
  process.exit(0);
}
const endTimer = setTimeout(finish, seconds * 1000);
process.on('SIGTERM', finish);
process.on('SIGINT', finish);
