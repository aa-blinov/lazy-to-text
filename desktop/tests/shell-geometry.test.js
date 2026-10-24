// Where the main window and the capsule go, with no screen involved.
import { createRequire } from 'node:module';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const { computeBounds, capsuleBounds, sanitizeSaved } = require('../electron/geometry.cjs');

const display = (x, y, width, height) => ({ workArea: { x, y, width, height } });
const primary = display(0, 25, 1920, 1055);
const second = display(1920, 0, 1920, 1080);
const defaults = { width: 1120, height: 760 };
const min = { width: 900, height: 600 };
const saved = (x, y, width = 1000, height = 650, maximized = false) => ({ x, y, width, height, maximized });

function bounds(savedState, displays = [primary, second], main = primary) {
  return computeBounds({ saved: savedState, displays, primary: main, defaults, min });
}

describe('the main window bounds', () => {
  it('restores a saved rectangle in place when its display is still there', () => {
    expect(bounds(saved(50, 80))).toMatchObject({ x: 50, y: 80, width: 1000, height: 650 });
    expect(bounds(saved(2000, 100))).toMatchObject({ x: 2000, y: 100, width: 1000, height: 650 });
  });

  it('keeps the size and centres on the primary display when the saved display is gone', () => {
    const result = bounds(saved(2400, 100), [primary]);
    expect(result.width).toBe(1000);
    expect(result.height).toBe(650);
    expect(result.x).toBe(Math.round((1920 - 1000) / 2));
    expect(result.y).toBe(Math.round(25 + (1055 - 650) / 2));
  });

  it('treats a window mostly off every display as gone', () => {
    const result = bounds(saved(1900, 100, 1000, 650), [primary]);
    expect(result.x).toBe(Math.round((1920 - 1000) / 2));
  });

  it('treats a title bar above the work area as unreachable', () => {
    expect(bounds(saved(100, -400), [primary]).y).toBe(Math.round(25 + (1055 - 650) / 2));
  });

  it('never opens taller than a short work area, as on a 1366 x 768 laptop', () => {
    const laptop = display(0, 0, 1366, 728);
    const result = bounds(null, [laptop], laptop);
    expect(result.height).toBeLessThanOrEqual(728);
    expect(result.width).toBeLessThanOrEqual(1366);
    expect(result.y).toBeGreaterThanOrEqual(0);
    expect(result.y + result.height).toBeLessThanOrEqual(728);
  });

  it('clamps a saved size that is larger than the display it returns to', () => {
    const small = display(0, 0, 1280, 700);
    const result = bounds(saved(0, 0, 3000, 2000), [small], small);
    expect(result.width).toBeLessThanOrEqual(1280);
    expect(result.height).toBeLessThanOrEqual(700);
  });

  it('is centred at the default size with nothing saved', () => {
    const result = bounds(null);
    expect(result).toMatchObject({ width: 1120, height: 760, x: 400, y: Math.round(25 + (1055 - 760) / 2) });
    expect(result.maximized).toBe(false);
  });

  it('remembers that it was maximised, and ignores a state file that is junk', () => {
    expect(bounds(saved(50, 80, 1000, 650, true)).maximized).toBe(true);
    for (const junk of ['x', 7, [], { x: 'a', y: 1, width: 1, height: 1 }, { x: 1, y: 1, width: NaN, height: 600 },
      { x: 1, y: 1, width: 10, height: 10 }, { x: 1, y: 1, width: 99999, height: 600 }]) {
      expect(sanitizeSaved(junk)).toBeNull();
      expect(bounds(junk)).toMatchObject({ width: 1120, height: 760 });
    }
  });
});

describe('the capsule bounds', () => {
  it('sits at the bottom centre of the work area, inside it', () => {
    const area = { x: 1920, y: 0, width: 1920, height: 1055 };
    const box = capsuleBounds(area, { width: 520, height: 96 });
    expect(box.x).toBe(1920 + (1920 - 520) / 2);
    expect(box.y + box.height).toBeLessThanOrEqual(area.y + area.height);
    expect(box.x).toBeGreaterThanOrEqual(area.x);
  });

  it('never exceeds a narrow display', () => {
    const area = { x: 0, y: 0, width: 400, height: 300 };
    const box = capsuleBounds(area, { width: 520, height: 96 });
    expect(box.width).toBe(400);
    expect(box.x).toBe(0);
  });
});
