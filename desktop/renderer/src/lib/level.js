// The input meter reads on a decibel scale, as every audio meter does. The
// runtime sends the block's peak as a 0..1 amplitude; speech at a comfortable
// distance peaks around 0.03 to 0.3, which on a linear bar lights one or two
// segments of twelve and never looks alive. In decibels the same speech fills
// the bar from the middle up, and a room's hiss stays below the first segment.

/** Quietest level the bar shows, in dB below full scale. */
export const FLOOR_DB = -54;
/** From here the bar turns amber, then red: loud, then close to clipping. */
export const LOUD_DB = -12;
export const CLIP_DB = -3;

/** dB below full scale for a 0..1 amplitude; `-Infinity` for silence. */
export function toDb(amplitude) {
  const a = Math.max(0, Math.min(1, Number(amplitude) || 0));
  return a > 0 ? 20 * Math.log10(a) : -Infinity;
}

/** Where the amplitude sits on the bar, 0..1. */
export function position(amplitude, floor = FLOOR_DB) {
  const db = toDb(amplitude);
  if (!Number.isFinite(db)) return 0;
  return Math.max(0, Math.min(1, (db - floor) / -floor));
}

/** The dB value at the top edge of segment `index` of `count`. */
export function segmentDb(index, count, floor = FLOOR_DB) {
  return floor + ((index + 1) / count) * -floor;
}

/** Which fill a segment takes, by where its top edge sits in dB. */
export function toneAt(index, count, floor = FLOOR_DB) {
  const db = segmentDb(index, count, floor);
  if (db <= LOUD_DB) return 'ok';
  if (db <= CLIP_DB) return 'loud';
  return 'clip';
}
