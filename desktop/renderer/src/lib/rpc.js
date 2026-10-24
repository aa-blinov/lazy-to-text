// The renderer's only door to the Python runtime: `call` for requests,
// `subscribe` for the event stream. Inside Electron the preload hands over
// the loopback port and token; in a plain browser tab (development) they
// come from the page URL: ?port=18765&token=devtoken.

let connection = null;

export class RpcError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

export async function connect() {
  if (connection) return connection;
  if (typeof window !== 'undefined' && window.l2t?.connection) {
    connection = await window.l2t.connection();
  } else {
    const q = new URLSearchParams(globalThis.location?.search ?? '');
    const port = q.get('port');
    const token = q.get('token');
    if (!port || !token) throw new RpcError('no_connection', 'No backend connection');
    connection = { port: Number(port), token };
  }
  return connection;
}

/** Test hook: use a fixed connection or a fake fetch. */
export function _setConnection(next) {
  connection = next;
}

export async function call(method, params = {}) {
  const { port, token } = await connect();
  const response = await fetch(`http://127.0.0.1:${port}/rpc`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, params }),
  });
  if (!response.ok) throw new RpcError('http_' + response.status, response.statusText);
  const body = await response.json();
  if (body.error) throw new RpcError(body.error.code, body.error.message);
  return body.result;
}

const listeners = new Map();
let source = null;

function ensureSource(conn) {
  if (source) return;
  source = new EventSource(`http://127.0.0.1:${conn.port}/events?token=${conn.token}`);
  source.onerror = () => {
    // EventSource reconnects by itself; a closed stream (the backend is
    // gone) is reported once so the shell can say so.
    if (source.readyState === EventSource.CLOSED) {
      source = null;
      for (const cb of listeners.get('__disconnected') ?? []) cb({});
    }
  };
  for (const name of listeners.keys()) attach(name);
}

const attached = new Set();
function attach(name) {
  if (!source || attached.has(name) || name.startsWith('__')) return;
  attached.add(name);
  source.addEventListener(name, (ev) => {
    let data = null;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    for (const cb of listeners.get(name) ?? []) cb(data);
  });
}

/** Subscribe to a server event. Returns the unsubscribe function. */
export function subscribe(name, cb) {
  if (!listeners.has(name)) listeners.set(name, new Set());
  listeners.get(name).add(cb);
  connect().then((conn) => {
    ensureSource(conn);
    attach(name);
  });
  return () => listeners.get(name)?.delete(cb);
}
