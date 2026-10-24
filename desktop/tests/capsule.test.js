import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { makeRpc } from './helpers/fakeRpc.js';
import { capsuleCopy, collapse, clock, DELIVERY_VISIBLE_MS } from '../renderer/src/components/capsule/copy.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
  RpcError: class extends Error {},
}));

const tr = (s) => s;

describe('capsule copy', () => {
  it('names each delivery outcome in the past tense and never claims Pasted', () => {
    const pasted = capsuleCopy({ delivery: { outcome: 'pasted', detail: '', text: 'hi' } }, tr);
    expect(pasted.title).toBe('Paste sent');
    expect(pasted.title).not.toMatch(/^Pasted/);
    expect(capsuleCopy({ delivery: { outcome: 'copied', detail: '', text: 'hi' } }, tr).title).toBe('Copied');
    expect(capsuleCopy({ delivery: { outcome: 'copied', detail: 'Cmd+V', text: 'hi' } }, tr).title).toBe('Copied — press Cmd+V');
    expect(capsuleCopy({ delivery: { outcome: 'failed', detail: '', text: 'hi' } }, tr).title).toBe('Delivery failed');
  });

  it('collapses the delivered text to one line and never shows it on a failure', () => {
    expect(collapse('one\n two\t three')).toBe('one two three');
    expect(capsuleCopy({ delivery: { outcome: 'pasted', text: 'a\nb' } }, tr).body).toBe('a b');
    expect(capsuleCopy({ delivery: { outcome: 'copied', text: '  ' } }, tr).body).toBe('Copied to clipboard');
    const failed = capsuleCopy({ delivery: { outcome: 'failed', text: 'my secret words' } }, tr);
    expect(failed.body).toBe('Nothing was pasted. The reason is in Logs.');
    expect(JSON.stringify(failed)).not.toContain('secret');
  });

  it('ignores an unknown outcome and says nothing for idle', () => {
    expect(capsuleCopy({ delivery: { outcome: 'mystery' } }, tr)).toBeNull();
    expect(capsuleCopy({ state: 'idle', delivery: null }, tr)).toBeNull();
    expect(capsuleCopy({ state: 'recording', delivery: null }, tr).body).toBe('Speak now');
    expect(capsuleCopy({ state: 'processing', delivery: null }, tr).body).toBe('Transcribing speech');
  });

  it('formats the recording clock', () => {
    expect(clock(0)).toBe('00:00');
    expect(clock(61_500)).toBe('01:01');
    expect(clock(-5)).toBe('00:00');
  });
});

async function open() {
  rpc.handlers['app.snapshot'] = () => ({ config: { ui: { theme: 'light', language: 'en' } } });
  const backend = await import('../renderer/src/lib/backend.js');
  backend.state.set('idle');
  backend.level.set(0);
  const { default: Overlay } = await import('../renderer/src/Overlay.svelte');
  render(Overlay);
  await tick();
  return backend;
}

describe('capsule', () => {
  beforeEach(() => {
    cleanup();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  });
  afterEach(() => vi.useRealTimers());

  it('draws nothing while idle', async () => {
    await open();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows recording with a clock and a live level, in tokens only', async () => {
    const backend = await open();
    backend.state.set('recording');
    const capsule = await screen.findByRole('status');
    expect(capsule.dataset.kind).toBe('recording');
    expect(capsule.textContent).toContain('Recording');
    expect(screen.getByTestId('clock').textContent).toBe('00:00');
    vi.advanceTimersByTime(3500);
    await tick();
    expect(screen.getByTestId('clock').textContent).toBe('00:03');
    backend.level.set(0.9);
    await tick();
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('90');
    expect(capsule.innerHTML).not.toMatch(/#[0-9a-f]{3,8}|rgb\(/i);
  });

  it('keeps the confirmation up when the state returns to idle, then lets it go', async () => {
    const backend = await open();
    backend.state.set('processing');
    await tick();
    rpc.emit('delivery', { outcome: 'pasted', detail: '', text: 'hello world' });
    backend.state.set('idle');
    const capsule = await screen.findByRole('status');
    expect(capsule.textContent).toContain('Paste sent');
    expect(capsule.textContent).toContain('hello world');
    vi.advanceTimersByTime(DELIVERY_VISIBLE_MS - 100);
    await tick();
    expect(screen.queryByRole('status')).not.toBeNull();
    vi.advanceTimersByTime(200);
    await tick();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows a delivery that arrives while still processing, and a new recording ends it', async () => {
    const backend = await open();
    backend.state.set('processing');
    await tick();
    rpc.emit('delivery', { outcome: 'copied', detail: 'Ctrl+V', text: 'x' });
    expect((await screen.findByRole('status')).textContent).toContain('Copied — press Ctrl+V');
    backend.state.set('recording');
    await tick();
    expect(screen.getByRole('status').dataset.kind).toBe('recording');
  });

  it('does not change for an outcome it does not know', async () => {
    await open();
    rpc.emit('delivery', { outcome: 'mystery', detail: '', text: '' });
    await tick();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
