// The model screens against a fake runtime: no model is downloaded and no
// network is opened. `lib/rpc.js` is replaced, so every call is scripted.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';

const calls = [];
let handlers = {};
let events = {};

vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: vi.fn(async (method, params = {}) => {
    calls.push([method, params]);
    const fn = handlers[method];
    if (!fn) throw Object.assign(new Error('no handler for ' + method), { code: 'unknown_method' });
    return fn(params);
  }),
  subscribe: vi.fn((name, cb) => {
    events[name] = cb; // wire() subscribes once per module, so these stay across tests
    return () => delete events[name];
  }),
  RpcError: class extends Error {},
}));

import { call } from '../renderer/src/lib/rpc.js';
import { state as appState, progress } from '../renderer/src/lib/backend.js';
import { visibleCards, matchesLanguage } from '../renderer/src/components/models/filter.js';
import {
  catalogue, modelState, loaded, fmt, formatBytes, downloadFigures, formatElapsed,
} from '../renderer/src/components/models/store.js';
import Models from '../renderer/src/views/Models.svelte';
import FirstRun from '../renderer/src/views/FirstRun.svelte';

const primary = (alias) => [...document.querySelectorAll(`[data-alias="${alias}"] button`)]
  .find((b) => ['Download', 'Select'].includes(b.textContent.trim()));

const card = (over) => ({
  alias: 'a', canonical: 'o/a', display_name: 'Alpha', size_mb: 100, vram_gb: 1, speed: 'fast',
  quality: 'good', languages: 'Russian (only)', description: 'About alpha', compute_type: 'int8',
  family: 'GigaAM', onnx_family: 'gigaam', recommended: false, pitch: '', url: 'https://huggingface.co/o/a',
  wer: 5, rtf: '0.010', prefer_cpu: false, auto_language: null, shared_with: [], inference: { kind: null },
  ...over,
});

const CARDS = [
  card({ alias: 'rec', display_name: 'Recommended one', size_mb: 260, recommended: true, wer: 7.1, rtf: '0.018', pitch: 'Start here.' }),
  card({ alias: 'tiny', display_name: 'Tiny', size_mb: 30, family: 'Vosk', wer: 4.5, rtf: '0.006' }),
  card({ alias: 'multi', display_name: 'Multi', size_mb: 1600, family: 'Whisper', languages: 'multilingual', wer: 16.2, rtf: '0.457',
    onnx_family: 'whisper', inference: { kind: 'whisper', values: { language: null, vad_filter: true, beam_size: 5, temperature: 0, initial_prompt: null } } }),
  card({ alias: 'blank', display_name: 'Unscored', size_mb: 50, family: 'Canary', wer: null, rtf: null, languages: 'English' }),
];

function scripted(over = {}) {
  handlers = {
    'models.list': () => ({
      models: CARDS,
      languages: [{ label: 'Auto-detect', code: null }, { label: 'Russian', code: 'ru' }],
      active: 'rec', state: 'idle', loading: false,
      cached: { rec: true, tiny: false, multi: true, blank: false }, deleting: [], storage_busy: false,
    }),
    'models.state': () => ({ active: 'rec', state: 'idle', loading: false, cached: { rec: true, tiny: false, multi: true, blank: false }, deleting: [], storage_busy: false }),
    'models.download': () => ({ alias: 'tiny', downloading: true, state: 'model_loading' }),
    'models.select': (p) => ({ alias: p.alias, noop: false, state: 'model_loading' }),
    'models.cancel_load': () => ({ cancelled: true, active: 'rec', state: 'idle', cached: {} }),
    'models.delete_info': () => ({ size_bytes: 3 * 1024 * 1024, shared_with: ['rnnt'], in_use: false }),
    'models.delete': () => ({ started: true }),
    'models.inference.set': (p) => ({ alias: p.alias, kind: 'whisper', values: { language: p.values.language ?? null, vad_filter: true, beam_size: 5, temperature: 0, initial_prompt: null }, pushed: true }),
    'models.storage.get': () => ({ path: '/m', is_default: true, size_bytes: null, busy: false }),
    'models.hf_token.get': () => ({ set: false }),
    'firstrun.status': () => ({ show: true, candidate: 'rec', hotkeys: { start: 'ctrl+f2', stop: 'ctrl+f3' } }),
    'firstrun.defer': () => ({ deferred: true }),
    'firstrun.complete': () => ({ complete: true }),
    ...over,
  };
}

