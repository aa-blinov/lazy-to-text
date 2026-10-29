// The capsule and the tray against a runtime that dies: windows.cjs with a
// fake `electron` and the stand-in runtime of tests/helpers/stubRuntime.cjs.
// A real runtime that is killed must take the capsule down with it and put
// the tray back to idle, which is what the field report said it did not.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

const require = createRequire(import.meta.url);
const stub = join(import.meta.dirname, 'helpers', 'stubRuntime.cjs');
const usable = !/\s/.test(process.execPath) && !/\s/.test(stub);

const made = { windows: [], tray: null, menus: [] };

function fakeElectron() {
  class FakeContents {
    constructor(win) { this.sent = []; this.win = win; }
    getURL() { return (this.win && this.win.url) || ''; }
    on() {}
    setWindowOpenHandler() {}
    isDestroyed() { return false; }
    send(channel, payload) { this.sent.push([channel, payload]); }
  }
  class BrowserWindow {
    constructor(options) {
      this.options = options;
      this.visible = false;
      this.calls = [];
      this.webContents = new FakeContents(this);
      made.windows.push(this);
    }
    setIgnoreMouseEvents() {}
    setAlwaysOnTop() {}
    setVisibleOnAllWorkspaces() {}
    loadURL(url) { this.url = url; }
    on() {}
    once() {}
    isDestroyed() { return !!this.destroyed; }
    isVisible() { return this.visible; }
    setBounds(bounds) { this.bounds = bounds; this.calls.push('setBounds'); }
    showInactive() { this.visible = true; this.calls.push('showInactive'); }
    moveTop() {}
    hide() { this.visible = false; this.calls.push('hide'); }
    destroy() { this.destroyed = true; }
  }
  class Tray {
    constructor() { this.tip = ''; this.menu = null; this.images = []; made.tray = this; }
    setToolTip(tip) { this.tip = tip; }
    setImage(image) { this.images.push(image); }
    setContextMenu(menu) { this.menu = menu; }
    on() {}
    isDestroyed() { return false; }
    destroy() {}
  }
  const display = { id: 1, workArea: { x: 0, y: 25, width: 1440, height: 875 } };
  return {
    app: { dock: { show() {} }, isHidden: () => false, show() {} },
    BrowserWindow,
    Tray,
    Menu: { buildFromTemplate: (t) => { made.menus.push(t); return t; } },
    nativeImage: { createFromPath: (p) => ({ path: p, resize: () => ({ path: p }) }) },
    screen: {
      getCursorScreenPoint: () => ({ x: 10, y: 10 }),
      getDisplayNearestPoint: () => display,
      getAllDisplays: () => [display],
      getPrimaryDisplay: () => display,
      on: () => {},
    },
    shell: { openExternal: vi.fn() },
    session: { defaultSession: null },
  };
}

let windows;
let Backend;
let backend;

beforeAll(() => {
  const electron = fakeElectron();
  const Module = require('node:module');
  const original = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : original.call(this, request, ...rest);
  };
  try {
    windows = require('../electron/windows.cjs');
    ({ Backend } = require('../electron/backend.cjs'));
  } finally {
    Module._load = original;
  }
});

afterEach(async () => {
  if (backend) await backend.kill();
  backend = null;
  delete process.env.L2T_BACKEND_CMD;
  delete process.env.STUB_MODE;
});

afterAll(() => windows.destroyAll());

const until = async (predicate, ms = 6000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (predicate()) return true;
    await new Promise((r) => setTimeout(r, 25));
  }
  return predicate();
};

