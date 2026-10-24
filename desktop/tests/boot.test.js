// @vitest-environment node
// public/boot.js runs before the first paint and gives <html> the palette and
// mode the user last had; src/lib/theme.js writes what it reads. Run here
// against stand-ins for the three globals it touches.
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const RENDERER = join(import.meta.dirname, '..', 'renderer');
const source = readFileSync(join(RENDERER, 'public', 'boot.js'), 'utf8');

function run({ store = {}, dark = false, throws = false } = {}) {
  const attrs = {};
  const style = {};
  const root = { setAttribute: (k, v) => (attrs[k] = v), style };
  const localStorage = {
    getItem: (k) => {
      if (throws) throw new Error('storage off');
      return store[k] ?? null;
    },
  };
  const matchMedia = () => ({ matches: dark });
  new Function('document', 'localStorage', 'matchMedia', source)({ documentElement: root }, localStorage, matchMedia);
  return { attrs, style };
}

describe('boot.js', () => {
  it('applies the stored palette and mode', () => {
    const { attrs } = run({ store: { 'l2t.look': JSON.stringify({ theme: 'dark', palette: 'nord' }) } });
    expect(attrs).toEqual({ 'data-theme': 'nord', 'data-mode': 'dark' });
  });

  it('follows the system for "system", and takes an explicit light over a dark system', () => {
    expect(run({ store: { 'l2t.look': JSON.stringify({ theme: 'system', palette: 'dracula' }) }, dark: true }).attrs['data-mode']).toBe('dark');
    expect(run({ store: { 'l2t.look': JSON.stringify({ theme: 'light', palette: 'dracula' }) }, dark: true }).attrs['data-mode']).toBe('light');
  });

  it('falls back to Gruvbox and the system mode on first launch, and on junk', () => {
    expect(run({ dark: true }).attrs).toEqual({ 'data-theme': 'gruvbox', 'data-mode': 'dark' });
    // Junk leaves the page's own defaults (Gruvbox, light) in place.
    expect(run({ store: { 'l2t.look': '{not json' } }).attrs).toEqual({});
    expect(run({ store: { 'l2t.look': JSON.stringify({ palette: 'neon' }) } }).attrs['data-theme']).toBe('gruvbox');
  });

  it('still follows the system mode when storage is unavailable', () => {
    expect(run({ throws: true, dark: true }).attrs).toEqual({ 'data-mode': 'dark' });
  });

  it('restores the text size within the bounds the app allows', () => {
    expect(run({ store: { 'l2t.scale': '1.5' } }).style.fontSize).toBe('150%');
    expect(run({ store: { 'l2t.scale': '9' } }).style.fontSize).toBeUndefined();
  });

  it('is loaded by every page before its module script, from its own file', () => {
    for (const page of ['index.html', 'overlay.html', 'popup.html']) {
      const html = readFileSync(join(RENDERER, page), 'utf8');
      const boot = html.indexOf('<script src="/boot.js"></script>');
      expect(boot, page).toBeGreaterThan(-1);
      expect(boot, page).toBeLessThan(html.indexOf('type="module"'));
    }
    expect(existsSync(join(RENDERER, 'public', 'boot.js'))).toBe(true);
  });
});