beforeEach(() => {
  calls.length = 0;
  scripted();
  appState.set('idle');
  progress.set({ current: 0, total: 0, desc: '', elapsed: 0 });
  catalogue.set([]);
  loaded.set(false);
});
afterEach(() => cleanup());

describe('filtering and sorting', () => {
  it('matches the language filter against the registry text, as Qt does', () => {
    expect(matchesLanguage(card({ languages: 'multilingual' }), 'multilingual')).toBe(true);
    expect(matchesLanguage(card({ languages: '25 langs' }), 'multilingual')).toBe(true);
    expect(matchesLanguage(card({ languages: 'English only' }), 'Russian')).toBe(false);
    expect(matchesLanguage(card({ languages: 'English only' }), '')).toBe(true);
  });

  it('keeps catalogue order, sorts by accuracy with unscored models last, by size, and by speed', () => {
    const order = (sort) => visibleCards(CARDS, { sort }).map((c) => c.alias);
    expect(order('order')).toEqual(['rec', 'tiny', 'multi', 'blank']);
    expect(order('accuracy')).toEqual(['tiny', 'rec', 'multi', 'blank']);
    expect(order('speed')).toEqual(['tiny', 'rec', 'multi', 'blank']);
    expect(order('size')).toEqual(['tiny', 'blank', 'rec', 'multi']);
  });

  it('combines query, language and family with AND', () => {
    expect(visibleCards(CARDS, { query: 'tiny' }).map((c) => c.alias)).toEqual(['tiny']);
    expect(visibleCards(CARDS, { language: 'multilingual' }).map((c) => c.alias)).toEqual(['multi']);
    expect(visibleCards(CARDS, { family: 'Vosk', language: 'Russian' }).map((c) => c.alias)).toEqual(['tiny']);
    expect(visibleCards(CARDS, { family: 'Vosk', language: 'English' })).toEqual([]);
  });

  it('finds a model by its translated name too', () => {
    const translate = (s) => (s === 'Tiny' ? 'Крошечная' : s);
    expect(visibleCards(CARDS, { query: 'крошеч' }, translate).map((c) => c.alias)).toEqual(['tiny']);
  });
});

describe('figures', () => {
  it('fills the n-th placeholder and formats bytes and seconds', () => {
    expect(fmt('%1 of %2', 3, 4)).toBe('3 of 4');
    expect(formatBytes(0)).toBe('');
    expect(formatBytes(1536 * 1024)).toBe('1.5 MB');
    expect(formatElapsed(75)).toBe('1:15');
    expect(formatElapsed(9)).toBe('9s');
  });

  it('falls back to the catalogue size for a missing total and holds under 100 percent', () => {
    const f = downloadFigures({ current: 50 * 1024 * 1024, total: 0 }, { size_mb: 100 });
    expect(f.fraction).toBeCloseTo(0.5);
    expect(downloadFigures({ current: 500 * 1024 * 1024, total: 0 }, { size_mb: 100 }).fraction).toBe(0.99);
    expect(downloadFigures({ current: 0, total: 0 }, null).fraction).toBeNull();
  });
});

