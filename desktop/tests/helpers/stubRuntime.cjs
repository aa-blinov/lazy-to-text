'use strict';
// A stand-in for `python -m app.server`, in Node, for the shell tests. It
// speaks the part of the protocol the main process uses: one ready line on
// stdout, GET /health, GET /events (an event stream with a heartbeat) and
// POST /rpc app.snapshot. STUB_MODE picks a behaviour.

const http = require('node:http');

const mode = process.env.STUB_MODE || 'ok';

if (mode === 'exit1') {
  console.error('Traceback (most recent call last):');
  console.error('ImportError: no module named nothing');
  process.exit(1);
}
if (mode === 'already') {
  console.log(JSON.stringify({ ready: false, error: 'already_running' }));
  process.exit(3);
}
if (mode === 'never') {
  console.log('some library printed this');
  console.log(JSON.stringify({ progress: 1 }));
  setInterval(() => {}, 1000);
  return;
}

const slow = mode === 'slowok';
const token = 'stubtoken';
const streams = new Set();
const server = http.createServer((req, res) => {
  // The window is a page on its own origin; the real runtime answers it with CORS headers.
  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }
  // The runtime takes the token in the header, and on /events in the query too (EventSource cannot send headers).
  const auth = req.headers.authorization === `Bearer ${token}`
    || (req.url.startsWith('/events') && req.url.includes(`token=${token}`))
    || (req.url.startsWith('/events') && req.url.includes('ticket='));
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
    return;
  }
  if (!auth) {
    res.writeHead(401);
    res.end();
    return;
  }
  if (req.url.split('?')[0] === '/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.write(': open\n\n');
    streams.add(res);
    req.on('close', () => streams.delete(res));
    if (mode === 'ok') {
      res.write(`event: state\ndata: ${JSON.stringify({ state: 'recording' })}\n\n`);
    }
    if (mode === 'delivery') {
      // A finished dictation: the text went to the clipboard.
      const text = process.env.STUB_DELIVERY_TEXT || 'a short sentence';
      res.write(`event: state\ndata: ${JSON.stringify({ state: 'idle' })}\n\n`);
      res.write(`event: delivery\ndata: ${JSON.stringify({ outcome: 'copied', detail: 'Cmd+V', text })}\n\n`);
    }
    return;
  }
  if (req.url === '/rpc') {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ result: { pid: process.pid, version: 'stub', log_path: '/stub/app.log', config: { ui: { language: process.env.STUB_LANGUAGE || 'ru' } } } }));
    });
    return;
  }
  res.writeHead(404);
  res.end();
});

if (mode === 'delivery') {
  // Repeat the delivery so a window that connects late still sees one.
  setInterval(() => {
    const text = process.env.STUB_DELIVERY_TEXT || 'a short sentence';
    for (const res of streams) {
      res.write(`event: delivery\ndata: ${JSON.stringify({ outcome: 'copied', detail: 'Cmd+V', text })}\n\n`);
    }
  }, 4000);
}

server.listen(0, '127.0.0.1', () => {
  const ready = () => console.log(JSON.stringify({ ready: true, port: server.address().port, token, pid: process.pid }));
  // A slow cold start: nothing for a while, then the ready line.
  if (slow) setTimeout(ready, 1200); else ready();
});

// The runtime exits when its parent closes its stdin.
process.stdin.resume();
process.stdin.on('end', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
