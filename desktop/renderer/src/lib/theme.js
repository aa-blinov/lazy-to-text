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
export function applyTextScale(scale = 1) {
  const n = Number(scale);
  const clamped = Number.isFinite(n) ? Math.min(1.75, Math.max(0.85, n)) : 1;
  document.documentElement.style.fontSize = clamped === 1 ? '' : `${clamped * 100}%`;
  return clamped;
}

const mql = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;

export function applyTheme(choice = 'system', palette = 'gruvbox') {
  const mode = choice === 'system' ? (mql?.matches ? 'dark' : 'light') : choice === 'dark' ? 'dark' : 'light';
  const root = document.documentElement;
  root.dataset.theme = palette;
  root.dataset.mode = mode;
  window.l2t?.setTheme?.(choice);
  return mode;
}

export function watchSystemTheme(cb) {
  mql?.addEventListener?.('change', cb);
  return () => mql?.removeEventListener?.('change', cb);
}
