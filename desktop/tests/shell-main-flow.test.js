// The whole main process through a fake `electron` and the stand-in runtime:
// what the user is shown while the runtime starts, when it cannot start, when
// it dies under a running window, and when it is restarted. These are the
// field reports of QA-SHELL-1, 2 and 3 as assertions.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const require = createRequire(import.meta.url);
const electronDir = join(import.meta.dirname, '..', 'electron');
const stub = join(import.meta.dirname, 'helpers', 'stubRuntime.cjs');
const usable = !/\s/.test(process.execPath) && !/\s/.test(stub);

let made;
let handlers;
let listeners;
let electron;
let exits;
let dialogs;

function fakeElectron() {
  class Contents {
    constructor(win) { this.win = win; this.sent = []; this.handlers = {}; }
    on(name, fn) { this.handlers[name] = fn; }
    once(name, fn) { this.handlers[`once:${name}`] = fn; }
    setWindowOpenHandler() {}
    isDestroyed() { return this.win.destroyed; }
    isLoading() { return false; }
    getURL() { return this.win.url || ''; }
    send(channel, payload) { this.sent.push([channel, payload]); }
  }
  class BrowserWindow {
    constructor(options) {
      this.options = options;
      this.destroyed = false;
      this.visible = false;
      this.handlers = {};
      this.webContents = new Contents(this);
      made.push(this);
    }
    static fromWebContents() { return null; }
    removeMenu() {}
    setIgnoreMouseEvents() {}
    setAlwaysOnTop() {}
    setVisibleOnAllWorkspaces() {}
    loadURL(url) { this.url = url; }
    on(name, fn) { this.handlers[name] = fn; }
    once(name, fn) { this.handlers[`once:${name}`] = fn; }
    removeAllListeners() { this.handlers = {}; }
    isDestroyed() { return this.destroyed; }
    isVisible() { return this.visible; }
    isMinimized() { return false; }
    isFullScreen() { return false; }
    isMaximized() { return false; }
    getBounds() { return { x: 1, y: 1, width: 1000, height: 700 }; }
    show() { this.visible = true; }
    showInactive() { this.visible = true; }
    hide() { this.visible = false; }
    focus() {}
    moveTop() {}
    setBounds() {}
    maximize() {}
    destroy() { this.destroyed = true; this.visible = false; if (this.handlers.closed) this.handlers.closed(); }
  }
  class Tray {
    constructor() { this.tip = ''; }
    setToolTip(t) { this.tip = t; }
    setImage() {}
    setContextMenu() {}
    on() {}
    isDestroyed() { return false; }
    destroy() {}
  }
  const display = { id: 1, workArea: { x: 0, y: 25, width: 1440, height: 875 } };
  return {
    app: {
      setName() {}, requestSingleInstanceLock: () => true, exit: (code) => exits.push(code), whenReady: () => Promise.resolve(),
      on() {}, relaunch() {}, releaseSingleInstanceLock() {}, isPackaged: false, name: 'Lazy to Text',
      getLocale: () => 'en-US', getPath: () => tmpdir(), focus() {}, dock: { show() {} }, isHidden: () => false, show() {},
    },
    BrowserWindow,
    Tray,
    Menu: { setApplicationMenu() {}, buildFromTemplate: (t) => t },
    nativeTheme: { themeSource: 'system' },
    nativeImage: { createFromPath: () => ({ resize: () => ({}) }) },
    screen: {
      getCursorScreenPoint: () => ({ x: 1, y: 1 }), getDisplayNearestPoint: () => display,
      getAllDisplays: () => [display], getPrimaryDisplay: () => display, on() {},
    },
    ipcMain: { handle: (n, f) => handlers.set(n, f), on: (n, f) => listeners.set(n, f) },
    dialog: { showMessageBox: async (o) => { dialogs.push(o); return { response: 0 }; }, showOpenDialog: vi.fn(), showSaveDialog: vi.fn() },
    shell: { openExternal: vi.fn(), showItemInFolder: vi.fn() },
    clipboard: { writeText: vi.fn() },
    protocol: { registerSchemesAsPrivileged() {}, handle() {} },
    session: { defaultSession: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} } },
  };
}

const until = async (predicate, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 25));
  }
  return predicate();
};

let backendOf;

function boot(mode) {
  process.env.L2T_BACKEND_CMD = `${process.execPath} ${stub}`;
  process.env.STUB_MODE = mode;
  process.env.STUB_LANGUAGE = 'en';
  const Module = require('node:module');
  const original = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : original.call(this, request, ...rest);
  };
  try {
    require(join(electronDir, 'main.cjs'));
  } finally {
    Module._load = original;
  }
}

