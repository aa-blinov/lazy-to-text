// State of the Transcribe screen, kept outside the component on purpose: a
// run outlives the screen (the user switches to Models and back while a long
// file is being read) and an operating-system open can arrive while another
// screen is showing. The component only draws what is here.

import { writable, get } from 'svelte/store';
import { call, subscribe } from './rpc.js';
import { tr, language } from './i18n.js';

const COURTESY_MS = 4000;

export const run = writable(emptyRun());
export const status = writable(null); // { text, kind: busy|done|warning|error, sticky }
export const dragging = writable(false);
export const extensions = writable([]);

function emptyRun() {
  return { phase: 'idle', path: null, size: null, text: '', baseline: '', elapsed: 0, seconds: 0 };
}

// ---- formatting (the same rules as the Qt view) -----------------------------

export function formatSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function formatElapsed(seconds) {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, '0')}`;
}

export function countWords(text) {
  return text.split(/\s+/).filter(Boolean).length;
}

/**
 * "1 word", "2 words", and the Russian few/many forms, from the catalogue
 * entries the Qt screens already use ("%1 word", "%1 words (few)", "%1 words").
 */
export function plural(n, one, few, many) {
  const lang = get(language);
  const rule = new Intl.PluralRules(lang).select(n);
  const source = rule === 'one' ? one : rule === 'few' && lang === 'ru' ? few : many;
  return tr(source).replace('%1', String(n));
}

export function baseName(path) {
  return (path || '').split(/[\\/]/).pop() || '';
}

export function describeFile(r) {
  const parts = [];
  if (r.size != null) parts.push(formatSize(r.size));
  // Frozen when the result lands. The Qt view kept measuring against the
  // clock, so the "processing time" grew with every edit of the text.
  if (r.seconds) parts.push(formatElapsed(r.seconds));
  const words = countWords(r.text);
  if (words) parts.push(plural(words, '%1 word', '%1 words (few)', '%1 words'));
  if (r.text !== r.baseline) parts.push(tr('Edited'));
  return parts.join('  ·  ');
}

// ---- status line ------------------------------------------------------------

let courtesyTimer = null;

export function setStatus(text, kind = 'info', { sticky = false } = {}) {
  clearTimeout(courtesyTimer);
  if (!text) {
    status.set(null);
    return;
  }
  status.set({ text, kind, sticky });
  if (!sticky) courtesyTimer = setTimeout(() => status.set(null), COURTESY_MS);
}

// ---- runs -------------------------------------------------------------------

function setBusy(path) {
  run.set({ ...emptyRun(), phase: 'busy', path });
  setStatus(tr('Working. The window stays usable.'), 'busy', { sticky: true });
}

function setError(message) {
  run.update((r) => ({ ...r, phase: 'error', text: '', baseline: '' }));
  setStatus(tr('Error: %1').replace('%1', message), 'error', { sticky: true });
}

function setDone(text, seconds) {
  const hasText = text.trim().length > 0;
  run.update((r) => ({ ...r, phase: 'done', text, baseline: text, seconds }));
  if (hasText) setStatus('');
  else {
    setStatus(
      tr('The model heard nothing. If the file has audio, try another model. A smaller one often helps.'),
      'warning',
      { sticky: true },
    );
  }
}

/**
 * Start a run. `strict` applies the drop guard; Browse and an operating-system
 * open name any existing file and a non-audio one ends in the decode error.
 */
export async function transcribePath(path, { strict = false } = {}) {
  const previous = get(run);
  setBusy(path);
  try {
    const result = await call('files.transcribe', { path, strict });
    run.update((r) => (r.path === path ? { ...r, size: result.size ?? null } : r));
  } catch (err) {
    if (err.code === 'not_found') {
      // Nothing was loaded, so the identity of the file that was shown stays
      // and only the status line speaks.
      run.set({ ...previous, phase: 'error', text: '', baseline: '' });
      setStatus(tr('Error: %1').replace('%1', tr('That file is no longer there.')), 'error', { sticky: true });
      return;
    }
    if (get(run).path === path) setError(tr(err.message));
  }
}

/** A path that may be anything the system hands over (Finder, argv). */
export function openPath(path) {
  return transcribePath(path);
}

export function isSupported(path, list = get(extensions)) {
  if (!list.length) return true;
  const lower = path.toLowerCase();
  return list.some((ext) => lower.endsWith(ext));
}

/** The first dropped local file with a supported extension, or null. */
export function pickDropped(files) {
  const pathFor = window.l2t?.pathForFile;
  for (const file of Array.from(files || [])) {
    const path = pathFor ? pathFor(file) : file.path;
    if (path && isSupported(path)) return path;
  }
  return null;
}

export async function browse() {
  if (get(run).phase === 'busy') return;
  const open = window.l2t?.dialog?.openFile;
  if (!open) {
    setStatus(tr('Choosing a file needs the desktop app.'), 'warning', { sticky: true });
    return;
  }
  const path = await open({
    title: tr('Choose an audio or video file'),
    filters: [
      { name: tr('Audio / video'), extensions: get(extensions).map((e) => e.slice(1)) },
      { name: tr('All files'), extensions: ['*'] },
    ],
  });
  if (path) await transcribePath(path);
}

export function edit(text) {
  run.update((r) => ({ ...r, text }));
}

export async function writeClipboard(text) {
  if (window.l2t?.clipboard) await window.l2t.clipboard.writeText(text);
  else await navigator.clipboard?.writeText(text);
}

export async function copyText() {
  const text = get(run).text;
  if (!text) return;
  await writeClipboard(text);
  setStatus(tr('Copied to clipboard.'), 'done');
}

export async function saveText() {
  const r = get(run);
  if (!r.text) return;
  const stem = baseName(r.path).replace(/\.[^.]*$/, '');
  const folder = r.path ? r.path.slice(0, r.path.length - baseName(r.path).length) : '';
  const suggested = `${folder}${stem || 'transcript'}.txt`;
  const save = window.l2t?.dialog?.saveFile;
  if (!save) {
    setStatus(tr('Saving a file needs the desktop app.'), 'warning', { sticky: true });
    return;
  }
  const path = await save({
    title: tr('Save transcript'),
    defaultPath: suggested,
    filters: [
      { name: 'Text', extensions: ['txt'] },
      { name: tr('All files'), extensions: ['*'] },
    ],
  });
  if (!path) return;
  try {
    await call('files.save_text', { path, text: r.text });
    setStatus(tr('Saved: %1').replace('%1', path), 'done');
  } catch (err) {
    setStatus(tr('Save failed: %1').replace('%1', err.message), 'error', { sticky: true });
  }
}

// ---- presets ----------------------------------------------------------------
// The list, the default and the pinned preset belong to the post-processing
// area (`presets.*`); this screen only shows them and pins one for a run.

export const presets = writable({ presets: [], active_id: '', override_id: '' });

function fromState(state) {
  const live = state.profiles.map((p) => ({ id: p.id, name: p.name }));
  return {
    presets: live,
    active_id: state.active_id,
    // A stale override names a preset deleted meanwhile; the picker has to
    // show the default instead.
    override_id: live.some((p) => p.id === state.override_id) ? state.override_id : '',
  };
}

export async function loadPresets() {
  try {
    presets.set(fromState(await call('presets.get')));
  } catch {
    // No recording stack: the strip stays hidden, which is what one preset does too.
  }
}

export async function setOverride(profileId) {
  try {
    presets.set(fromState(await call('presets.set_override', { id: profileId })));
  } catch (err) {
    setStatus(err.message, 'error', { sticky: true });
    await loadPresets();
  }
}

// ---- wiring: events, window-wide drop, OS file open --------------------------

let installed = false;

/**
 * Called once by the shell. `navigate` brings the Transcribe screen forward;
 * it is the only thing this module needs from the shell.
 */
export function installFileInbox({ navigate } = {}) {
  if (installed) return;
  installed = true;

  subscribe('file.progress', (d) => {
    run.update((r) => (r.path === d.path && r.phase === 'busy' ? { ...r, elapsed: d.elapsed } : r));
  });
  subscribe('file.done', (d) => {
    if (get(run).path !== d.path) return;
    setDone(d.text || '', d.elapsed || 0);
  });
  subscribe('file.failed', (d) => {
    if (get(run).path !== d.path) return;
    setError(d.message);
  });
  // Presets edited on the post-processing screen reach this picker live.
  subscribe('presets', () => loadPresets());
  call('files.formats').then((r) => extensions.set(r.extensions)).catch(() => {});

  window.l2t?.onFileOpen?.((path) => {
    navigate?.();
    window.l2t?.window?.show?.();
    openPath(path);
  });

  let depth = 0;
  const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');
  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    depth += 1;
    if (get(run).phase !== 'busy') dragging.set(true);
  });
  window.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = get(run).phase === 'busy' ? 'none' : 'copy';
  });
  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (depth === 0) dragging.set(false);
  });
  window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    dragging.set(false);
    if (get(run).phase === 'busy') return;
    const path = pickDropped(e.dataTransfer.files);
    navigate?.();
    if (path) transcribePath(path, { strict: true });
    else setStatus(tr('That file type is not supported.'), 'warning', { sticky: true });
  });
}

/** Test hook. */
export function _reset() {
  run.set(emptyRun());
  status.set(null);
  dragging.set(false);
  installed = false;
}
