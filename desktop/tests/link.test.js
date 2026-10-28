// The window and the runtime: noticing that the runtime is gone, saying so,
// and coming back when it returns. EventSource and fetch are fakes; what is
// under test is the decision logic in lib/rpc.js, lib/backend.js and the
// dialog that tells the user.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import * as rpcModule from '../renderer/src/lib/rpc.js';
import * as backendModule from '../renderer/src/lib/backend.js';
import EngineDown from '../renderer/src/components/EngineDown.svelte';

class FakeSource {
  static all = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.closed = false;
    this.listeners = {};
    FakeSource.all.push(this);
  }
  addEventListener(name, cb) {
    (this.listeners[name] ||= []).push(cb);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  fail(final = false) {
    if (final) this.readyState = 2;
    this.onerror?.();
  }
}
FakeSource.CONNECTING = 0;
FakeSource.OPEN = 1;
FakeSource.CLOSED = 2;

let up;
let rpc;
let backend;

let tickets = 0;
let ticketsSupported = true;
function fakeFetch() {
  return vi.fn(async (url, init) => {
    if (String(url).endsWith('/health')) {
      if (!up) throw new TypeError('Failed to fetch');
      return { ok: true };
    }
    if (!up) throw new TypeError('Failed to fetch');
    const method = JSON.parse(init.body).method;
    if (method === 'app.events_ticket') {
      if (!ticketsSupported) return { ok: true, json: async () => ({ error: { code: 'unknown_method', message: 'no' } }) };
      return { ok: true, json: async () => ({ result: { ticket: `T${++tickets}`, ttl_s: 30 } }) };
    }
    return { ok: true, json: async () => ({ result: { state: 'idle', config: { ui: {} }, log_path: '/logs/app.log' } }) };
  });
}

beforeEach(() => {
  // The modules are imported once, at the top of the file: a module registry
  // reset would hand the component and the test two different copies of the
  // Svelte runtime, and the component would mount into the wrong one. The
  // state is reset through the hooks the modules expose instead.
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
  FakeSource.all = [];
  tickets = 0;
  ticketsSupported = true;
  up = true;
  vi.stubGlobal('EventSource', FakeSource);
  vi.stubGlobal('fetch', fakeFetch());
  // A plain tab finds its runtime in the page URL, and asks again from there.
  window.history.replaceState(null, '', '/?port=4242&token=tok');
  rpc = rpcModule;
  backend = backendModule;
  rpc._resetLink();
  backend._resetBackend();
  rpc._setConnection({ port: 4242, token: 'tok' });
});

afterEach(() => {
  cleanup();
  rpc._resetLink();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete window.l2t;
  window.history.replaceState(null, '', '/');
});

const settle = async (ms = 0) => {
  await vi.advanceTimersByTimeAsync(ms);
};

