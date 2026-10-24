// The renderer takes every colour, radius and font from @monos/ui. A literal
// in a screen is a value that will not follow the theme, so it is a failure
// here rather than a review comment.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = join(import.meta.dirname, '..', 'renderer', 'src') + '/';

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const sources = walk(ROOT).filter((f) => ['.svelte', '.js', '.css'].includes(extname(f)));

describe('renderer sources', () => {
  it('have sources to check', () => {
    expect(sources.length).toBeGreaterThan(5);
  });

  it('hold no literal colour', () => {
    const offenders = [];
    for (const file of sources) {
      const text = readFileSync(file, 'utf8');
      if (/#[0-9a-fA-F]{3,8}\b/.test(text.replace(/&#\d+;|href="#[^"]*"|url\(#[^)]*\)|#app\b|#[a-z-]+(?=[\s{,.:[>)])/g, ''))
        || /\brgba?\(|\bhsla?\(/.test(text)) {
        offenders.push(file.replace(ROOT, ''));
      }
    }
    expect(offenders).toEqual([]);
  });

  it('hold no emoji', () => {
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
    const offenders = sources.filter((f) => emoji.test(readFileSync(f, 'utf8'))).map((f) => f.replace(ROOT, ''));
    expect(offenders).toEqual([]);
  });

  it('render no HTML from data: no {@html} anywhere', () => {
    // Text from a history entry, a preset name or a model id is printed by
    // Svelte's own escaping; {@html} would turn any of it into markup.
    const offenders = sources.filter((f) => /\{@html\b/.test(readFileSync(f, 'utf8'))).map((f) => f.replace(ROOT, ''));
    expect(offenders).toEqual([]);
  });

  it('use no eval, no Function constructor and no inline event handler string', () => {
    const offenders = sources
      .filter((f) => /\beval\s*\(|new Function\s*\(|\bsetTimeout\(\s*['"`]|\bsetInterval\(\s*['"`]/.test(readFileSync(f, 'utf8')))
      .map((f) => f.replace(ROOT, ''));
    expect(offenders).toEqual([]);
  });

  it('have a Russian entry for every literal string passed to $t or tr', () => {
    const table = {};
    for (const name of readdirSync(join(ROOT, 'i18n')).filter((f) => f.startsWith('ru') && f.endsWith('.json'))) {
      Object.assign(table, JSON.parse(readFileSync(join(ROOT, 'i18n', name), 'utf8')));
    }
    const missing = [];
    for (const file of sources.filter((f) => /\.(svelte|js)$/.test(f))) {
      const text = readFileSync(file, 'utf8');
      for (const m of text.matchAll(/(?:\$t|\btr)\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g)) {
        const key = (m[1] ?? m[2]).replace(/\\'/g, "'");
        if (!(key in table)) missing.push(`${key}  <- ${file.replace(ROOT, '')}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('keep every Russian catalogue a flat string table', () => {
    const files = readdirSync(join(ROOT, 'i18n')).filter((f) => f.startsWith('ru') && f.endsWith('.json'));
    for (const name of files) {
      const table = JSON.parse(readFileSync(join(ROOT, 'i18n', name), 'utf8'));
      for (const [k, v] of Object.entries(table)) {
        expect(typeof k).toBe('string');
        expect(typeof v).toBe('string');
      }
    }
  });
});
