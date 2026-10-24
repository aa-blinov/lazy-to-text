// Shared state of the interface: one readable store per server event, plus
// the snapshot taken at start. Views read these and call `call(...)`;
// none of them opens its own subscription for state that several screens
// share.

import { writable, derived, get } from 'svelte/store';
import { call, subscribe } from './rpc.js';

export const snapshot = writable(null);
export const state = writable('idle');
export const engine = writable({ provider: null, model: '', alias: '' });
export const resources = writable({});
export const progress = writable({ current: 0, total: 0, desc: '', elapsed: 0 });
export const level = writable(0);
export const connected = writable(false);
export const startError = writable('');

export const config = derived(snapshot, ($s) => $s?.config ?? {});

let started = false;

export async function start() {
  if (started) return;
  started = true;
  subscribe('state', (d) => state.set(d.state));
  subscribe('engine', (d) => engine.set(d));
  subscribe('resources', (d) => resources.set(d));
  subscribe('progress', (d) => progress.set(d));
  subscribe('level', (d) => level.set(d.level ?? 0));
  subscribe('__disconnected', () => connected.set(false));
  try {
    snapshot.set(await call('app.snapshot'));
    connected.set(true);
  } catch (err) {
    startError.set(err.message);
    throw err;
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
