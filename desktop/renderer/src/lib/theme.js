// The kit's themes are attributes on <html>. The palette is the user's
// choice from config (`ui.palette`, Gruvbox by default, the kit's reference
// palette) and light / dark / system follows `ui.theme`.

export const PALETTES = ['gruvbox', 'github', 'dracula', 'nord', 'solarized', 'catppuccin'];

export function normalisePalette(value) {
  return PALETTES.includes(value) ? value : PALETTES[0];
}

// Text size is the root font size: the kit and the screens size type and
// most spacing in rem, so one number scales them together. The same bounds
// as the Qt interface (app/ui_prefs.py).
// What public/boot.js reads before the first paint of the next start.
function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage can be off; the next start then opens in the defaults.
  }
}

export function applyTextScale(scale = 1) {
  const n = Number(scale);
  const clamped = Number.isFinite(n) ? Math.min(1.75, Math.max(0.85, n)) : 1;
  document.documentElement.style.fontSize = clamped === 1 ? '' : `${clamped * 100}%`;
  remember('l2t.scale', String(clamped));
  return clamped;
}

const mql = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;

export function applyTheme(choice = 'system', palette = 'gruvbox') {
  const mode = choice === 'system' ? (mql?.matches ? 'dark' : 'light') : choice === 'dark' ? 'dark' : 'light';
  const root = document.documentElement;
  root.dataset.theme = palette;
  root.dataset.mode = mode;
  remember('l2t.look', JSON.stringify({ theme: choice, palette }));
  window.l2t?.setTheme?.(choice);
  return mode;
}

export function watchSystemTheme(cb) {
  mql?.addEventListener?.('change', cb);
  return () => mql?.removeEventListener?.('change', cb);
}