describe.skipIf(!usable)('the capsule and the tray follow the runtime and let go of it', () => {
  it('shows on recording, and hides at once, idle, when the runtime is killed; and comes back with a restart', async () => {
    process.env.L2T_BACKEND_CMD = `${process.execPath} ${stub}`;
    process.env.STUB_MODE = 'ok';
    backend = new Backend({ isPackaged: false });
    let died = 0;
    backend.onExit = () => { died += 1; windows.engineLost(); };
    await backend.start();

    windows.configure({
      preload: '/p', backend, stateFile: '/tmp/l2t-test-window-state.json',
      onStreamLost: () => {},
      // A Linux runner has no StatusNotifier host; the tray is the subject here.
      linuxTrayHost: () => true,
    });
    windows.setLanguage('en');
    windows.startOverlayFeed();
    // On macOS the capsule is replaced after every appearance: ask for the current window.
    const overlay = () => made.windows.filter((w) => w.options.transparent && !w.destroyed).at(-1);
    const tray = made.tray;
    expect(overlay()).toBeTruthy();
    expect(tray).toBeTruthy();

    // The stand-in reports `recording` on connect.
    expect(await until(() => overlay().visible)).toBe(true);
    expect(tray.tip).toBe('Lazy to Text: recording');
    // The system takes a panel off the screen without telling the app (a
    // full-screen Space): while the capsule is wanted it is put back.
    overlay().visible = false;
    expect(await until(() => overlay().visible, 3000)).toBe(true);
    // Placed inside the display's work area, in the bottom-right corner (spec 007 FR-007).
    expect(overlay().bounds.x + overlay().bounds.width).toBe(1440 - 8);
    expect(overlay().bounds.y + overlay().bounds.height).toBe(25 + 875);
    expect(overlay().bounds.x + overlay().bounds.width).toBeLessThanOrEqual(1440);
    expect(overlay().bounds.y + overlay().bounds.height).toBeLessThanOrEqual(25 + 875);

    process.kill(backend.child.pid, 'SIGKILL');
    expect(await until(() => died === 1)).toBe(true);
    expect(overlay().visible).toBe(false);
    expect(tray.tip).toBe('Lazy to Text: engine stopped');
    expect(tray.images.at(-1).path).toMatch(/tray_idle/);
    // A restart-engine entry appears in the tray menu only now.
    const items = made.menus.at(-1);
    expect(items.find((i) => i.label === 'Restart engine').visible).toBe(true);

    // Events from nothing keep it down: the feed is stopped, nothing shows it again.
    await new Promise((r) => setTimeout(r, 1500));
    expect(overlay().visible).toBe(false);

    const connection = await backend.start();
    windows.engineBack(connection);
    expect(await until(() => overlay().visible)).toBe(true);
    expect(made.menus.at(-1).find((i) => i.label === 'Restart engine').visible).toBe(false);
  }, 20000);

  it('replaces the capsule window after every appearance on macOS, and keeps one on other systems', async () => {
    const live = () => made.windows.filter((w) => w.options.transparent && !w.destroyed);
    windows.destroyAll();
    const real = process.platform;
    const setPlatform = (value) => Object.defineProperty(process, 'platform', { value, configurable: true });
    try {
      for (const [platform, replaced] of [['darwin', true], ['linux', false]]) {
        setPlatform(platform);
        process.env.L2T_BACKEND_CMD = `${process.execPath} ${stub}`;
        process.env.STUB_MODE = 'ok';
        const mine = new Backend({ isPackaged: false });
        await mine.start();
        windows.configure({ preload: '/p', backend: mine, stateFile: '/tmp/l2t-test-window-state.json', onStreamLost: () => {}, linuxTrayHost: () => true });
        windows.startOverlayFeed();
        expect(live()).toHaveLength(1);
        const shown = live()[0];
        expect(await until(() => shown.visible)).toBe(true);

        process.kill(mine.child.pid, 'SIGKILL');
        windows.engineLost();
        expect(await until(() => !shown.visible)).toBe(true);

        // One window waits for the next recording; only on macOS is it a new one.
        expect(live()).toHaveLength(1);
        expect(live()[0] === shown).toBe(!replaced);
        expect(shown.destroyed === true).toBe(replaced);
        await mine.kill();
        windows.destroyAll();
      }
    } finally {
      setPlatform(real);
    }
  }, 30000);

  it('translates the tray into Russian when the runtime says so', () => {
    windows.setLanguage('ru');
    const items = made.menus.at(-1);
    expect(items.map((i) => i.label)).toEqual(['Показать окно', 'Перезапустить движок', undefined, 'Выйти']);
    expect(made.tray.tip).toMatch(/Lazy to Text: /);
    windows.setLanguage('en');
  });

  it('answers whether a Linux desktop has a tray with no for "cannot ask"', () => {
    const saved = process.env.PATH;
    process.env.PATH = '/nonexistent';
    try {
      expect(windows._internals.linuxTrayHost()).toBe(false);
    } finally {
      process.env.PATH = saved;
    }
  });
});
