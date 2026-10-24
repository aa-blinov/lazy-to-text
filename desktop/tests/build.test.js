// @vitest-environment node
// The built pages have to work under the policy the window enforces:
// default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
// connect-src http://127.0.0.1:*; img-src 'self' data:; font-src 'self'.
// A dev server hides every breach (it adds its own hosts and inlines
// freely), so this builds the real thing and reads what came out.
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { build } from 'vite';

const DESKTOP = join(import.meta.dirname, '..');
let out;
const PAGES = ['index.html', 'overlay.html', 'popup.html'];

beforeAll(async () => {
  out = mkdtempSync(join(tmpdir(), 'l2t-build-'));
  await build({
    configFile: join(DESKTOP, 'vite.config.js'),
    root: join(DESKTOP, 'renderer'),
    logLevel: 'silent',
    build: { outDir: out, emptyOutDir: true },
  });
}, 120_000);

afterAll(() => rmSync(out, { recursive: true, force: true }));

const assets = (ext) => readdirSync(join(out, 'assets')).filter((f) => f.endsWith(ext)).map((f) => join(out, 'assets', f));

describe('the built renderer under the window policy', () => {
  it('carries the policy in every page, without the dev server hosts', () => {
    for (const page of PAGES) {
      const html = readFileSync(join(out, page), 'utf8');
      const policy = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)?.[1];
      expect(policy, page).toBeTruthy();
      expect(policy).toContain("default-src 'self'");
      expect(policy).toContain("script-src 'self'");
      expect(policy).toContain('connect-src http://127.0.0.1:*;');
      expect(policy).not.toContain('ws:');
      expect(policy).not.toContain("'unsafe-eval'");
    }
  });

  it('has no inline script and no inline event handler', () => {
    for (const page of PAGES) {
      const html = readFileSync(join(out, page), 'utf8');
      expect(html.match(/<script(?![^>]*\ssrc=)[^>]*>/g), page).toBeNull();
      expect(html, page).not.toMatch(/\son[a-z]+\s*=/i);
    }
  });

  it('loads no remote asset', () => {
    const files = [...PAGES.map((p) => join(out, p)), ...assets('.css')];
    for (const file of files) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/(?:src|href)="https?:|url\(\s*['"]?https?:/);
    }
  });

  it('inlines no font as a data: URI, which font-src \'self\' would block', () => {
    for (const file of assets('.css')) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/url\(\s*['"]?data:(?:font|application\/(?:font|octet))/);
    }
  });

  it('contains no eval and no Function constructor in its own or the kit\'s code', () => {
    for (const file of assets('.js')) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/\beval\s*\(|new Function\s*\(/);
    }
  });
});
