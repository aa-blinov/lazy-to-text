// The start and end sounds. They come as sets, each a pair made together (one
// family: a start that rises, an end that falls), so the two never sound like
// they belong to different places. A pair of the person's own files is the
// only way to mix. Kept outside the component, like the other settings state.

import { writable } from 'svelte/store';
import { call } from './rpc.js';

export const CUSTOM = 'custom';

export const soundList = writable({ sets: [], custom: [], start: '', stop: '', theme: '' });

export async function loadSounds() {
  const list = await call('sounds.list');
  soundList.set(list);
  return list;
}

/** Set both cues to one of the sets. */
export async function chooseSet(theme) {
  const result = await call('sounds.set_theme', { theme });
  soundList.update((list) => ({ ...list, start: result.start, stop: result.stop, theme: result.theme }));
  return result;
}

/** Set one cue ('start' or 'stop') to a file of the person's own that was added. */
export async function chooseFile(slot, value) {
  const result = await call('sounds.set', { slot, value });
  await loadSounds();
  return result;
}

export function previewSound(value) {
  return call('sounds.preview', { value });
}

/** Play the start sound, then its end sound, as they will be heard. */
export async function previewPair(list, wait = (ms) => new Promise((r) => setTimeout(r, ms))) {
  const first = await previewSound(list.start);
  await wait(((first?.seconds ?? 0) + 0.25) * 1000);
  await previewSound(list.stop);
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

/** The options of the picker: the sets, then the way to use files of one's own. */
export function setOptions(list, tr) {
  return [
    ...list.sets.map((s) => ({ value: s.id, label: tr(s.label) })),
    { value: CUSTOM, label: tr('Your own files') },
  ];
}

export function isOwn(list, value) {
  return list.custom.some((c) => c.value === value);
}

/** What to call the sound a cue is set to. */
export function soundName(list, value, tr) {
  if (!value) return tr('Off');
  const own = list.custom.find((c) => c.value === value);
  if (own) return own.name;
  const set = list.sets.find((s) => s.start === value || s.stop === value);
  return set ? tr(set.label) : value.split(/[\\/]/).pop();
}
