// The start and stop sounds: the list the runtime offers, the current choice,
// and a file of the person's own. Kept outside the component, like the other
// settings state, so a test reads the same thing the screen does.

import { writable } from 'svelte/store';
import { call } from './rpc.js';

export const ADD = '__add__';

export const soundList = writable({ presets: [], custom: [], start: '', stop: '' });

export async function loadSounds() {
  const list = await call('sounds.list');
  soundList.set(list);
  return list;
}

/** Choose the sound of one cue ('start' or 'stop'); the runtime applies it at once. */
export async function chooseSound(slot, value) {
  const result = await call('sounds.set', { slot, value });
  soundList.update((list) => ({ ...list, [slot]: result.value }));
  return result;
}

export function previewSound(value) {
  return call('sounds.preview', { value });
}

/** Copy a WAV file into the app and list it. Returns `{ value, name, seconds }`. */
export async function addSound(path) {
  const added = await call('sounds.add', { path });
  await loadSounds();
  return added;
}

export async function removeSound(value) {
  const result = await call('sounds.remove', { value });
  await loadSounds();
  return result;
}

/** The options of the picker: Off, the shipped sounds, the person's own, and the way to add one. */
export function soundOptions(list, tr) {
  return [
    { value: '', label: tr('Off') },
    ...list.presets.map((p) => ({ value: p.value, label: tr(p.label) })),
    ...list.custom.map((c) => ({ value: c.value, label: c.name })),
    { value: ADD, label: tr('Choose a file…') },
  ];
}

export function isCustom(list, value) {
  return list.custom.some((c) => c.value === value);
}
