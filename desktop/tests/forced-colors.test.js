// Forced colours (Windows contrast themes). A browser test cannot flip the
// operating system's switch, so this holds the stylesheet to what the design
// says (DESIGN.md, "Forced colours" and the Defer Rule): inside the media
// query only system colours are named, and every state that is told by a fill
// alone has a rule. Chromium's emulation of the media feature was the other
// half of the check, done by hand (parity-audit.md, M4).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(import.meta.dirname, '..', 'renderer', 'src', 'app.css'), 'utf8');

function block() {
  const start = css.indexOf('@media (forced-colors: active)');
  expect(start).toBeGreaterThan(-1);
  let depth = 0;
  for (let i = css.indexOf('{', start); i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(start, i + 1);
    }
  }
  throw new Error('unterminated forced-colors block');
}

const SYSTEM = new Set([
  'canvas', 'canvastext', 'linktext', 'visitedtext', 'activetext', 'buttonface', 'buttontext', 'buttonborder',
  'field', 'fieldtext', 'highlight', 'highlighttext', 'selecteditem', 'selecteditemtext', 'mark', 'marktext',
  'graytext', 'transparent', 'inherit', 'currentcolor', 'none',
]);

describe('the forced-colours rules', () => {
  const rules = block();

  it('name system colours only, never a colour of ours', () => {
    const values = [...rules.matchAll(/(?:^|[;{\s])(?:color|background-color|background|border-color|outline-color|border|outline)\s*:\s*([^;}]+)/g)]
      .flatMap((m) => m[1].split(/\s+/));
    const colourWords = values.filter((v) => /^[a-z]+$/i.test(v) && !['solid', 'dashed', 'none', 'transparent'].includes(v.toLowerCase()));
    expect(colourWords.length).toBeGreaterThan(10);
    const foreign = colourWords.filter((v) => !SYSTEM.has(v.toLowerCase()));
    expect(foreign).toEqual([]);
    expect(rules).not.toMatch(/var\(--|#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
  });

  it('keep a focus ring that the system promises is visible', () => {
    expect(rules).toMatch(/:focus-visible\s*{[^}]*outline:\s*2px solid Highlight/);
  });

  it('give every state that a fill alone tells a rule of its own', () => {
    for (const selector of [
      "button[role='switch'][aria-checked='true']",
      "[aria-current='page']",
      "button[aria-pressed='true']",
      "[role='progressbar']",
      "[role='meter']",
      "div[class*='border-ink-soft']",
      "[class*='rounded-full'][aria-hidden='true']",
    ]) {
      expect(rules, selector).toContain(selector);
    }
  });

  it('frame the kit\'s unframed buttons, and grey the disabled ones', () => {
    expect(rules).toMatch(/button\[class\*='tracking-widest'\][^{]*{\s*border:\s*1px solid ButtonText/);
    expect(rules).toMatch(/button:disabled[^{]*{[^}]*GrayText/);
  });

  it('keep the capsule window clear and draw the capsule itself in the system colours', () => {
    expect(rules).toMatch(/html:has\(\.capsule-stage\)[^{]*{[^}]*background:\s*transparent/);
    expect(rules).toMatch(/\.capsule-stage \[role='status'\]\s*{[^}]*background-color:\s*Canvas/);
    const overlay = readFileSync(join(import.meta.dirname, '..', 'renderer', 'src', 'Overlay.svelte'), 'utf8');
    expect(overlay).toContain('capsule-stage');
    expect(overlay).toContain('data-testid="dot"');
  });
});
