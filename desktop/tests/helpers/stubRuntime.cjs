'use strict';
// A stand-in for `python -m app.server`, in Node, for the shell tests. It
// speaks the part of the protocol the main process uses: one ready line on
// stdout, GET /health, GET /events (an event stream with a heartbeat) and
// POST /rpc app.snapshot and app.events_ticket. STUB_MODE picks a behaviour.
//
// /events is like the real one: a request carries the token in the header
// or a one-time ticket in the query. STUB_TICKETS=legacy makes the ticket
// method unknown (an older runtime); STUB_TICKETS=strict refuses a token in
// the query. GET /__stub counts what arrived, for the tests.

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
const ticketMode = process.env.STUB_TICKETS || 'on';
const issued = new Set();
const seen = { tickets_issued: 0, streams_by_ticket: 0, streams_by_header: 0, streams_by_query_token: 0, refused: 0 };
let ticketCount = 0;
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
  const isEvents = req.url.split('?')[0] === '/events';
  const query = new URLSearchParams(req.url.includes('?') ? req.url.slice(req.url.indexOf('?') + 1) : '');
  let how = null;
  if (req.headers.authorization === `Bearer ${token}`) how = 'header';
  else if (isEvents && query.get('ticket') && issued.delete(query.get('ticket'))) how = 'ticket';
  else if (isEvents && ticketMode !== 'strict' && query.get('token') === token) how = 'query';
  const auth = how !== null;
  if (req.url === '/__stub') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(seen));
    return;
  }
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
    return;
  }
  if (!auth) {
    if (isEvents) seen.refused += 1;
    res.writeHead(401);
    res.end();
    return;
  }
  if (isEvents) {
    seen[{ ticket: 'streams_by_ticket', header: 'streams_by_header', query: 'streams_by_query_token' }[how]] += 1;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.write(': open\n\n');
    streams.add(res);
    req.on('close', () => streams.delete(res));
    if (mode === 'login') {
      // The user flips Start when I log in: the setting changes, then the event says so.
      setTimeout(() => {
        loginValue = !loginValue;
        res.write(`event: settings\ndata: ${JSON.stringify({ keys: ['ui.start_at_login'] })}\n\n`);
      }, 400);
    }
    if (mode === 'ok' || mode === 'login') {
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
      let method = '';
      try { method = JSON.parse(Buffer.concat(chunks).toString('utf8')).method; } catch { /* not JSON */ }
      if (method === 'app.events_ticket') {
        if (ticketMode === 'legacy') {
          res.end(JSON.stringify({ error: { code: 'unknown_method', message: 'unknown method' } }));
          return;
        }
        ticketCount += 1;
        const ticket = `stub-ticket-${ticketCount}`;
        issued.add(ticket);
        seen.tickets_issued += 1;
        res.end(JSON.stringify({ result: { ticket, ttl_s: 30 } }));
        return;
      }
      res.end(JSON.stringify({ result: { pid: process.pid, version: 'stub', log_path: '/stub/app.log', config: { ui: { language: process.env.STUB_LANGUAGE || 'ru', start_at_login: loginValue } } } }));
    });
    return;
  }
  res.writeHead(404);
  res.end();
});

let loginValue = process.env.STUB_LOGIN === '1';

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
