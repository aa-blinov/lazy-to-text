// Shared state of the model screens: the catalogue, which cards are on disk,
// which one is active, and the actions that change them. Models, First run
// and the Storage and token cards all read this one store, so a download
// started on one is seen on the others.

import { writable, derived, get } from 'svelte/store';
import { toast } from '../../lib/toast.js';
import { call, subscribe } from '../../lib/rpc.js';
import { progress, state as appState } from '../../lib/backend.js';
import { tr, formatNumber, translateRuntime } from '../../lib/i18n.js';

export const catalogue = writable([]);
export const languages = writable([]);
export const modelState = writable({
  active: null,
  cached: {},
  deleting: [],
  storage_busy: false,
});
export const loaded = writable(false);
export const loadError = writable('');
/** The last load result the runtime reported: {alias, outcome, t}. */
export const lastLoad = writable(null);
/** The first-run screen says when a model is ready, so the toast stays quiet there. */
export const quietReady = writable(false);

/** Alias of the card that is loading now (the active one while state is model_loading). */
export const loadingAlias = derived([modelState, appState], ([$m, $s]) =>
  $s === 'model_loading' ? $m.active : null,
);

export const activeCard = derived([catalogue, modelState], ([$c, $m]) =>
  $c.find((card) => card.alias === $m.active) ?? null,
);

let wired = false;

/** Fill the n-th placeholder of a Qt catalogue string: `%1` ... `%9`. */
export function fmt(template, ...args) {
  return args.reduce((text, value, index) => text.replaceAll(`%${index + 1}`, String(value)), template);
}

export function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return '';
  const unit = (key) => tr(key);
  if (n >= 1024 ** 3) return `${formatNumber(n / 1024 ** 3, 1)} ${unit('GB')}`;
  if (n >= 1024 ** 2) return `${formatNumber(n / 1024 ** 2, 1)} ${unit('MB')}`;
  if (n >= 1024) return `${Math.max(1, Math.round(n / 1024))} ${unit('KB')}`;
  return `${n} ${unit('B')}`;
}

export function formatSize(sizeMb) {
  return sizeMb >= 1000
    ? fmt(tr('%1 GB'), formatNumber(sizeMb / 1000, 1))
    : fmt(tr('%1 MB'), sizeMb);
}

export function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  if (s < 60) return fmt(tr('%1s'), s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * What a download looks like right now: a fraction (or null when no total is
 * known), and the bytes. The backend reports a total late or not at all for
 * some repositories, so the catalogue size stands in for it, as the Qt top
 * bar does; the fraction is held under one until the load really ends.
 */
export function downloadFigures(p, card) {
  const current = Number(p?.current) || 0;
  let total = Number(p?.total) || 0;
  if (total <= 0 && card) total = card.size_mb * 1024 * 1024;
  const fraction = total > 0 && current > 0 ? Math.min(0.99, current / total) : null;
  return { current, total, fraction, elapsed: Number(p?.elapsed) || 0 };
}

export function applyState(next) {
  modelState.update((prev) => ({ ...prev, ...next }));
}

export async function loadModels() {
  try {
    const result = await call('models.list');
    catalogue.set(result.models);
    languages.set(result.languages);
    applyState({
      active: result.active,
      cached: result.cached,
      deleting: result.deleting,
      storage_busy: result.storage_busy,
    });
    loadError.set('');
    loaded.set(true);
  } catch (err) {
    loadError.set(err.message);
    loaded.set(true);
  }
}

export async function refreshState() {
  try {
    applyState(await call('models.state'));
  } catch {
    // The next event or screen visit refreshes it; a failed refresh is not news.
  }
}

function nameOf(alias) {
  const card = get(catalogue).find((c) => c.alias === alias);
  return card ? tr(card.display_name) : alias;
}

/** Subscribe to the server events once for the whole renderer. */
export function wire() {
  if (wired) return;
  wired = true;
  subscribe('models', (d) => applyState(d));
  subscribe('model_load', (d) => {
    lastLoad.set({ ...d, t: Date.now() });
    if (d.outcome === 'error') {
      // The first-run screen shows its own failure; a second voice would
      // point at Logs, which that screen does not have. One id, so a retry
      // replaces the toast instead of stacking another.
      if (!get(quietReady)) {
        toast({
          id: 'model-load-error',
          title: fmt(tr('Could not load %1'), nameOf(d.alias)),
          // The runtime's own sentence when it sent one, else the generic pointer.
          description: d.reason ? translateRuntime(d.reason) : tr('The model did not start. Open Logs in the sidebar to see why.'),
          tone: 'danger',
          duration: 0,
        });
      }
    } else if (d.outcome === 'ready' && !get(quietReady)) {
      toast({ title: fmt(tr('%1 is ready'), nameOf(d.alias)), tone: 'success' });
    }
  });
  subscribe('model_delete', (d) => {
    if (d.deleted) {
      toast({
        title: fmt(tr('Deleted %1'), nameOf(d.alias)),
        description: d.freed_bytes ? fmt(tr('%1 freed'), formatBytes(d.freed_bytes)) : '',
        tone: 'success',
      });
    } else {
      toast({
        title: tr('Delete failed'),
        description: d.error || fmt(tr('Could not delete the cached weights for %1.'), nameOf(d.alias)),
        tone: 'danger',
        duration: 0,
      });
    }
  });
}

function fail(title, err) {
  toast({ title, description: err?.message ?? String(err), tone: 'danger' });
}

/**
 * `expectLoad` is for the Load button of a model that is active on disk but
 * not running: the runtime then loads it instead of answering "already
 * active". A `noop` anyway means it still believes the model is running.
 */
export async function selectModel(alias, { expectLoad = false } = {}) {
  try {
    const result = await call('models.select', { alias });
    if (expectLoad && result?.noop) {
      fail(tr('The model could not be loaded'), new Error(tr('The engine did not start loading it. Restart the app and try again.')));
    }
    await refreshState();
    return result;
  } catch (err) {
    fail(tr('The model could not be switched'), err);
    await refreshState();
    return null;
  }
}

export async function downloadModel(alias) {
  try {
    const result = await call('models.download', { alias });
    await refreshState();
    return result;
  } catch (err) {
    if (err.code === 'already_cached') return selectModel(alias);
    fail(tr('The download could not start'), err);
    await refreshState();
    return null;
  }
}

export async function cancelLoad() {
  try {
    const result = await call('models.cancel_load');
    applyState(result);
    return result;
  } catch (err) {
    fail(tr('Cancel failed'), err);
    return null;
  }
}

export async function saveInference(alias, values) {
  try {
    const result = await call('models.inference.set', { alias, values });
    catalogue.update((cards) =>
      cards.map((c) =>
        c.alias === alias ? { ...c, inference: { ...c.inference, values: result.values } } : c,
      ),
    );
    return result;
  } catch (err) {
    fail(tr('Settings were not saved'), err);
    return null;
  }
}

export { progress };
