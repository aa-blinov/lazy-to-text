// The first-run gate in the shell: with no model on disk the setup screen
// stands in for the sidebar and the screens until it is finished or set aside.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { makeRpc } from './helpers/fakeRpc.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
  reconnect: async () => true,
  markDown: () => {},
  RpcError: class extends Error {},
}));
vi.mock('../renderer/src/lib/transcribe.js', async () => {
  const { writable } = await import('svelte/store');
  return { installFileInbox: () => {}, discardAsk: writable(null), answerDiscard: () => {} };
});
vi.mock('../renderer/src/components/transcribe/DropOverlay.svelte', async () => ({
  default: (await import('./helpers/Stub.svelte')).default,
}));
vi.mock('../renderer/src/views/index.js', async () => {
  const Stub = (await import('./helpers/Stub.svelte')).default;
  return {
    views: ['transcribe', 'models', 'history', 'postprocessing', 'settings', 'logs'].map((id) => ({
      id,
      label: id[0].toUpperCase() + id.slice(1),
      component: Stub,
    })),
  };
});

const CARD = {
  alias: 'rec', canonical: 'o/rec', display_name: 'Recommended one', size_mb: 260, speed: 'fast',
  quality: 'good', languages: 'Russian', description: 'd', compute_type: 'int8', family: 'GigaAM',
  onnx_family: 'gigaam', recommended: true, pitch: 'Start here.', url: 'https://huggingface.co/o/rec',
  wer: 7.1, rtf: '0.018', shared_with: [], inference: { kind: null },
};

async function open(firstRun) {
  // The shell starts its stores once per module load and decides the first
  // frame from the snapshot, so each test sets the snapshot it is about.
  const snap = { first_run: firstRun, config: { ui: { theme: 'light', language: 'en' } } };
  rpc.handlers['app.snapshot'] = () => snap;
  const { snapshot, connected } = await import('../renderer/src/lib/backend.js');
  snapshot.set(snap);
  connected.set(true);
  rpc.handlers['models.list'] = () => ({ models: [CARD], languages: [], active: null, state: 'idle', loading: false, cached: {}, deleting: [], storage_busy: false });
  rpc.handlers['firstrun.status'] = () => ({ show: true, candidate: 'rec', hotkeys: { start: 'ctrl+f2', stop: '' } });
  rpc.handlers['firstrun.defer'] = () => ({ deferred: true });
  const { default: App } = await import('../renderer/src/App.svelte');
  render(App);
}

describe('first-run gate', () => {
  beforeEach(() => cleanup());

  it('shows the setup screen and no sidebar when the runtime says so', async () => {
    await open(true);
    await screen.findByTestId('first-run');

    expect(document.querySelector('nav')).toBeNull();
    expect(screen.queryByTestId('status-strip')).toBeNull();
  });

  it('ignores the screen shortcuts while it is up', async () => {
    await open(true);
    await screen.findByTestId('first-run');

    await fireEvent.keyDown(window, { key: '2', ctrlKey: true });

    expect(screen.getByTestId('first-run')).toBeTruthy();
  });

  it('shows the shell when a model is on disk', async () => {
    await open(false);
    await screen.findByTestId('status-strip');

    expect(screen.queryByTestId('first-run')).toBeNull();
    expect(document.querySelector('nav')).not.toBeNull();
  });

  it('opens the Models screen for See all models instead, and the shell for Set up later', async () => {
    await open(true);
    await screen.findByTestId('model-pitch');
    await fireEvent.click(screen.getByRole('button', { name: 'See all models instead' }));
    await screen.findByTestId('status-strip');
    expect(document.querySelector('nav [aria-current]')?.textContent.trim()).toBe('Models');

    cleanup();
    await open(true);
    await screen.findByTestId('model-pitch');
    await fireEvent.click(screen.getByRole('button', { name: 'Set up later' }));
    await waitFor(() => expect(screen.queryByTestId('first-run')).toBeNull());
    expect(document.querySelector('nav [aria-current]')?.textContent.trim()).toBe('Transcribe');
  });

  it('draws neither the shell nor the setup screen before the runtime has answered', async () => {
    const backend = await import('../renderer/src/lib/backend.js');
    backend._resetBackend();
    rpc.handlers['app.snapshot'] = () => new Promise(() => {});
    const { default: App } = await import('../renderer/src/App.svelte');
    render(App);

    expect(screen.getByTestId('booting')).toBeTruthy();
    expect(document.querySelector('nav')).toBeNull();
    expect(screen.queryByTestId('status-strip')).toBeNull();
    expect(screen.queryByTestId('first-run')).toBeNull();
  });
});
