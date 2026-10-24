// Shared state of the interface: one readable store per server event, plus
// the snapshot taken at start. Views read these and call `call(...)`;
// none of them opens its own subscription for state that several screens
// share.

import { writable, derived, get } from 'svelte/store';
import { call, subscribe, reconnect, markDown } from './rpc.js';

export const snapshot = writable(null);
export const state = writable('idle');
export const engine = writable({ provider: null, model: '', alias: '' });
export const resources = writable({});
export const progress = writable({ current: 0, total: 0, desc: '', elapsed: 0 });
export const level = writable(0);
/** True once the first snapshot has been read. */
export const connected = writable(false);
export const startError = writable('');

/** The runtime stopped answering after the window was up. */
export const engineDown = writable(false);
export const restarting = writable(false);
export const restartError = writable('');
/**
 * Counts reconnections. The shell keys the open screen on it, so every
 * screen reads its data again from a runtime that may be a new process.
 */
export const epoch = writable(0);

export const config = derived(snapshot, ($s) => $s?.config ?? {});

/** A model is loaded when the engine reports the accelerator it runs on. */
export const modelLoaded = derived(engine, ($e) => Boolean($e?.provider));

let started = false;
let wired = false;
let logPath = '';

/** Where the runtime writes its log, kept for the moment it cannot be asked. */
export function lastLogPath() {
  return logPath;
}

function resetLive() {
  state.set('disconnected');
  engine.set({ provider: null, model: '', alias: '' });
  resources.set({});
  progress.set({ current: 0, total: 0, desc: '', elapsed: 0 });
  level.set(0);
}

function onDown() {
  restartError.set('');
  engineDown.set(true);
  resetLive();
}

async function onUp() {
  // The events sent while the link was out are gone, so everything the
  // screens show is read again, from a runtime that may be a new process.
  try {
    const next = await call('app.snapshot');
    snapshot.set(next);
    if (next?.log_path) logPath = next.log_path;
    if (get(state) === 'disconnected') state.set(next?.state || 'idle');
    engineDown.set(false);
    restartError.set('');
    epoch.update((n) => n + 1);
  } catch {
    // Answered /health but not the snapshot: still not usable. Keep waiting.
    markDown('snapshot');
  }
}

function wire() {
  if (wired) return;
  wired = true;
  subscribe('state', (d) => state.set(d.state));
  subscribe('engine', (d) => engine.set(d));
  subscribe('resources', (d) => resources.set(d));
  subscribe('progress', (d) => progress.set(d));
  subscribe('level', (d) => level.set(d.level ?? 0));
  // A setting written by a call (from this window, the capsule's sibling, or
  // another client) changes the theme, palette or language everywhere: the
  // capsule is a separate window and learns of it only here.
  subscribe('settings', () => {
    refresh().catch(() => {});
  });
  subscribe('__disconnected', onDown);
  subscribe('__connected', onUp);
  // The main process knows the runtime's exit before the stream does. These
  // are optional: a plain browser tab has no bridge, and an older shell has
  // only `onBackendExit`.
  const bridge = typeof window !== 'undefined' ? window.l2t : null;
  if (bridge?.backend?.onExit) bridge.backend.onExit(() => markDown('exit'));
  else if (bridge?.onBackendExit) bridge.onBackendExit(() => markDown('exit'));
  bridge?.backend?.onRestarted?.(() => {
    reconnect().catch(() => {});
  });
}

export async function start() {
  if (started) return;
  started = true;
  wire();
  try {
    const first = await call('app.snapshot');
    snapshot.set(first);
    if (first?.log_path) logPath = first.log_path;
    connected.set(true);
  } catch (err) {
    startError.set(err.message);
    started = false;
    throw err;
  }
}

/** Try the first connection again after it failed. */
export function retryStart() {
  startError.set('');
  return start();
}

/**
 * Restart the runtime when the shell can, then wait for it. In a plain
 * browser tab there is nothing to restart, so this only asks again.
 */
export async function restartEngine() {
  restartError.set('');
  restarting.set(true);
  try {
    const restart = typeof window !== 'undefined' ? window.l2t?.backend?.restart : null;
    if (typeof restart === 'function') await window.l2t.backend.restart();
    const ok = await reconnect();
    if (!ok) restartError.set('The engine did not come back. Try again.');
  } catch (err) {
    restartError.set(err?.message || 'The engine did not come back. Try again.');
  } finally {
    restarting.set(false);
  }
}

/** Re-read the snapshot, e.g. after a setting changed in the runtime. */
export async function refresh() {
  snapshot.set(await call('app.snapshot'));
}

/** Update one section/key of the cached config after a successful write. */
export function patchConfig(section, key, value) {
  snapshot.update((s) => {
    if (!s) return s;
    return {
      ...s,
      config: { ...s.config, [section]: { ...(s.config[section] ?? {}), [key]: value } },
    };
  });
}

export function currentConfig() {
  return get(config);
}

/** Test hook. */
export function _resetBackend() {
  started = false;
  wired = false;
  logPath = '';
  snapshot.set(null);
  state.set('idle');
  engine.set({ provider: null, model: '', alias: '' });
  connected.set(false);
  engineDown.set(false);
  restarting.set(false);
  restartError.set('');
  startError.set('');
  epoch.set(0);
}
