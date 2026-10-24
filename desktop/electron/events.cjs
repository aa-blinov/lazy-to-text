'use strict';
// A tiny server-sent-events client for the main process, so the tray and
// the capsule can follow the runtime without a renderer being open.

const http = require('node:http');

function connectEvents(connection, handlers) {
  let req = null;
  let stopped = false;
  let retry = null;

  function open() {
    req = http.get(
      {
        host: '127.0.0.1',
        port: connection.port,
        path: `/events?token=${encodeURIComponent(connection.token)}`,
        headers: { Accept: 'text/event-stream' },
      },
      (res) => {
        res.setEncoding('utf8');
        let buffer = '';
        res.on('data', (chunk) => {
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
        res.on('end', again);
      },
    );
    req.on('error', again);
  }

  function again() {
    if (stopped) return;
    clearTimeout(retry);
    retry = setTimeout(open, 1000);
  }

  open();
  return () => {
    stopped = true;
    clearTimeout(retry);
    if (req) req.destroy();
  };
}

module.exports = { connectEvents };