const mainWindow = () => made.find((w) => w.url && w.url.endsWith('/index.html'));
const splashWindow = () => made.find((w) => w.url && w.url.includes('/splash.html'));
const splashStates = () => (splashWindow() ? splashWindow().webContents.sent.filter(([c]) => c === 'l2t:splash:state').map(([, s]) => s) : []);
// ipcMain.handle turns a throw into a rejection; so does this.
const ask = (name, event) => Promise.resolve().then(() => handlers.get(name)(event));
// The stand-in tells its own pid: other test files run their own at the same time.
const stubPid = async () => {
  const { port, token } = await handlers.get('l2t:connection')(fromMain());
  const response = await fetch(`http://127.0.0.1:${port}/rpc`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ method: 'app.snapshot', params: {} }),
  });
  return (await response.json()).result.pid;
};
const fromMain = () => ({ sender: mainWindow().webContents, senderFrame: { url: 'l2t-app://app/index.html' } });
const fromSplash = () => ({ sender: splashWindow().webContents, senderFrame: { url: 'l2t-app://app/splash.html' } });

beforeEach(() => {
  made = [];
  handlers = new Map();
  listeners = new Map();
  exits = [];
  dialogs = [];
  electron = fakeElectron();
  if (!process.argv.includes('--l2t-selftest')) process.argv.push('--l2t-selftest');
  for (const key of Object.keys(require.cache)) if (key.startsWith(electronDir)) delete require.cache[key];
});

afterEach(async () => {
  // Stop the runtime this test started, through the main process's own quit.
  if (listeners.has('l2t:quit') && mainWindow()) {
    listeners.get('l2t:quit')(fromMain());
    await until(() => exits.length > 0, 12000);
  } else if (splashWindow() && listeners.has('l2t:splash:quit')) {
    listeners.get('l2t:splash:quit')(fromSplash());
    await until(() => exits.length > 0, 12000);
  }
  delete process.env.L2T_BACKEND_CMD;
  delete process.env.STUB_MODE;
  delete process.env.STUB_LANGUAGE;
});

