// Independent arithmetic reference for synthetic tests, not target-code execution.
// Formula: SPA v6763 module 94627/r5. Inputs replace Date.now/Math.random.
// Do not use crypto HMAC or Math.imul: those are not this browser implementation.
export function referenceTraceId(nowMs, draws) {
  const alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const data = nowMs.toString(16).padStart(13, '0').slice(-13)
    + draws.map(value => alphabet[Math.floor(value * alphabet.length)]).join('');
  let a = 0, b = 0, c = 0;
  for (let i = 0; i < data.length; i++) a = (((a << 5) - a) + data.charCodeAt(i)) | 0;
  for (let i = data.length - 1; i >= 0; i--) {
    b = (((b << 7) - b) + data.charCodeAt(i) * (i + 1)) | 0;
  }
  const center = Math.floor(data.length / 2);
  for (let i = 0; i < data.length; i++) {
    c = (((c << 3) - c) + data.charCodeAt(i) * (Math.abs(i - center) + 1)) | 0;
  }
  const mix = (value, first, second) => {
    let n = (first * Math.abs(value)) >>> 0;
    n = (n ^ (n >>> 16)) >>> 0;
    n = (second * n) >>> 0;
    return alphabet[((n ^ (n >>> 13)) >>> 0) % alphabet.length];
  };
  return 'F-' + data + mix(a ^ b, 0x9e3779b1, 0x85ebca6b)
    + mix(b ^ c, 0xc2b2ae35, 0x9e3779b1) + mix(c ^ a, 0x27d4eb2d, 0x85ebca6b);
}

export function fixtures() {
  const rows = [
    [0, [0, 0, 0, 0, 0, 0]],
    [1, [0.9999999999999999, 0.5, 0.25, 0.75, 0, 1 / 62]],
    [0x10000000000000, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]],
    [Number.MAX_SAFE_INTEGER, [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]],
  ];
  for (let i = 0; i < 128; i++) {
    rows.push([
      1700000000000 + i * 100003,
      Array.from({length: 6}, (_, j) => ((i * 37 + j * 23) % 997) / 997),
    ]);
  }
  return rows.map(([now_ms, random_values]) => ({
    now_ms, random_values, expected: referenceTraceId(now_ms, random_values),
  }));
}
