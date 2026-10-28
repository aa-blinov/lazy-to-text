// The Settings screen's side of the runtime: what is stored, what the
// microphone test is doing, and which macOS permissions are missing.
// Kept outside the component so a test or another window reads the same
// state; Settings explicitly clears the temporary mic-test result on exit.

import { writable, get } from 'svelte/store';
import { call, subscribe } from './rpc.js';
import { refresh, patchConfig } from './backend.js';
import { loadSounds } from './sounds.js';

export const settings = writable(null);
export const permissions = writable(null);
export const micTest = writable({ phase: 'idle', level: 0 });
export const devices = writable({ devices: [], current: null, loaded: false });
let micTestSessionOpen = false;

export function resetMicTest() {
  micTestSessionOpen = false;
  micTest.set({ phase: 'idle', level: 0 });
}

// A mode leaves behind the bindings it does not use: toggle folds Stop into
// Start and push-to-talk idles Start and Stop. The form remembers the values
// so switching back finds what was there, for as long as the app runs.
export const remembered = { stop: null, cancel: null };

export async function loadSettings() {
  const value = await call('settings.get');
  settings.set(value);
  return value;
}

export async function saveValue(key, value) {
  const result = await call('settings.set', { key, value });
  const [section, name] = key.split('.');
  patchConfig(section, name, result.value);
  settings.update((s) => (s ? withValue(s, key, result.value) : s));
  return result;
}

function withValue(s, key, value) {
  const [section, name] = key.split('.');
  return { ...s, [section]: { ...(s[section] ?? {}), [name]: value } };
}

export async function validateHotkeys(draft) {
  const { errors } = await call('settings.validate_hotkeys', hotkeyParams(draft));
  return errors;
}

function hotkeyParams(draft) {
  return {
    mode: draft.mode,
    start: draft.start,
    stop: draft.stop,
    cancel: draft.cancel,
    push_to_talk_key: draft.ptt,
  };
}

export async function saveHotkeys(draft) {
  const result = await call('settings.set_hotkeys', hotkeyParams(draft));
  settings.set(result.settings);
  await refresh();
  return result;
}

export async function resetHotkeys() {
  const result = await call('settings.reset_hotkeys');
  settings.set(result.settings);
  remembered.stop = null;
  remembered.cancel = null;
  await refresh();
  return result;
}

/** `refresh` rebuilds the audio system's device list first: it is frozen at start, so a phone or headset connected since is not in it. */
export async function listDevices({ refresh = false } = {}) {
  const result = await call('devices.list', refresh ? { refresh: true } : {});
  devices.set({ ...result, loaded: true });
  return result;
}

/** Read the list again, but only for a screen that has shown it. */
export function refreshDevices() {
  if (!get(devices).loaded) return Promise.resolve(null);
  return listDevices().catch(() => null);
}

export async function selectDevice(index) {
  const result = await call('devices.select', { device: index });
  devices.update((d) => ({ ...d, current: result.device }));
  patchConfig('audio', 'device', index);
  return result;
}

export async function startMicTest() {
  // The running state is set here as well as by the event, so a second
  // click in the gap before the event arrives cannot start a second test.
  micTestSessionOpen = true;
  micTest.set({ phase: 'running', level: 0 });
  try {
    return await call('devices.test');
  } catch (err) {
    if (micTestSessionOpen) micTest.set({ phase: 'error', reason: err.message, level: 0 });
    throw err;
  }
}

export async function refreshPermissions() {
  const value = await call('permissions.refresh');
  permissions.set(value);
  return value;
}

export async function requestPermission(kind) {
  const result = await call('permissions.request', { kind });
  return result;
}

let watching = null;

/** Subscribe once to the events this screen cares about. */
export function watchSettingsEvents() {
  if (watching) return watching;
  const stops = [
    subscribe('mic_test', (d) => {
      if (micTestSessionOpen) {
        micTest.update((m) => ({ ...m, ...d, level: d.phase === 'running' ? 0 : m.level }));
      }
    }),
    subscribe('mic_level', (d) =>
      micTest.update((m) => (m.phase === 'running' ? { ...m, level: d.level ?? 0 } : m)),
    ),
    subscribe('permissions', (d) => permissions.set(d)),
    // Another client changed a setting: read again rather than overwrite it
    // with the next edit made on a stale page.
    subscribe('settings', (d) => {
      loadSettings().catch(() => {});
      // The microphone is its own list: `settings.get` does not carry it.
      if (!Array.isArray(d?.keys) || d.keys.includes('audio.device')) refreshDevices();
      // The start and end sounds are their own list too.
      if (!Array.isArray(d?.keys) || d.keys.some((k) => k.startsWith('audio_feedback.'))) loadSounds().catch(() => {});
    }),
    // Events sent while the link was out are gone, and a device can be
    // plugged or unplugged at any time: read the list again.
    subscribe('__connected', () => refreshDevices()),
  ];
  watching = () => {
    stops.forEach((stop) => stop());
    watching = null;
  };
  return watching;
}

export function currentSettings() {
  return get(settings);
}
