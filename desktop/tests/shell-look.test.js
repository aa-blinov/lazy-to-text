// The look the shell paints before the renderer is up: the choice survives a
// restart, and the table of colours is the kit's.
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { themes } from '../node_modules/@monos/ui/src/themes.js';

const look = createRequire(import.meta.url)('../electron/look.cjs');

describe('the shell palette table', () => {
  it('equals the kit for every palette, in both modes, for each role the shell paints', () => {
    expect(Object.keys(look.PALETTES)).toEqual(Object.keys(themes));
    for (const [name, table] of Object.entries(look.PALETTES)) {
      for (const mode of ['light', 'dark']) {
        for (const [role, value] of Object.entries(table[mode])) {
          expect(value, `${name} ${mode} ${role}`).toBe(themes[name][mode][role]);
        }
      }
    }
  });
});

describe('colours', () => {
  it('follows the system only for the system choice', () => {
    expect(look.colours({ theme: 'system', palette: 'nord' }, true).bg).toBe(themes.nord.dark.bg);
    expect(look.colours({ theme: 'system', palette: 'nord' }, false).bg).toBe(themes.nord.light.bg);
    expect(look.colours({ theme: 'light', palette: 'nord' }, true).bg).toBe(themes.nord.light.bg);
    expect(look.colours({ theme: 'dark', palette: 'nord' }, false).bg).toBe(themes.nord.dark.bg);
  });

  it('falls back to Gruvbox for an unknown palette and to the system for an unknown mode', () => {
    expect(look.normalise({ theme: 'purple', palette: '__proto__' })).toEqual({ theme: 'system', palette: 'gruvbox' });
    expect(look.normalise(null)).toEqual({ theme: 'system', palette: 'gruvbox' });
  });
});

describe('the saved look', () => {
  it('round-trips and reads as the defaults when the file is missing or broken', () => {
    const dir = mkdtempSync(join(tmpdir(), 'l2t-look-'));
    const file = join(dir, 'look.json');
    expect(look.load(file)).toEqual(look.DEFAULT);
    look.save(file, { theme: 'dark', palette: 'dracula' });
    expect(look.load(file)).toEqual({ theme: 'dark', palette: 'dracula' });
    writeFileSync(file, '{nope');
    expect(look.load(file)).toEqual(look.DEFAULT);
    expect(() => look.save(join(dir, 'missing', 'look.json'), { theme: 'dark' })).not.toThrow();
  });
});

describe('the start-up page', () => {
  async function open(state) {
    const { readFileSync: read } = await import('node:fs');
    document.documentElement.removeAttribute('style');
    document.body.innerHTML = read(join(import.meta.dirname, '..', 'electron', 'splash.html'), 'utf8')
      .replace(/[\s\S]*<body>/, '').replace(/<script[\s\S]*$/, '');
    let onColours = null;
    window.l2tSplash = { retry() {}, quit() {}, onState() {}, onColours: (cb) => { onColours = cb; } };
    history.replaceState(null, '', '#' + encodeURIComponent(JSON.stringify(state)));
    window.eval(read(join(import.meta.dirname, '..', 'electron', 'splash.js'), 'utf8'));
    return onColours;
  }

  const colours = look.colours({ theme: 'dark', palette: 'nord' });
  const wire = { bg: colours.bg, panel: colours.surface, ink: colours.ink, muted: colours.inkSoft, line: colours.line, accent: colours.accent, danger: colours.danger, dark: true };

  it('wears the palette the shell hands it, from the first state and on a later change', async () => {
    const onColours = await open({ mode: 'loading', title: 'Starting', colours: wire });
    const style = document.documentElement.style;
    expect(style.getPropertyValue('--bg')).toBe(themes.nord.dark.bg);
    expect(style.getPropertyValue('--accent')).toBe(themes.nord.dark.accent);
    onColours({ ...wire, bg: themes.gruvbox.light.bg, dark: false });
    expect(style.getPropertyValue('--bg')).toBe(themes.gruvbox.light.bg);
    expect(style.colorScheme).toBe('light');
  });

  it('ignores a colour that is not a hex value', async () => {
    await open({ mode: 'loading', title: 'x', colours: { ...wire, bg: 'url(http://evil)' } });
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe('');
  });
});