describe('Models', () => {
  it('shows every card with Download on absent ones, Select on present ones and Active on one', async () => {
    render(Models);
    await screen.findByText('Recommended one');

    const rec = document.querySelector('[data-alias="rec"]');
    const tiny = document.querySelector('[data-alias="tiny"]');
    const multi = document.querySelector('[data-alias="multi"]');
    expect(rec.textContent).toContain('Active');
    expect(rec.textContent).toContain('Recommended');
    expect(tiny.textContent).toContain('Download');
    expect(multi.textContent).toContain('Select');
    expect(multi.textContent).toContain('Delete');
    expect(rec.textContent).not.toContain('Delete'); // the active card cannot be deleted
    expect(screen.getByText('Showing 4 of 4 models')).toBeTruthy();
  });

  it('renders an unmeasured model with blanks rather than zeros', async () => {
    render(Models);
    await screen.findByText('Unscored');
    expect(document.querySelector('[data-alias="blank"]').textContent).toContain('WER —');
  });

  it('narrows as the user types and says so when nothing matches', async () => {
    render(Models);
    await screen.findByText('Tiny');
    const search = screen.getByRole('searchbox', { name: 'Search models' });

    await fireEvent.input(search, { target: { value: 'tiny' } });
    await waitFor(() => expect(document.querySelectorAll('[data-testid=model-card]').length).toBe(1));

    await fireEvent.input(search, { target: { value: 'zzz' } });
    await screen.findByText('No models match your filters');
    await fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(document.querySelectorAll('[data-testid=model-card]').length).toBe(4));
  });

  it('downloads an absent model and selects a present one', async () => {
    render(Models);
    await screen.findByText('Tiny');

    await fireEvent.click(primary('tiny'));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'models.download' && p.alias === 'tiny')).toBe(true));

    await fireEvent.click(primary('multi'));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'models.select' && p.alias === 'multi')).toBe(true));
  });

  it('explains the lock instead of silently disabling the buttons', async () => {
    appState.set('recording');
    render(Models);
    await screen.findByText('Tiny');

    expect(screen.getByText(/Recording is in progress/)).toBeTruthy();
    expect(primary('tiny').disabled).toBe(true);
  });

  it('shows the download with bytes and elapsed, and Cancel stays reachable', async () => {
    appState.set('model_loading');
    progress.set({ current: 26 * 1024 * 1024, total: 260 * 1024 * 1024, desc: '', elapsed: 7 });
    render(Models);
    await screen.findByTestId('load-banner');

    const banner = screen.getByTestId('load-banner').textContent;
    expect(banner).toContain('Downloading Recommended one');
    expect(banner).toContain('10%');
    expect(banner).toContain('26.0 MB of 260.0 MB');
    expect(banner).toContain('7s');
    expect(document.querySelector('[data-alias="rec"]').textContent).toContain('Loading 10%');

    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(calls.some(([m]) => m === 'models.cancel_load')).toBe(true));
  });

  it('confirms a delete with the measured size and the siblings, then deletes', async () => {
    render(Models);
    await screen.findByText('Multi');

    await fireEvent.click([...document.querySelectorAll('[data-alias="multi"] button')].find((b) => b.textContent.trim() === 'Delete'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('Remove the downloaded weights for Multi (3.0 MB)?');
    expect(dialog.textContent).toContain('rnnt');
    expect(calls.some(([m]) => m === 'models.delete')).toBe(false); // nothing happens before the confirmation

    await fireEvent.click([...dialog.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Delete'));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'models.delete' && p.alias === 'multi')).toBe(true));
  });

  it('saves a changed language on the active whisper card', async () => {
    handlers['models.list'] = () => ({
      models: CARDS, languages: [{ label: 'Auto-detect', code: null }, { label: 'Russian', code: 'ru' }],
      active: 'multi', state: 'idle', loading: false, cached: { multi: true }, deleting: [], storage_busy: false,
    });
    render(Models);
    await screen.findByTestId('inference-settings');

    const prompt = screen.getByLabelText('Initial prompt');
    await fireEvent.input(prompt, { target: { value: 'Anthropic' } });
    await fireEvent.change(prompt);

    await waitFor(() => expect(calls.some(([m, p]) => m === 'models.inference.set' && p.alias === 'multi' && p.values.initial_prompt === 'Anthropic')).toBe(true));
  });

  it('says why the catalogue is missing instead of showing an empty page', async () => {
    handlers['models.list'] = () => { throw new Error('runtime gone'); };
    render(Models);

    expect((await screen.findByText('The catalogue could not be loaded'))).toBeTruthy();
    expect(screen.getByText(/runtime gone/)).toBeTruthy();
  });

  it('applies the pushed model state without a refetch', async () => {
    render(Models);
    await screen.findByText('Tiny');

    events.models({ active: 'multi', cached: { rec: true, tiny: true, multi: true, blank: false }, deleting: [], storage_busy: false });

    await waitFor(() => expect(document.querySelector('[data-alias="multi"]').textContent).toContain('Active'));
    expect(get(modelState).cached.tiny).toBe(true);
  });
});

describe('FirstRun', () => {
  it('offers the recommended model with its pitch and no second competing button', async () => {
    render(FirstRun, { pollMs: 5 });
    await screen.findByTestId('model-pitch');

    expect(screen.getByTestId('model-pitch').textContent).toBe('Start here.');
    expect(screen.getAllByRole('button', { name: 'Download' }).length).toBe(1);
    expect(screen.getByRole('button', { name: 'Set up later' })).toBeTruthy();
  });

  it('walks choose, download, key, and writes the flag only on Start dictating', async () => {
    let loading = true;
    handlers['models.state'] = () => ({ active: 'rec', state: 'idle', loading, cached: { rec: !loading }, deleting: [], storage_busy: false });
    const done = vi.fn();
    const { component } = render(FirstRun, { pollMs: 5 });
    component.$on('done', done);
    await screen.findByTestId('model-pitch');

    await fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await screen.findByRole('button', { name: 'Cancel' });
    expect(calls.some(([m, p]) => m === 'models.download' && p.alias === 'rec')).toBe(true);
    expect(calls.some(([m]) => m === 'firstrun.complete')).toBe(false);

    loading = false;
    await screen.findByTestId('hotkey-caps');
    expect(screen.getByTestId('hotkey-caps').textContent).toContain('Ctrl');
    expect(screen.getByTestId('hotkey-caps').textContent).toContain('F3');

    await fireEvent.click(screen.getByRole('button', { name: 'Start dictating' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(calls.filter(([m]) => m === 'firstrun.complete').length).toBe(1);
  });

  it('does not advance to the key step when loading stopped but nothing is on disk', async () => {
    handlers['models.state'] = () => ({ active: 'rec', state: 'idle', loading: false, cached: { rec: false }, deleting: [], storage_busy: false });
    render(FirstRun, { pollMs: 5 });
    await screen.findByTestId('model-pitch');

    await fireEvent.click(screen.getByRole('button', { name: 'Download' }));

    await screen.findByText('The download did not finish.');
    expect(screen.queryByTestId('hotkey-caps')).toBeNull();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
  });

  it('Set up later ends the screen for the session without writing the flag', async () => {
    const done = vi.fn();
    const { component } = render(FirstRun, { pollMs: 5 });
    component.$on('done', done);
    await screen.findByTestId('model-pitch');

    await fireEvent.click(screen.getByRole('button', { name: 'Set up later' }));

    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(calls.some(([m, p]) => m === 'firstrun.defer' && p.reason === 'later')).toBe(true);
    expect(calls.some(([m]) => m === 'firstrun.complete')).toBe(false);
  });

  it('See all models instead sends the user to the catalogue', async () => {
    const catalogueRequested = vi.fn();
    const { component } = render(FirstRun, { pollMs: 5 });
    component.$on('catalogue', catalogueRequested);
    await screen.findByTestId('model-pitch');

    await fireEvent.click(screen.getByRole('button', { name: 'See all models instead' }));

    await waitFor(() => expect(catalogueRequested).toHaveBeenCalled());
    expect(calls.some(([m, p]) => m === 'firstrun.defer' && p.reason === 'catalogue')).toBe(true);
  });

  it('cancelling the download goes back to the choice', async () => {
    handlers['models.state'] = () => ({ loading: true, cached: {} });
    render(FirstRun, { pollMs: 5 });
    await screen.findByTestId('model-pitch');
    await fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    await screen.findByTestId('model-pitch');
    expect(calls.some(([m]) => m === 'models.cancel_load')).toBe(true);
  });
});
