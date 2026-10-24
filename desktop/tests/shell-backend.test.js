// The part of the main process that keeps the runtime alive and notices when
// it is not: real child processes against a stand-in that speaks the
// runtime's protocol (tests/helpers/stubRuntime.cjs), no Electron.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const { Backend, StartError } = require('../electron/backend.cjs');
const { connectEvents } = require('../electron/events.cjs');

const stub = join(import.meta.dirname, 'helpers', 'stubRuntime.cjs');
const usable = !/\s/.test(process.execPath) && !/\s/.test(stub);
const app = { isPackaged: false };
const made = [];

function backend(mode, extra = {}) {
  process.env.L2T_BACKEND_CMD = `${process.execPath} ${stub}`;
  process.env.STUB_MODE = mode;
  Object.assign(process.env, extra);
  const b = new Backend(app);
  made.push(b);
  return b;
}

afterEach(async () => {
  while (made.length) await made.pop().kill();
  delete process.env.L2T_BACKEND_CMD;
  delete process.env.STUB_MODE;
  delete process.env.STUB_LANGUAGE;
  delete process.env.STUB_TICKETS;
});

const until = async (predicate, ms = 5000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 20));
  }
  return predicate();
};

describe.skipIf(!usable)('the runtime child process', () => {
  it('starts, answers health and the snapshot, and stops when asked', async () => {
    const b = backend('ok');
    const connection = await b.start();
    expect(connection.port).toBeGreaterThan(0);
    expect(connection.token).toBe('stubtoken');
    expect(await b.healthy()).toBe(true);
    const snapshot = await b.snapshot();
    expect(snapshot.log_path).toBe('/stub/app.log');
    expect(snapshot.config.ui.language).toBe('ru');
    await b.stop();
    expect(b.alive()).toBe(false);
  });

  it('reports a process killed from outside, with its signal, and forgets the connection', async () => {
    const b = backend('ok');
    const exits = [];
    b.onExit = (code, signal) => exits.push({ code, signal });
    await b.start();
    process.kill(b.child.pid, 'SIGKILL');
    expect(await until(() => exits.length === 1)).toBe(true);
    // POSIX reports the signal; Windows has no signals, so a terminated child
    // reports a non-zero exit code and no signal.
    if (process.platform === 'win32') {
      expect(exits[0].signal).toBeNull();
      expect(exits[0].code).not.toBe(0);
      expect(exits[0].code).not.toBeNull();
    } else {
      expect(exits[0]).toEqual({ code: null, signal: 'SIGKILL' });
    }
    expect(b.connection).toBeNull();
    expect(await b.healthy(500)).toBe(false);
  });

  it('does not report an exit it asked for, nor one of a child that was replaced', async () => {
    const b = backend('ok');
    const exits = [];
    b.onExit = (...args) => exits.push(args);
    await b.start();
    const first = b.child;
    await b.stop();
    const second = await b.start();
    expect(second.port).toBeGreaterThan(0);
    expect(b.child).not.toBe(first);
    await new Promise((r) => setTimeout(r, 200));
    expect(exits).toEqual([]);
    expect(b.alive()).toBe(true);
  });

  it('can be started again after it died, on a new port with a live runtime', async () => {
    const b = backend('ok');
    const exits = [];
    b.onExit = (...args) => exits.push(args);
    const before = await b.start();
    process.kill(b.child.pid, 'SIGKILL');
    await until(() => exits.length === 1);
    const after = await b.start();
    expect(after.port).not.toBe(before.port);
    expect(await b.healthy()).toBe(true);
    expect(exits).toHaveLength(1);
  });

  it('says what happened when it exits while starting, and keeps the child\'s last lines apart', async () => {
    const error = await backend('exit1').start().catch((e) => e);
    expect(error).toBeInstanceOf(StartError);
    expect(error.kind).toBe('exited');
    expect(error.code).toBe(1);
    expect(error.detail).toContain('ImportError');
    expect(error.message).not.toContain('ImportError');
  });

  it('tells "another copy is running" from other failures', async () => {
    const error = await backend('already').start().catch((e) => e);
    expect(error.kind).toBe('already_running');
  });

  it('gives up on a runtime that never prints the ready line, and kills it', async () => {
    const b = backend('never');
    const error = await b.start(400).catch((e) => e);
    expect(error.kind).toBe('timeout');
    expect(await until(() => !b.alive(), 12000)).toBe(true);
  }, 20000);

  it('names a missing binary', async () => {
    process.env.L2T_BACKEND_CMD = '/nonexistent/server';
    const b = new Backend(app);
    const error = await b.start().catch((e) => e);
    expect(error.kind).toBe('missing');
    expect(error.message).toContain('/nonexistent/server');
  });
});

