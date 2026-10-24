'use strict';
// A tiny server-sent-events client for the main process, so the tray and
// the capsule can follow the runtime without a renderer being open.
//
// It also reports when the stream is gone. The runtime exiting is seen
// through the child process; this is the other witness, for a runtime that
// is alive and no longer answering. `onLost` fires once per loss, when the
// stream ends or a connect attempt fails, and again only after the stream
// has been up in between.

const http = require('node:http');

// The runtime sends a comment line every 15 s while the stream is quiet, so
// a stream that has been silent for three of those is not alive.
const IDLE_MS = 45000;

const TICKET_TIMEOUT_MS = 8000;

/**
 * A one-time ticket for `GET /events`, asked for with the token in the
 * header, so the stream's URL carries a random 30-second value and the
 * launch token is never in a URL. Resolves `{ticket}`, or `{legacy: true}`
 * when the runtime does not know the method (an older runtime, which takes
 * the token on the stream itself). Any other failure rejects, and the
 * caller treats it like a stream that did not open.
 */
function requestTicket(connection) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({ method: 'app.events_ticket', params: {} });
    const req = http.request(
      {
        host: '127.0.0.1',
        port: connection.port,
        path: '/rpc',
        method: 'POST',
        timeout: TICKET_TIMEOUT_MS,
        headers: {
          Authorization: `Bearer ${connection.token}`,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
        },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('error', reject);
        res.on('end', () => {
          let body = null;
          try {
            body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          } catch {
            // not JSON: judged by the status below
          }
          if (body && body.error && body.error.code === 'unknown_method') {
            resolve({ legacy: true });
          } else if (res.statusCode === 200 && body && body.result && typeof body.result.ticket === 'string' && body.result.ticket) {
            resolve({ ticket: body.result.ticket });
          } else {
            reject(new Error(`no ticket (HTTP ${res.statusCode})`));
          }
        });
      },
    );
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
    req.end(payload);
  });
}

function connectEvents(connection, handlers, onLost = () => {}, idleMs = IDLE_MS) {
  let req = null;
  let stopped = false;
  let retry = null;
  let idle = null;
  let lostReported = false;

  function watchdog() {
    clearTimeout(idle);
    idle = setTimeout(() => {
      if (req) req.destroy();
      lost();
      again();
    }, idleMs);
  }

  function lost() {
    if (stopped || lostReported) return;
    lostReported = true;
    try {
      onLost();
    } catch {
      // a handler's failure must not end the retry loop
    }
  }

  // A ticket is spent by the stream that shows it, so every connect, the
  // first and each reconnect, asks for its own. The header is the fallback
  // for a runtime that has no ticket method, and only for that.
  async function open() {
    let target;
    try {
      const got = await requestTicket(connection);
      target = got.ticket
        ? { path: `/events?ticket=${encodeURIComponent(got.ticket)}`, headers: { Accept: 'text/event-stream' } }
        : { path: '/events', headers: { Accept: 'text/event-stream', Authorization: `Bearer ${connection.token}` } };
    } catch {
      lost();
      again();
      return;
    }
    if (stopped) return;
    req = http.get(
      {
        host: '127.0.0.1',
        port: connection.port,
        path: target.path,
        headers: target.headers,
      },
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          lost();
          again();
          return;
        }
        lostReported = false;
        watchdog();
        res.setEncoding('utf8');
        let buffer = '';
        res.on('data', (chunk) => {
          watchdog();
          buffer += chunk;
          let split;
          while ((split = buffer.indexOf('\n\n')) !== -1) {
            const block = buffer.slice(0, split);
            buffer = buffer.slice(split + 2);
            let name = 'message';
            let data = '';
            for (const line of block.split('\n')) {
              if (line.startsWith('event: ')) name = line.slice(7);
              else if (line.startsWith('data: ')) data += line.slice(6);
            }
            if (!data) continue;
            try {
              handlers[name]?.(JSON.parse(data));
            } catch {
              // a handler's failure must not end the stream
            }
          }
        });
        res.on('end', () => { lost(); again(); });
        res.on('error', () => { lost(); again(); });
      },
    );
    req.on('error', () => { lost(); again(); });
  }

  function again() {
    if (stopped) return;
    clearTimeout(idle);
    clearTimeout(retry);
    retry = setTimeout(open, 1000);
  }

  open();
  return () => {
    stopped = true;
    clearTimeout(retry);
    clearTimeout(idle);
    if (req) req.destroy();
  };
}

module.exports = { connectEvents, requestTicket };
