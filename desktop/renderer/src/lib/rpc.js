// The renderer's only door to the Python runtime: `call` for requests,
// `subscribe` for the event stream. Inside Electron the preload hands over
// the loopback port and token; in a plain browser tab (development) they
// come from the page URL: ?port=18765&token=devtoken.
//
// The link has two states. While the event stream is open it is `up`. When
// the stream errors and the runtime does not answer /health, or the main
// process says the runtime exited, it is `down`: the pseudo-events
// `__disconnected` and `__connected` tell the shell, and a timer keeps
// asking for the runtime until it is back. A stream that merely blinked and
// reopened also raises `__connected`, because the events sent in the gap are
// gone and the screens have to read their data again.

import { translateRuntime } from './i18n.js';

let connection = null;

export class RpcError extends Error {
  constructor(code, message, field = '') {
    super(message || code);
    this.code = code;
    // The input a refusal is about, when the runtime names one.
    this.field = field;
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

const RECOVER_MS = 2000;
const PROBE_MS = 1500;
const CHECK_DELAY_MS = 1000;

let link = 'up';
let checkTimer = null;
let recoverTimer = null;
let recovering = null;
let hadError = false;

export function linkState() {
  return link;
}

function emitLocal(name, data = {}) {
  for (const cb of listeners.get(name) ?? []) cb(data);
}

/** Is the runtime answering? /health takes no token and costs nothing. */
async function probe() {
  if (!connection) return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_MS);
  try {
    const response = await fetch(`http://127.0.0.1:${connection.port}/health`, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function checkSoon() {
  if (checkTimer || link === 'down') return;
  checkTimer = setTimeout(async () => {
    checkTimer = null;
    if (!(await probe())) markDown('unreachable');
  }, CHECK_DELAY_MS);
}

/** The runtime is gone: say so once, drop the stream and start looking for it. */
export function markDown(reason = 'unreachable') {
  if (link === 'down') return;
  link = 'down';
  clearTimeout(checkTimer);
  checkTimer = null;
  closeSource();
  emitLocal('__disconnected', { reason });
  clearInterval(recoverTimer);
  recoverTimer = setInterval(() => {
    reconnect().catch(() => {});
  }, RECOVER_MS);
}

/**
 * Ask for the connection again (a restarted runtime has a new port and
 * token), and when it answers, reopen the stream and announce it. Safe to
 * call at any time; concurrent calls share one attempt.
 */
export function reconnect() {
  if (recovering) return recovering;
  recovering = (async () => {
    connection = null;
    try {
      await connect();
    } catch {
      return false;
    }
    if (!(await probe())) return false;
    const wasDown = link === 'down';
    link = 'up';
    hadError = false;
    clearInterval(recoverTimer);
    recoverTimer = null;
    closeSource();
    await openStream();
    emitLocal('__connected', { after: wasDown ? 'down' : 'restart' });
    return true;
  })().finally(() => {
    recovering = null;
  });
  return recovering;
}

export async function call(method, params = {}) {
  const { port, token } = await connect();
  let response;
  try {
    response = await fetch(`http://127.0.0.1:${port}/rpc`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ method, params }),
    });
  } catch {
    // The browser's own wording ("Failed to fetch") says nothing to a user.
    checkSoon();
    throw new RpcError('unreachable', 'The engine is not responding.');
  }
  if (!response.ok) throw new RpcError('http_' + response.status, response.statusText);
  const body = await response.json();
  if (body.error) {
    // The runtime writes English; every screen shows err.message as it is.
    throw new RpcError(body.error.code, translateRuntime(body.error.message), body.error.field || '');
  }
  return body.result;
}

const listeners = new Map();
let source = null;
let opening = null;
const attached = new Set();

function closeSource() {
  if (source) {
    source.onerror = null;
    source.onopen = null;
    source.close();
  }
  source = null;
  attached.clear();
}

/**
 * Open the event stream. The runtime hands out a one-time ticket for the URL,
 * so the launch token never sits in a query string; an older runtime without
 * `app.events_ticket` still takes the token. A ticket is spent by the first
 * stream that shows it, which is why a stream is never left to the browser's
 * own reconnecting: a new one is opened here, with a new ticket.
 */
function openStream() {
  if (source || typeof EventSource === 'undefined') return Promise.resolve();
  if (opening) return opening;
  opening = (async () => {
    const conn = connection ?? (await connect());
    let query = `token=${encodeURIComponent(conn.token)}`;
    try {
      const { ticket } = await call('app.events_ticket');
      if (ticket) query = `ticket=${encodeURIComponent(ticket)}`;
    } catch {
      // No ticket method, or the runtime is not answering: the open below says which.
    }
    if (source) return;
    const mine = new EventSource(`http://127.0.0.1:${conn.port}/events?${query}`);
    source = mine;
    mine.onopen = () => {
      if (!hadError) return;
      hadError = false;
      emitLocal('__connected', { after: 'blink' });
    };
    mine.onerror = () => {
      hadError = true;
      if (mine.readyState === EventSource.CLOSED) settleClosed(mine);
      else checkSoon();
    };
    for (const name of listeners.keys()) attach(name);
  })().finally(() => {
    opening = null;
  });
  return opening;
}

/**
 * A closed stream is final. If the runtime still answers, the stream was
 * only lost (a spent ticket, a sleep): open another and tell the screens to
 * read again. If it does not answer, the runtime is gone.
 */
async function settleClosed(mine) {
  if (source !== mine || link === 'down') return;
  if (!(await probe())) {
    markDown('closed');
    return;
  }
  if (source !== mine) return;
  closeSource();
  hadError = false;
  await openStream();
  emitLocal('__connected', { after: 'blink' });
}

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
  connect()
    .then(() => {
      if (link === 'down') return undefined;
      attach(name);
      return openStream();
    })
    .catch(() => {});
  return () => listeners.get(name)?.delete(cb);
}

/** Test hook: forget the stream and the link state. */
export function _resetLink() {
  closeSource();
  clearTimeout(checkTimer);
  clearInterval(recoverTimer);
  checkTimer = null;
  recoverTimer = null;
  recovering = null;
  opening = null;
  link = 'up';
  hadError = false;
  listeners.clear();
}
