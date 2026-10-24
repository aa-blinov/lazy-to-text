// Turning key presses into the binding text the runtime validates
// ("ctrl+shift+a", "f8", "right_alt"), and binding text into key caps.
//
// Physical key codes are used, not the typed character: with Option held a
// Mac types a symbol, and a layout other than US would otherwise bind a
// letter nobody pressed. The text produced is only a proposal; the runtime
// applies the same validation rules as the Qt screen and says why it refuses
// one.

const MODIFIER_ORDER = ['ctrl', 'alt', 'shift', 'cmd'];

const MODIFIER_OF_CODE = {
  ControlLeft: 'ctrl', ControlRight: 'ctrl',
  AltLeft: 'alt', AltRight: 'alt',
  ShiftLeft: 'shift', ShiftRight: 'shift',
  MetaLeft: 'cmd', MetaRight: 'cmd',
  OSLeft: 'cmd', OSRight: 'cmd',
};

const NAMED = {
  Space: 'space', Enter: 'enter', NumpadEnter: 'enter', Tab: 'tab',
  Backspace: 'backspace', Delete: 'delete', Insert: 'insert',
  Home: 'home', End: 'end', PageUp: 'page_up', PageDown: 'page_down',
  ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
  Escape: 'esc',
};

export function isModifierCode(code) {
  return code in MODIFIER_OF_CODE;
}

/** The right-hand modifiers that work alone in push-to-talk, by platform. */
export function soloNameForCode(code, platform) {
  switch (code) {
    case 'ControlRight': return 'right_ctrl';
    case 'AltRight': return 'right_alt';
    case 'ShiftRight': return 'right_shift';
    case 'MetaRight':
    case 'OSRight':
      return platform === 'darwin' ? 'right_cmd' : platform === 'win32' ? 'right_win' : 'right_super';
    case 'ContextMenu': return platform === 'win32' ? 'right_menu' : null;
    default: return null;
  }
}

/** The name of the non-modifier key of an event, or null when it has none. */
export function keyName(event) {
  const code = event.code || '';
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^Numpad[0-9]$/.test(code)) return code.slice(6);
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code.toLowerCase();
  if (code in NAMED) return NAMED[code];
  // Anything else is passed on by its printed name so the refusal can name it.
  const printed = (event.key || '').toLowerCase();
  return printed && printed !== 'unidentified' ? printed : null;
}

export function heldModifiers(event) {
  const held = new Set();
  if (event.ctrlKey) held.add('ctrl');
  if (event.altKey) held.add('alt');
  if (event.shiftKey) held.add('shift');
  if (event.metaKey) held.add('cmd');
  return MODIFIER_ORDER.filter((m) => held.has(m));
}

/**
 * What one keydown means while a binding is being captured.
 *   { kind: 'cancel' }            Escape alone: give up
 *   { kind: 'clear' }             Backspace or Delete alone, when empty is allowed
 *   { kind: 'leave' }             Tab alone: let focus move on
 *   { kind: 'modifiers', mods }   a modifier went down; show it, wait
 *   { kind: 'solo', text }        a key that works alone in push-to-talk (Fn, Menu)
 *   { kind: 'combo', text }       the binding
 *   { kind: 'ignore' }
 */
export function interpretKeydown(event, { platform = 'linux', allowEmpty = false, allowSolo = false } = {}) {
  if (event.repeat) return { kind: 'ignore' };
  const code = event.code || '';
  const mods = heldModifiers(event);

  if (isModifierCode(code)) return { kind: 'modifiers', mods };
  if (event.key === 'Fn') {
    // Windows has no Fn binding at all; elsewhere it is a solo key.
    if (platform === 'win32') return { kind: 'ignore' };
    return allowSolo ? { kind: 'solo', text: 'fn' } : { kind: 'modifiers', mods };
  }

  const bare = mods.length === 0;
  if (bare && code === 'Escape') return { kind: 'cancel' };
  if (bare && code === 'Tab') return { kind: 'leave' };
  if (bare && allowEmpty && (code === 'Backspace' || code === 'Delete')) return { kind: 'clear' };

  if (allowSolo && bare) {
    const solo = soloNameForCode(code, platform);
    if (solo) return { kind: 'solo', text: solo };
  }

  const key = keyName(event);
  if (!key) return { kind: 'ignore' };
  return { kind: 'combo', text: [...mods, key].join('+') };
}

/**
 * A modifier released with nothing else pressed in between is the binding
 * itself in push-to-talk: right Cmd held and let go. Left-hand modifiers are
 * passed on as they are so the runtime can explain why they are refused.
 */
export function interpretKeyup(event, { platform = 'linux', allowSolo = false, sawOtherKey = false } = {}) {
  if (!allowSolo || sawOtherKey) return null;
  const code = event.code || '';
  if (!isModifierCode(code)) return null;
  return soloNameForCode(code, platform) ?? MODIFIER_OF_CODE[code];
}

const KEY_LABELS = {
  page_up: 'Page Up', page_down: 'Page Down', esc: 'Esc', up: 'Up', down: 'Down', left: 'Left',
  right: 'Right', fn: 'Fn', space: 'Space', enter: 'Enter', tab: 'Tab', backspace: 'Backspace',
  delete: 'Delete', insert: 'Insert', home: 'Home', end: 'End',
};

/** Key caps for a binding text: "ctrl+f8" -> ["Ctrl", "F8"]. */
export function bindingParts(text, platform = 'linux') {
  const raw = String(text || '').trim();
  if (!raw) return [];
  const mac = platform === 'darwin';
  const word = (part) => {
    const p = part.trim().toLowerCase();
    if (p === 'ctrl' || p === 'control') return 'Ctrl';
    if (p === 'shift') return 'Shift';
    if (p === 'alt' || p === 'option') return mac ? 'Option' : 'Alt';
    if (['cmd', 'command', 'win', 'windows', 'super'].includes(p)) return mac ? 'Cmd' : platform === 'win32' ? 'Win' : 'Super';
    if (p.startsWith('right_') || p.endsWith('_r')) {
      const base = p.startsWith('right_') ? p.slice(6) : p.slice(0, -2);
      return `Right ${word(base)}`;
    }
    if (/^f\d{1,2}$/.test(p)) return p.toUpperCase();
    if (p in KEY_LABELS) return KEY_LABELS[p];
    return p.length === 1 ? p.toUpperCase() : p;
  };
  return raw.split('+').map(word);
}

/** Fill the %1, %2 placeholders of a translated sentence. */
export function fmt(text, ...values) {
  let out = String(text);
  values.forEach((value, i) => {
    out = out.replaceAll(`%${i + 1}`, String(value));
  });
  return out;
}
