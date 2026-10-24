import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { toasts, clearToasts } from '@monos/ui';
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
  const Stub = (await import('./helpers/HeadingStub.svelte')).default;
  return {
    views: ['transcribe', 'models', 'history', 'postprocessing', 'settings', 'logs'].map((id) => ({
      id,
      label: id[0].toUpperCase() + id.slice(1),
      component: Stub,
    })),
  };
});

async function open(language = 'en') {
  rpc.handlers['app.snapshot'] = () => ({ config: { ui: { theme: 'light', language } } });
  const { default: App } = await import('../renderer/src/App.svelte');
  render(App);
  await screen.findByTestId('status-strip');
  // The module keeps its first snapshot between tests; set the language as a refresh would.
  const { snapshot } = await import('../renderer/src/lib/backend.js');
  snapshot.set({ config: { ui: { theme: 'light', language } } });
  await waitFor(() => expect(document.documentElement.lang).toBe(language));
}

describe('keyboard: Cmd/Ctrl+N moves the focus into the screen', () => {
  beforeEach(() => cleanup());

  it('puts the focus on the new screen heading, which is not a Tab stop', async () => {
    await open();
    screen.getByRole('button', { name: 'Models' }).focus();
    await fireEvent.keyDown(window, { key: '3', ctrlKey: true });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('heading')));
    expect(document.activeElement.getAttribute('tabindex')).toBe('-1');
  });

  it('does the same for Cmd+, (Settings)', async () => {
    await open();
    screen.getByRole('button', { name: 'Models' }).focus();
    await fireEvent.keyDown(window, { key: ',', metaKey: true });
    await waitFor(() => expect(document.activeElement.tagName).toBe('H1'));
  });

  it('has a Skip to content link before the sidebar that moves the focus into the screen', async () => {
    await open();
    const link = screen.getByRole('link', { name: 'Skip to content' });
    const sidebarItem = screen.getByRole('button', { name: 'Models' });
    expect(link.compareDocumentPosition(sidebarItem) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await fireEvent.click(link);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('heading')));
  });

  it('names the skip link in Russian', async () => {
    await open('ru');
    expect(screen.getByRole('link', { name: 'Перейти к содержимому' })).toBeTruthy();
  });
});

describe('toasts', () => {
  beforeEach(() => {
    clearToasts();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    clearToasts();
  });

  it('ends an error that asked to stay until closed, after about eight seconds', async () => {
    const { toast } = await import('../renderer/src/lib/toast.js');
    toast({ title: 'Could not load', tone: 'danger', duration: 0 });
    toast({ title: 'Saved', tone: 'success' });
    vi.advanceTimersByTime(4100);
    expect(get(toasts).map((t) => t.title)).toEqual(['Could not load']);
    vi.advanceTimersByTime(4000);
    expect(get(toasts)).toEqual([]);
  });

  it('keeps no more than three, dropping the oldest', async () => {
    const { toast } = await import('../renderer/src/lib/toast.js');
    for (const n of [1, 2, 3, 4, 5]) toast({ title: `Export failed ${n}`, tone: 'danger' });
    expect(get(toasts).map((t) => t.title)).toEqual(['Export failed 3', 'Export failed 4', 'Export failed 5']);
  });

  it('shows at most three in the live region, above the status strip', async () => {
    vi.useRealTimers();
    const { toast } = await import('../renderer/src/lib/toast.js');
    await open();
    for (const n of [1, 2, 3, 4]) toast({ title: `Failed ${n}`, tone: 'danger' });
    await waitFor(() => expect(screen.getByText('Failed 4')).toBeTruthy());
    expect(screen.queryByText('Failed 1')).toBeNull();
    const region = screen.getByText('Failed 4').closest('[aria-live]');
    expect(region.getAttribute('aria-live')).toBe('polite');
    expect(region.className).toContain('bottom-9');
  });

  it('every failing toast of the app passes through the wrapper, never the library directly', async () => {
    const { readdirSync, readFileSync, statSync } = await import('node:fs');
    const { join, sep } = await import('node:path');
    const walk = (dir) => readdirSync(dir).flatMap((n) => {
      const p = join(dir, n);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
    const offenders = walk(join(__dirname, '../renderer/src'))
      .filter((f) => /\.(svelte|js)$/.test(f) && !f.split(sep).join('/').endsWith('lib/toast.js'))
      .filter((f) => /import\s*\{[^}]*\btoast\b[^}]*\}\s*from\s*'@monos\/ui'/.test(readFileSync(f, 'utf8')));
    expect(offenders).toEqual([]);
  });
});

describe('a failed dictation on the main window', () => {
  beforeEach(() => {
    cleanup();
    clearToasts();
  });

  it('says why in a toast, with the runtime sentence in the interface language', async () => {
    await open('ru');
    await waitFor(() => expect(document.documentElement.lang).toBe('ru'));
    rpc.emit('delivery', {
      outcome: 'failed',
      kind: 'too_short',
      detail: 'The recording was too short to transcribe. Speak a little longer before you stop.',
    });
    const [item] = get(toasts);
    expect(item.title).toBe('Запись слишком короткая');
    expect(item.description).toContain('Говорите чуть дольше');
    expect(item.duration).toBeGreaterThan(0);
  });

  it('stays quiet for a delivery that worked', async () => {
    await open();
    rpc.emit('delivery', { outcome: 'pasted', detail: '', text: 'hi' });
    expect(get(toasts)).toEqual([]);
  });
});
