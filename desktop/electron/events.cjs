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

  function open() {
    req = http.get(
      {
        host: '127.0.0.1',
        port: connection.port,
        path: '/events',
        headers: { Accept: 'text/event-stream', Authorization: `Bearer ${connection.token}` },
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

module.exports = { connectEvents };