describe('the link to the runtime', () => {
  it('names a failed request in words, not as "Failed to fetch"', async () => {
    up = false;
    await expect(rpc.call('app.ping')).rejects.toMatchObject({ code: 'unreachable', message: 'The engine is not responding.' });
  });

  it('opens the stream with a one-time ticket, never with the launch token in the URL', async () => {
    rpc.subscribe('state', () => {});
    await settle();
    expect(FakeSource.all[0].url).toBe('http://127.0.0.1:4242/events?ticket=T1');
    expect(FakeSource.all[0].url).not.toContain('tok');
  });

  it('falls back to the token for a runtime that has no tickets', async () => {
    ticketsSupported = false;
    rpc.subscribe('state', () => {});
    await settle();
    expect(FakeSource.all[0].url).toBe('http://127.0.0.1:4242/events?token=tok');
  });

  it('opens a new stream with a new ticket when the old one is lost but the runtime answers', async () => {
    const back = vi.fn();
    const down = vi.fn();
    rpc.subscribe('__connected', back);
    rpc.subscribe('__disconnected', down);
    rpc.subscribe('state', () => {});
    await settle();

    // The browser's own retry presents the spent ticket and the stream ends for good.
    FakeSource.all[0].fail(true);
    await settle(10);

    expect(down).not.toHaveBeenCalled();
    expect(FakeSource.all.length).toBe(2);
    expect(FakeSource.all[1].url).toBe('http://127.0.0.1:4242/events?ticket=T2');
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('declares the runtime gone when the stream errors and /health does not answer', async () => {
    const down = vi.fn();
    rpc.subscribe('__disconnected', down);
    rpc.subscribe('state', () => {});
    await settle();
    expect(FakeSource.all.length).toBe(1);

    up = false;
    FakeSource.all[0].fail();
    await settle(1200);

    expect(down).toHaveBeenCalledTimes(1);
    expect(rpc.linkState()).toBe('down');
    expect(FakeSource.all[0].closed).toBe(true);
  });

  it('does not cry wolf when the stream blinks but the runtime answers', async () => {
    const down = vi.fn();
    const back = vi.fn();
    rpc.subscribe('__disconnected', down);
    rpc.subscribe('__connected', back);
    rpc.subscribe('state', () => {});
    await settle();

    FakeSource.all[0].fail();
    await settle(1200);
    expect(down).not.toHaveBeenCalled();

    // The browser reopens the stream by itself; what was said in the gap is lost.
    FakeSource.all[0].onopen();
    expect(back).toHaveBeenCalledTimes(1);
  });

  it('keeps asking until the runtime is back, then reopens the stream and says so', async () => {
    const down = vi.fn();
    const back = vi.fn();
    const seen = vi.fn();
    rpc.subscribe('__disconnected', down);
    rpc.subscribe('__connected', back);
    rpc.subscribe('state', seen);
    await settle();

    up = false;
    FakeSource.all[0].fail(true);
    await settle(10);
    expect(down).toHaveBeenCalledTimes(1);

    await settle(6000);
    expect(back).not.toHaveBeenCalled();

    up = true;
    await settle(2500);
    expect(back).toHaveBeenCalledTimes(1);
    expect(rpc.linkState()).toBe('up');
    // A fresh stream, with the earlier subscriptions attached to it.
    const fresh = FakeSource.all.at(-1);
    expect(fresh).not.toBe(FakeSource.all[0]);
    fresh.listeners.state[0]({ data: JSON.stringify({ state: 'recording' }) });
    expect(seen).toHaveBeenCalledWith({ state: 'recording' });
  });

  it('asks the shell for the connection again, because a restarted runtime has a new port', async () => {
    window.l2t = { connection: vi.fn().mockResolvedValue({ port: 5000, token: 'new' }) };
    rpc._setConnection(null);
    const back = vi.fn();
    rpc.subscribe('__connected', back);
    await rpc.reconnect();
    expect(window.l2t.connection).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith('http://127.0.0.1:5000/health', expect.anything());
    expect(back).toHaveBeenCalled();
  });
});

describe('what the window shows when the runtime dies', () => {
  async function started() {
    await backend.start();
    await settle();
  }

  it('resets the live state, raises the flag and reads everything again on return', async () => {
    await started();
    backend.state.set('recording');
    backend.engine.set({ provider: 'CPU', model: 'm', alias: 'a' });
    expect(get(backend.engineDown)).toBe(false);

    up = false;
    FakeSource.all[0].fail(true);
    await settle(10);

    expect(get(backend.engineDown)).toBe(true);
    expect(get(backend.state)).toBe('disconnected');
    expect(get(backend.engine).provider).toBeNull();
    expect(get(backend.modelLoaded)).toBe(false);
    expect(backend.lastLogPath()).toBe('/logs/app.log');

    const before = get(backend.epoch);
    up = true;
    await settle(2500);

    expect(get(backend.engineDown)).toBe(false);
    expect(get(backend.state)).toBe('idle');
    expect(get(backend.epoch)).toBe(before + 1);
  });

  it('hears about the exit from the shell before the stream notices', async () => {
    let exit;
    window.l2t = { backend: { onExit: (cb) => (exit = cb), onRestarted: () => {}, restart: vi.fn() } };
    await started();

    up = false;
    exit();
    await settle(10);

    expect(get(backend.engineDown)).toBe(true);
  });

  it('still hears an older shell, which only has onBackendExit', async () => {
    let exit;
    window.l2t = { onBackendExit: (cb) => (exit = cb) };
    await started();
    up = false;
    exit();
    await settle(10);
    expect(get(backend.engineDown)).toBe(true);
  });

  it('restarts through the shell and waits for the runtime', async () => {
    const restart = vi.fn(async () => {
      up = true;
    });
    window.l2t = { backend: { onExit: () => {}, onRestarted: () => {}, restart } };
    await started();
    up = false;
    FakeSource.all[0].fail(true);
    await settle(10);

    await backend.restartEngine();

    expect(restart).toHaveBeenCalledTimes(1);
    expect(get(backend.engineDown)).toBe(false);
    expect(get(backend.restarting)).toBe(false);
  });

  it('says when the restart did not bring it back', async () => {
    window.l2t = { backend: { onExit: () => {}, onRestarted: () => {}, restart: vi.fn(async () => {}) } };
    await started();
    up = false;
    FakeSource.all[0].fail(true);
    await settle(10);

    await backend.restartEngine();

    expect(get(backend.engineDown)).toBe(true);
    expect(get(backend.restartError)).toContain('did not come back');
  });

  it('reconnects when the shell says it started a new runtime', async () => {
    let restarted;
    window.l2t = {
      backend: { onExit: () => {}, onRestarted: (cb) => (restarted = cb), restart: vi.fn() },
      connection: async () => ({ port: 9, token: 't' }),
    };
    await started();
    up = false;
    FakeSource.all[0].fail(true);
    await settle(10);
    up = true;
    restarted({});
    await settle(10);
    expect(get(backend.engineDown)).toBe(false);
  });
});

describe('the dialog', () => {
  function dialog() {
    render(EngineDown);
  }

  it('is closed while the engine runs and blocks the window when it stops', async () => {
    dialog();
    expect(screen.queryByTestId('engine-down')).toBeNull();

    backend.snapshot.set({ log_path: '/logs/app.log' });
    backend.engineDown.set(true);

    expect(await screen.findByText('The engine stopped')).toBeTruthy();
    expect(screen.getByTestId('engine-down').textContent).toContain('/logs/app.log');
    // No way to wave it off: no close button, and Escape does nothing.
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('offers Restart when the shell can restart the runtime', async () => {
    window.l2t = { backend: { restart: vi.fn(async () => {}) } };
    dialog();
    backend.engineDown.set(true);
    expect(await screen.findByRole('button', { name: 'Restart' })).toBeTruthy();
  });

  it('closes by itself when the engine is back', async () => {
    dialog();
    backend.engineDown.set(true);
    await screen.findByText('The engine stopped');
    backend.engineDown.set(false);
    await waitFor(() => expect(screen.queryByText('The engine stopped')).toBeNull());
  });
});
