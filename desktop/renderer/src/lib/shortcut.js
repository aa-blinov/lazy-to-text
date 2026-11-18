// Platform-wide shortcuts, matched by the physical key (`code`), not the
// character (`key`): with a non-Latin keyboard layout active, such as
// Russian on Windows, the same physical key reports a different character —
// "а" for the F key, "б" for the comma — so a `key === 'f'` or a
// `key === ','` check never fires there. `key` is the fallback for events
// that carry no `code`.

function withPlatformModifier(event) {
  // CmdOrCtrl, as the native menu accelerators spell it: on macOS either
  // modifier is accepted rather than Cmd alone, and on Windows the OS takes
  // most Win-key chords before the renderer sees them. This matches the
  // digit jump below in App.svelte, which has always taken either.
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
}

// The Find shortcut (Ctrl+F, or Cmd+F on macOS).
export function isFindShortcut(event) {
  if (!withPlatformModifier(event)) return false;
  if (event.code) return event.code === 'KeyF';
  return typeof event.key === 'string' && event.key.toLowerCase() === 'f';
}

// The Settings shortcut (Ctrl+,, or Cmd+, on macOS), as in the native menu.
export function isSettingsShortcut(event) {
  if (!withPlatformModifier(event)) return false;
  if (event.code) return event.code === 'Comma';
  return event.key === ',';
}

// The index of the number key that was pressed (1-based), for the
// Cmd/Ctrl+1..9 screen switcher. The number row reports symbols instead
// of digits on layouts like French AZERTY, so `Number(event.key)` is
// not the way; `event.code` names the physical key. `key` is the
// fallback for events that carry no `code`.
export function digitIndex(event) {
  if (event.code) {
    return /^Digit[1-9]$/.test(event.code) ? Number(event.code.slice(5)) : null;
  }
  const n = Number(event.key);
  return n >= 1 && n <= 9 ? n : null;
}
