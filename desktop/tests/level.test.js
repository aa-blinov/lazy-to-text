import { describe, expect, it } from 'vitest';
import { FLOOR_DB, position, segmentDb, toDb, toneAt } from '../renderer/src/lib/level.js';

describe('the input level scale', () => {
  it('reads amplitude in decibels below full scale', () => {
    expect(toDb(1)).toBeCloseTo(0, 5);
    expect(toDb(0.1)).toBeCloseTo(-20, 5);
    expect(toDb(0)).toBe(-Infinity);
    expect(toDb('nonsense')).toBe(-Infinity);
  });

  it('puts ordinary speech well up the bar, where a linear scale lit one segment', () => {
    // A peak of 0.05 is -26 dB: more than half of the 54 dB range.
    expect(position(0.05)).toBeGreaterThan(0.5);
    expect(Math.round(position(0.05) * 12)).toBeGreaterThanOrEqual(6);
    expect(Math.round(0.05 * 12)).toBe(1);
  });

  it('keeps a quiet room off the bar and a full-scale peak at the top', () => {
    expect(position(0)).toBe(0);
    expect(position(0.0005)).toBe(0);
    expect(position(1)).toBe(1);
    expect(position(2)).toBe(1);
    expect(FLOOR_DB).toBe(-54);
  });

  it('turns amber when loud and red close to clipping', () => {
    const tones = Array.from({ length: 12 }, (_, i) => toneAt(i, 12));
    expect(tones[0]).toBe('ok');
    expect(tones.at(-1)).toBe('clip');
    expect(tones).toContain('loud');
    expect(segmentDb(11, 12)).toBeCloseTo(0, 5);
    // Green never follows amber, and amber never follows red.
    const order = { ok: 0, loud: 1, clip: 2 };
    for (let i = 1; i < tones.length; i += 1) expect(order[tones[i]]).toBeGreaterThanOrEqual(order[tones[i - 1]]);
  });
});
