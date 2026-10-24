// What counts as one of the app's own pages, and what the main process says in each language.
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const guard = require('../electron/guard.cjs');
const strings = require('../electron/strings.cjs');
const env = require('../electron/env.cjs');

describe('the page allow-list', () => {
  it('knows a packaged page by scheme, host and file, and nothing else', () => {
    guard.configure({ dev: false });
    for (const page of ['index.html', 'overlay.html', 'popup.html']) {
      expect(guard.isRendererUrl(`l2t-app://app/${page}`)).toBe(true);
    }
    for (const url of ['file:///tmp/evil.html', 'l2t-app://app/splash.html', 'l2t-app://evil/index.html', 'l2t-app://app/other.html',
      'l2t-app://app/assets/x.js', 'http://127.0.0.1:5173/index.html', 'https://l2t-app.example/index.html', 'not a url', '', null, undefined]) {
      expect(guard.isRendererUrl(url), String(url)).toBe(false);
    }
  });

  it('allows exactly the Vite origin in development, not a port that starts with it', () => {
    guard.configure({ dev: true });
    expect(guard.isRendererUrl('http://127.0.0.1:5173/index.html')).toBe(true);
    expect(guard.isRendererUrl('http://127.0.0.1:51730/index.html')).toBe(false);
    expect(guard.isRendererUrl('http://127.0.0.1:5173.evil.test/index.html')).toBe(false);
    expect(guard.isRendererUrl('file:///tmp/evil.html')).toBe(false);
    expect(guard.isRendererUrl('l2t-app://app/index.html')).toBe(false);
    guard.configure({ dev: false });
  });

  it('knows the start-up page by its own address only, and the two sets do not overlap', () => {
    guard.configure({ dev: false });
    expect(guard.isSplashUrl(guard.splashUrl())).toBe(true);
    expect(guard.isSplashUrl(guard.splashUrl('%7B%7D'))).toBe(true);
    for (const url of ['file:///tmp/evil.html', 'l2t-app://app/index.html', 'l2t-app://evil/splash.html',
      'l2t-app://app/splash.js', 'https://example.com/splash.html', 'junk']) {
      expect(guard.isSplashUrl(url), url).toBe(false);
    }
    expect(guard.isRendererUrl(guard.splashUrl())).toBe(false);
    expect([...guard.SPLASH_FILES].sort()).toEqual(['splash.html', 'splash.js']);
  });

  it('serves nothing from outside the renderer folder', () => {
    const root = '/app/dist-renderer';
    expect(guard.resolveInside(root, '/index.html')).toBe('/app/dist-renderer/index.html');
    expect(guard.resolveInside(root, '/assets/a.js')).toBe('/app/dist-renderer/assets/a.js');
    for (const bad of ['/../secret', '/..%2f..%2fsecret', '/assets/../../x', '/%00', '/%E0%A4%A']) {
      expect(guard.resolveInside(root, bad), bad).toBeNull();
    }
  });
});

describe('the main process strings', () => {
  it('choose Russian for a Russian setting or locale and English otherwise', () => {
    expect(strings.normalise('ru')).toBe('ru');
    expect(strings.normalise('ru-RU')).toBe('ru');
    expect(strings.normalise('ru_RU')).toBe('ru');
    for (const other of ['en', 'en-US', 'de', '', undefined, null, 'rum']) expect(strings.normalise(other)).toBe('en');
  });

  it('have every key in both languages, the tray tips included', () => {
    const shape = (value) => (value && typeof value === 'object'
      ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shape(v)])) : typeof value);
    expect(shape(strings.STRINGS.ru)).toEqual(shape(strings.STRINGS.en));
    for (const state of ['idle', 'recording', 'processing', 'model_loading', 'stopped']) {
      expect(strings.STRINGS.ru.tip[state]).toBeTruthy();
      expect(strings.STRINGS.ru.tip[state]).not.toBe(strings.STRINGS.en.tip[state]);
    }
  });

  it('fill a placeholder', () => {
    expect(strings.format(strings.STRINGS.en.startFailures.exited, { code: 1 })).toContain('exit code 1');
  });
});

describe('the developer and test hooks', () => {
  const packaged = { isPackaged: true };
  const unpackaged = { isPackaged: false };

  it('need the self-test flag as well as the variable', () => {
    const vars = { L2T_SCREENSHOT: '/tmp/x.png', L2T_SELFTEST_DROP: '/tmp/a.wav' };
    expect(env.hook('L2T_SCREENSHOT', vars, ['app'])).toBeUndefined();
    expect(env.hook('L2T_SCREENSHOT', vars, ['app', '--l2t-selftest'])).toBe('/tmp/x.png');
    expect(env.hook('L2T_SELFTEST_DROP', vars, ['app'])).toBeUndefined();
  });

  it('keep a packaged app from starting a different runtime or loading a local server', () => {
    const vars = { L2T_BACKEND_CMD: '/bin/sh -c evil', L2T_DEV: '1' };
    expect(env.backendOverride(packaged, vars, ['app'])).toBeUndefined();
    expect(env.backendOverride(packaged, vars, ['app', '--l2t-selftest'])).toBe('/bin/sh -c evil');
    expect(env.backendOverride(unpackaged, vars, ['app'])).toBe('/bin/sh -c evil');
    expect(env.dev(packaged, vars)).toBe(false);
    expect(env.dev(unpackaged, vars)).toBe(true);
    expect(env.dev(unpackaged, {})).toBe(false);
  });
});