describe.skipIf(!usable)('the event stream as a second witness', () => {
  it('delivers events and reports the loss once when the runtime dies', async () => {
    const b = backend('ok');
    await b.start();
    const states = [];
    let lost = 0;
    const stop = connectEvents(b.connection, { state: (s) => states.push(s.state) }, () => { lost += 1; });
    expect(await until(() => states.includes('recording'))).toBe(true);
    expect(lost).toBe(0);
    process.kill(b.child.pid, 'SIGKILL');
    expect(await until(() => lost >= 1)).toBe(true);
    await new Promise((r) => setTimeout(r, 2500));
    expect(lost).toBe(1);
    stop();
  }, 15000);

  it('treats a stream that goes quiet as lost, so a hung runtime is noticed', async () => {
    const b = backend('silent');
    await b.start();
    let lost = 0;
    const stop = connectEvents(b.connection, {}, () => { lost += 1; }, 300);
    expect(await until(() => lost >= 1, 3000)).toBe(true);
    stop();
  });

  it('does nothing after it was stopped', async () => {
    const b = backend('ok');
    await b.start();
    let lost = 0;
    const stop = connectEvents(b.connection, {}, () => { lost += 1; });
    await new Promise((r) => setTimeout(r, 200));
    stop();
    await b.kill();
    await new Promise((r) => setTimeout(r, 1500));
    expect(lost).toBe(0);
  });
});

describe.skipIf(!usable)('the stream is opened with a one-time ticket, never with the token in a URL', () => {
  const stats = async (b) => (await fetch(`http://127.0.0.1:${b.connection.port}/__stub`)).json();

  it('asks for a ticket, opens the stream with it and carries no token in the URL', async () => {
    const b = backend('ok', { STUB_TICKETS: 'strict' });
    await b.start();
    const states = [];
    const stop = connectEvents(b.connection, { state: (s) => states.push(s.state) });
    expect(await until(() => states.includes('recording'))).toBe(true);
    const seen = await stats(b);
    expect(seen.tickets_issued).toBe(1);
    expect(seen.streams_by_ticket).toBe(1);
    expect(seen.streams_by_header + seen.streams_by_query_token).toBe(0);
    stop();
  });

  it('asks for a new ticket on every reconnect, because a ticket is spent by one stream', async () => {
    const b = backend('ok', { STUB_TICKETS: 'strict' });
    await b.start();
    let lost = 0;
    const states = [];
    // 300 ms of silence ends each stream, so the client reconnects over and over.
    const stop = connectEvents(b.connection, { state: (s) => states.push(s.state) }, () => { lost += 1; }, 300);
    await until(() => lost >= 2, 6000);
    const seen = await stats(b);
    expect(seen.tickets_issued).toBeGreaterThanOrEqual(2);
    expect(seen.streams_by_ticket).toBe(seen.tickets_issued);
    expect(seen.refused).toBe(0);
    stop();
  }, 10000);

  it('falls back to the token only when the runtime does not know the ticket method', async () => {
    const b = backend('ok', { STUB_TICKETS: 'legacy' });
    await b.start();
    const states = [];
    const stop = connectEvents(b.connection, { state: (s) => states.push(s.state) });
    expect(await until(() => states.includes('recording'))).toBe(true);
    const seen = await stats(b);
    expect(seen.tickets_issued).toBe(0);
    expect(seen.streams_by_header).toBe(1);
    stop();
  });

  it('does not fall back when the ticket call merely fails: that is a loss, not a legacy runtime', async () => {
    const b = backend('ok', { STUB_TICKETS: 'strict' });
    await b.start();
    let lost = 0;
    const bad = { port: b.connection.port, token: 'wrong' };
    const stop = connectEvents(bad, {}, () => { lost += 1; });
    expect(await until(() => lost >= 1, 3000)).toBe(true);
    const seen = await stats(b);
    expect(seen.streams_by_header + seen.streams_by_query_token + seen.streams_by_ticket).toBe(0);
    stop();
  });
});
