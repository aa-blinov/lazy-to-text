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

async function open(platform = 'linux') {
  rpc.handlers['app.snapshot'] = () => ({ platform, config: { ui: { theme: 'light', language: 'en' } } });
  const { default: App } = await import('../renderer/src/App.svelte');
  render(App);
  await screen.findByTestId('status-strip');
}

const current = () => document.querySelector('nav [aria-current="page"], nav [aria-current="true"]')?.textContent.trim();

describe('shell', () => {
  beforeEach(() => cleanup());

  it('keeps the status strip on screen once connected', async () => {
    await open();
    expect(screen.getByTestId('status-strip')).toBeTruthy();
  });

  it.each(['darwin', 'win32'])('lets the window be taken by its whole top edge on %s', async (platform) => {
    await open();
    const backend = await import('../renderer/src/lib/backend.js');
    backend.snapshot.update((snap) => ({ ...snap, platform }));
    const strip = await screen.findByTestId('drag-strip');
    expect(strip.classList.contains('drag')).toBe(true);
    expect(strip.closest('main')).toBeNull();
    expect(strip.nextElementSibling?.querySelector('#main')).toBeTruthy();
  });

  it('adds no renderer drag strip on Linux', async () => {
    await open();
    const backend = await import('../renderer/src/lib/backend.js');
    backend.snapshot.update((snap) => ({ ...snap, platform: 'linux' }));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('drag-strip')).toBeNull();
  });

  it('jumps to a screen with Ctrl or Cmd plus its number, in sidebar order', async () => {
    await open();
    await fireEvent.keyDown(window, { key: '4', ctrlKey: true });
    await waitFor(() => expect(current()).toBe('Postprocessing'));
    await fireEvent.keyDown(window, { key: '6', metaKey: true });
    await waitFor(() => expect(current()).toBe('Logs'));
    await fireEvent.keyDown(window, { key: '1', ctrlKey: true });
    await waitFor(() => expect(current()).toBe('Transcribe'));
  });

  it('leaves a bare digit, an unbound digit and other modifiers alone', async () => {
    await open();
    await fireEvent.keyDown(window, { key: '3' });
    await fireEvent.keyDown(window, { key: '7', ctrlKey: true });
    await fireEvent.keyDown(window, { key: '0', ctrlKey: true });
    await fireEvent.keyDown(window, { key: '3', ctrlKey: true, shiftKey: true });
    expect(current()).toBe('Transcribe');
  });
});
