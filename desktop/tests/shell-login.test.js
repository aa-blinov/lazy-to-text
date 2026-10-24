// Starting with the computer: what the shell asks of the operating system, and
// how a launch by the login item is recognised. The OS calls are stood in for;
// what is ours, and checked here, is which call is made for which platform,
// that a development run touches nothing, and that a failure never throws.
import { createRequire } from 'node:module';
import { mkdtempSync, existsSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

const require = createRequire(import.meta.url);
const login = require('../electron/login.cjs');

const fakeApp = (over = {}) => ({
  isPackaged: true,
  setLoginItemSettings: vi.fn(),
  getLoginItemSettings: vi.fn(() => ({})),
  getPath: () => '/Applications/Lazy to Text.app/Contents/MacOS/Lazy to Text',
  ...over,
});

const dirs = [];
function scratch() {
  const dir = mkdtempSync(join(tmpdir(), 'l2t-login-'));
  dirs.push(dir);
  return dir;
}
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop(), { recursive: true, force: true });
});

describe('start at login on macOS and Windows', () => {
  it('registers a hidden start on macOS', () => {
    const app = fakeApp();
    const done = login.applyStartAtLogin(true, { app, platform: 'darwin', env: {} });
    expect(done).toMatchObject({ applied: true });
    expect(app.setLoginItemSettings).toHaveBeenCalledWith(
      expect.objectContaining({ openAtLogin: true, openAsHidden: true, args: ['--hidden'] }),
    );
  });

  it('removes the login item when switched off', () => {
    const app = fakeApp();
    login.applyStartAtLogin(false, { app, platform: 'darwin', env: {} });
    expect(app.setLoginItemSettings).toHaveBeenCalledWith(expect.objectContaining({ openAtLogin: false }));
  });

  it('names the portable executable on Windows, not the folder it unpacks into', () => {
    const app = fakeApp();
    login.applyStartAtLogin(true, {
      app, platform: 'win32', env: { PORTABLE_EXECUTABLE_FILE: 'C:\\Tools\\LazyToText-portable.exe' },
    });
    expect(app.setLoginItemSettings).toHaveBeenCalledWith({
      openAtLogin: true, args: ['--hidden'], path: 'C:\\Tools\\LazyToText-portable.exe',
    });
  });

  it('removes the Windows entry by the same path and arguments it was made with', () => {
    const app = fakeApp({ getPath: () => 'C:\\Apps\\Lazy to Text.exe' });
    login.applyStartAtLogin(false, { app, platform: 'win32', env: {} });
    expect(app.setLoginItemSettings).toHaveBeenCalledWith({
      openAtLogin: false, path: 'C:\\Apps\\Lazy to Text.exe', args: ['--hidden'],
    });
  });

  it('leaves the system alone in a development run', () => {
    const app = fakeApp({ isPackaged: false });
    expect(login.applyStartAtLogin(true, { app, platform: 'darwin', env: {} })).toEqual({ applied: false, reason: 'unpackaged' });
    expect(app.setLoginItemSettings).not.toHaveBeenCalled();
  });

  it('reports a failure instead of throwing it', () => {
    const app = fakeApp({ setLoginItemSettings: vi.fn(() => { throw new Error('denied'); }) });
    const log = vi.fn();
    expect(login.applyStartAtLogin(true, { app, platform: 'win32', env: {}, log })).toMatchObject({ applied: false, reason: 'error' });
    expect(log).toHaveBeenCalledWith(expect.stringContaining('denied'));
  });

  it('treats anything but true as off', () => {
    const app = fakeApp();
    login.applyStartAtLogin('yes', { app, platform: 'darwin', env: {} });
    expect(app.setLoginItemSettings).toHaveBeenCalledWith(expect.objectContaining({ openAtLogin: false }));
  });
});

describe('start at login on Linux', () => {
  const env = (dir, extra = {}) => ({ XDG_CONFIG_HOME: dir, ...extra });

  it('writes an XDG autostart entry that starts hidden, and removes it again', () => {
    const dir = scratch();
    const app = fakeApp({ getPath: () => '/opt/Lazy to Text/lazy-to-text' });
    const on = login.applyStartAtLogin(true, { app, platform: 'linux', env: env(dir) });
    const file = join(dir, 'autostart', 'lazy-to-text.desktop');
    expect(on).toMatchObject({ applied: true, file });
    const text = readFileSync(file, 'utf8');
    expect(text).toContain('[Desktop Entry]');
    expect(text).toContain('Type=Application');
    expect(text).toContain('Exec="/opt/Lazy to Text/lazy-to-text" --hidden');
    expect(app.setLoginItemSettings).not.toHaveBeenCalled();

    login.applyStartAtLogin(false, { app, platform: 'linux', env: env(dir) });
    expect(existsSync(file)).toBe(false);
    // Off when it was never on is not an error.
    expect(login.applyStartAtLogin(false, { app, platform: 'linux', env: env(dir) })).toMatchObject({ applied: true });
  });

  it('starts an AppImage by the image, not by the folder it is mounted in', () => {
    const dir = scratch();
    login.applyStartAtLogin(true, {
      app: fakeApp(), platform: 'linux', env: env(dir, { APPIMAGE: '/home/me/LazyToText.AppImage' }),
    });
    expect(readFileSync(join(dir, 'autostart', 'lazy-to-text.desktop'), 'utf8')).toContain('Exec="/home/me/LazyToText.AppImage" --hidden');
  });

  it('quotes what the Desktop Entry format reserves', () => {
    expect(login.execLine('/odd "dir"/app%1')).toBe('"/odd \\"dir\\"/app%%1" --hidden');
  });
});

describe('a launch by the login item', () => {
  it('is recognised by the flag on every platform', () => {
    for (const platform of ['win32', 'linux', 'darwin']) {
      expect(login.startedHidden({ argv: ['x', 'y', '--hidden'], app: fakeApp(), platform })).toBe(true);
    }
    expect(login.startedHidden({ argv: ['x', 'y'], app: fakeApp(), platform: 'win32' })).toBe(false);
  });

  it('is read from the system on macOS, which passes no arguments to a login item', () => {
    const app = fakeApp({ getLoginItemSettings: () => ({ wasOpenedAtLogin: true }) });
    expect(login.startedHidden({ argv: ['x'], app, platform: 'darwin' })).toBe(true);
    expect(login.startedHidden({ argv: ['x'], app, platform: 'linux' })).toBe(false);
    const broken = fakeApp({ getLoginItemSettings: () => { throw new Error('no'); } });
    expect(login.startedHidden({ argv: ['x'], app: broken, platform: 'darwin' })).toBe(false);
  });
});
