'use strict';
// Where the main window opens. Pure functions, so the display cases (a
// screen that was unplugged, a laptop smaller than the default size) are
// tested without a screen.

const MIN_VISIBLE = { width: 120, height: 60 };

function overlap(a, b) {
  const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return { width: Math.max(0, w), height: Math.max(0, h) };
}

function finite(n) {
  return typeof n === 'number' && Number.isFinite(n);
}

/** What the window state file may hold; anything else is ignored. */
function sanitizeSaved(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const { x, y, width, height } = raw;
  if (![x, y, width, height].every(finite)) return null;
  if (width < 200 || height < 150 || width > 20000 || height > 20000) return null;
  return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height), maximized: raw.maximized === true };
}

function fit(size, min, area) {
  return {
    width: Math.max(Math.min(min.width, area.width), Math.min(size.width, area.width)),
    height: Math.max(Math.min(min.height, area.height), Math.min(size.height, area.height)),
  };
}

/**
 * The bounds for a new main window.
 *
 * With a saved rectangle that still shows enough of itself on some display's
 * work area, it is restored in place (its size clamped to that display).
 * Otherwise the size is kept and the window is centred on the primary
 * display. The default size never exceeds the work area, and the minimum
 * never does either: a 1366 x 768 laptop has a work area shorter than the
 * default height.
 */
function computeBounds({ saved, displays, primary, defaults, min }) {
  const areas = (displays && displays.length ? displays : [primary]).map((d) => d.workArea);
  const home = primary.workArea;
  const state = sanitizeSaved(saved);
  const wanted = state ? { width: state.width, height: state.height } : defaults;

  if (state) {
    for (const area of areas) {
      const seen = overlap(state, area);
      const titleReachable = state.y >= area.y - 1 && state.y <= area.y + area.height - MIN_VISIBLE.height;
      if (seen.width >= MIN_VISIBLE.width && seen.height >= MIN_VISIBLE.height && titleReachable) {
        const size = fit(wanted, min, area);
        const x = Math.min(Math.max(state.x, area.x), area.x + area.width - size.width);
        const y = Math.min(Math.max(state.y, area.y), area.y + area.height - size.height);
        return { x, y, ...size, maximized: state.maximized };
      }
    }
  }
  const size = fit(wanted, min, home);
  return {
    x: Math.round(home.x + (home.width - size.width) / 2),
    y: Math.round(home.y + (home.height - size.height) / 2),
    ...size,
    maximized: Boolean(state && state.maximized),
  };
}

/**
 * The capsule's bounds: the bottom-right corner of a display's work area,
 * inside it (the Qt capsule's place, spec 007 FR-007).
 *
 * The window is wider and taller than the capsule it holds, and the page
 * draws the capsule against the window's right edge with an 8 px gutter of
 * its own, so a 16 px visual margin on the right is 8 px of window margin
 * here; at the bottom the capsule already sits 20 px above the window's edge.
 */
function capsuleBounds(workArea, size, margin = { right: 8, bottom: 0 }) {
  const width = Math.min(size.width, workArea.width);
  const height = Math.min(size.height, workArea.height);
  const right = typeof margin === 'number' ? margin : margin.right;
  const bottom = typeof margin === 'number' ? margin : margin.bottom;
  return {
    x: Math.round(Math.max(workArea.x, workArea.x + workArea.width - width - right)),
    y: Math.round(Math.max(workArea.y, workArea.y + workArea.height - height - bottom)),
    width,
    height,
  };
}

module.exports = { computeBounds, sanitizeSaved, capsuleBounds, overlap };
