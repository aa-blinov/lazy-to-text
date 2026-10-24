// Small text helpers for strings the user typed or the runtime reported.

/**
 * Shorten a long string in the middle, so two names that share a start and
 * differ at the end (presets, model ids) stay distinguishable in a list.
 */
export function middleEllipsis(text, max = 44) {
  const s = String(text ?? '');
  if (s.length <= max) return s;
  const keep = max - 1;
  const head = Math.ceil(keep * 0.65);
  return `${s.slice(0, head)}…${s.slice(s.length - (keep - head))}`;
}

/** One line naming a row, for an accessible name: whitespace collapsed, cut short. */
export function subject(text, max = 40) {
  const s = String(text ?? '').split(/\s+/).filter(Boolean).join(' ');
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