describe.skipIf(!usable)('start-up', () => {
  it('shows the loading window at once, before the runtime has said anything, then the shell', async () => {
    boot('slowok');
    expect(await until(() => splashWindow())).toBeTruthy();
    expect(mainWindow()).toBeUndefined();
    expect(splashWindow().url).toMatch(/^l2t-app:\/\/app\/splash\.html#/);
    expect(decodeURIComponent(splashWindow().url.split('#')[1])).toContain('"mode":"loading"');
    expect(splashWindow().options.webPreferences.preload).toMatch(/splash-preload\.cjs$/);
    expect(await until(() => mainWindow())).toBeTruthy();
    expect(mainWindow().options.webPreferences.sandbox).toBe(true);
    // The loading window goes when the real one is ready to show.
    mainWindow().handlers['once:ready-to-show']?.();
    expect(await until(() => splashWindow().destroyed)).toBe(true);
  });

  it('shows what went wrong, with the log path and Retry, and no shell, when the runtime cannot start', async () => {
    boot('exit1');
    expect(await until(() => splashStates().some((s) => s.mode === 'error'))).toBe(true);
    const state = splashStates().find((s) => s.mode === 'error');
    expect(state.title).toBe('The engine did not start');
    expect(state.message).toBe('The engine stopped while starting (exit code 1).');
    expect(state.message).not.toMatch(/Error invoking remote method/);
    expect(state.detail).toContain('ImportError');
    expect(state.logPath).toMatch(/app\.log$/);
    expect(state.labels.retry).toBe('Retry');
    expect(mainWindow()).toBeUndefined();
  });

  it('starts again on Retry, and a splash that is not the splash cannot retry', async () => {
    boot('exit1');
    expect(await until(() => splashStates().some((s) => s.mode === 'error'))).toBe(true);
    process.env.STUB_MODE = 'ok';
    listeners.get('l2t:splash:retry')({ sender: {}, senderFrame: { url: 'file:///evil.html' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(mainWindow()).toBeUndefined();
    listeners.get('l2t:splash:retry')(fromSplash());
    expect(await until(() => splashStates().some((s) => s.mode === 'loading'))).toBe(true);
    expect(await until(() => mainWindow())).toBeTruthy();
  });

  it('says another copy is running, in front, and starts no window', async () => {
    boot('already');
    expect(await until(() => dialogs.length === 1)).toBe(true);
    expect(dialogs[0].detail).toMatch(/already running/);
    expect(await until(() => exits.includes(0))).toBe(true);
    expect(mainWindow()).toBeUndefined();
  });

  it('writes the start-up page in Russian when the system is Russian', async () => {
    electron.app.getLocale = () => 'ru-RU';
    boot('exit1');
    expect(await until(() => splashStates().some((s) => s.mode === 'error'))).toBe(true);
    const state = splashStates().find((s) => s.mode === 'error');
    expect(state.title).toBe('Движок не запустился');
    expect(state.labels.retry).toBe('Повторить');
  });
});

describe.skipIf(!usable)('a runtime that dies under a running window', () => {
  async function running() {
    boot('ok');
    expect(await until(() => mainWindow())).toBeTruthy();
    const win = mainWindow();
    win.visible = true;
    return win;
  }

  it('tells every window, and refuses the connection until the runtime is back', async () => {
    const win = await running();
    const connection = await handlers.get('l2t:connection')(fromMain());
    expect(connection.port).toBeGreaterThan(0);
    const overlay = made.find((w) => w.options.transparent);

    process.kill(await stubPid(), 'SIGKILL');

    expect(await until(() => win.webContents.sent.some(([c]) => c === 'l2t:backend-exit'))).toBe(true);
    const [, payload] = win.webContents.sent.find(([c]) => c === 'l2t:backend-exit');
    // Windows has no signals: a terminated child reports a non-zero code.
    if (process.platform === 'win32') {
      expect(payload.signal).toBeNull();
      expect(payload.code).not.toBe(0);
      expect(payload.code).not.toBeNull();
    } else {
      expect(payload).toEqual({ code: null, signal: 'SIGKILL' });
    }
    expect(win.webContents.sent.filter(([c]) => c === 'l2t:backend-exit')).toHaveLength(1);
    expect(overlay.webContents.sent.some(([c]) => c === 'l2t:backend-exit')).toBe(true);
    await expect(ask('l2t:connection', fromMain())).rejects.toThrow('The engine is not running.');
    expect(overlay.visible).toBe(false);
  });

  it('restarts on request and hands every window the new connection', async () => {
    const win = await running();
    const old = await handlers.get('l2t:connection')(fromMain());
    process.kill(await stubPid(), 'SIGKILL');
    expect(await until(() => win.webContents.sent.some(([c]) => c === 'l2t:backend-exit'))).toBe(true);

    const answer = await handlers.get('l2t:backend:restart')(fromMain());
    expect(answer.ok).toBe(true);
    expect(answer.connection.port).not.toBe(old.port);
    const now = await handlers.get('l2t:connection')(fromMain());
    expect(now).toEqual(answer.connection);
    const announced = win.webContents.sent.find(([c]) => c === 'l2t:backend-restarted');
    expect(announced[1]).toEqual(answer.connection);
  });

  it('does not send the connection or the exit to a window that shows a page that is not the app\'s', async () => {
    const win = await running();
    const overlay = made.find((w) => w.options.transparent);
    const old = await handlers.get('l2t:connection')(fromMain());
    // A page got into the main window (a navigation that slipped through): the preload follows it.
    win.webContents.getURL = () => 'file:///tmp/evil.html';
    process.kill(await stubPid(), 'SIGKILL');
    expect(await until(() => overlay.webContents.sent.some(([c]) => c === 'l2t:backend-exit'))).toBe(true);
    expect(win.webContents.sent.some(([c]) => c === 'l2t:backend-exit')).toBe(false);

    const answer = await handlers.get('l2t:backend:restart')(fromMain());
    expect(answer.ok).toBe(true);
    expect(answer.connection.port).not.toBe(old.port);
    expect(overlay.webContents.sent.some(([c, p]) => c === 'l2t:backend-restarted' && p.token === answer.connection.token)).toBe(true);
    expect(win.webContents.sent.some(([c]) => c === 'l2t:backend-restarted')).toBe(false);
    // And the page itself, asking for the connection, is refused by the sender check.
    const foreign = { sender: win.webContents, senderFrame: { url: 'file:///tmp/evil.html' } };
    await expect(ask('l2t:connection', foreign)).rejects.toThrow('Not allowed');
  });

  it('answers a failed restart with a message a person can read', async () => {
    const win = await running();
    process.kill(await stubPid(), 'SIGKILL');
    expect(await until(() => win.webContents.sent.some(([c]) => c === 'l2t:backend-exit'))).toBe(true);
    process.env.STUB_MODE = 'exit1';
    const answer = await handlers.get('l2t:backend:restart')(fromMain());
    expect(answer).toEqual({ ok: false, message: 'The engine stopped while starting (exit code 1).' });
    // Still dead, still offering the way back.
    await expect(ask('l2t:connection', fromMain())).rejects.toThrow();
    process.env.STUB_MODE = 'ok';
    expect((await handlers.get('l2t:backend:restart')(fromMain())).ok).toBe(true);
  });

  it('leaves a runtime that is answering alone when a window asks for a restart', async () => {
    await running();
    const before = await handlers.get('l2t:connection')(fromMain());
    const answer = await handlers.get('l2t:backend:restart')(fromMain());
    expect(answer.ok).toBe(true);
    expect(answer.connection).toEqual(before);
  });

  it('gives the log path the runtime reported', async () => {
    await running();
    await until(() => true, 300);
    const reply = {};
    listeners.get('l2t:backend:log-path')({ ...fromMain(), set returnValue(v) { reply.value = v; } });
    expect(reply.value).toBe('/stub/app.log');
  });
});
