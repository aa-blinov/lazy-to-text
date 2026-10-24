import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import { toasts } from '@monos/ui';
import { makeRpc } from './helpers/fakeRpc.js';
import { formatBytes, percent, loadingDetail, resourceItems, isAccelerator, loadTone } from '../renderer/src/components/statusFormat.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
  RpcError: class extends Error {},
}));

describe('status figures', () => {
  it('formats bytes and caps progress below 100 until the load ends', () => {
    expect(formatBytes(0)).toBe('');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(percent(50, 100)).toBe(50);
    expect(percent(100, 100)).toBe(99);
    expect(percent(5, 0)).toBeNull();
  });

  it('describes a load by bytes when a size is known, by bytes alone, or by elapsed time', () => {
    const MB = 1024 * 1024;
    expect(loadingDetail({ current: 10 * MB, total: 40 * MB, elapsed: 4 })).toBe('10.0 MB / 40.0 MB (25%) · 4 s');
    expect(loadingDetail({ current: 3 * MB, total: 0, elapsed: 0 })).toBe('3.0 MB');
    expect(loadingDetail({ current: 0, total: 0, elapsed: 12 })).toBe('12 s');
    expect(loadingDetail({})).toBe('');
  });

  it('lists the resources a sample has, GPU only when it was measured', () => {
    expect(resourceItems({})).toEqual([]);
    const cpuRam = resourceItems({ cpu_percent: 12.4, ram_percent: 50, ram_used_mb: 8192, ram_total_mb: 16384 });
    expect(cpuRam.map((i) => [i.key, i.value])).toEqual([['CPU', '12%'], ['RAM', '8.0/16.0 GB']]);
    const gpu = resourceItems({ cpu_percent: 1, ram_percent: 1, gpu_util_percent: 80, gpu_vram_used_mb: 2048, gpu_vram_total_mb: 8192 });
    expect(gpu.map((i) => i.key)).toEqual(['CPU', 'RAM', 'GPU', 'VRAM']);
  });

  it('knows accelerators and tones a load figure', () => {
    expect(isAccelerator('CoreML')).toBe(true);
    expect(isAccelerator('CPU')).toBe(false);
    expect(loadTone(90)).toBe('text-danger-text');
    expect(loadTone(60)).toBe('text-warning-text');
    expect(loadTone(10)).toBe('text-ink-soft');
  });
});

async function open() {
  const backend = await import('../renderer/src/lib/backend.js');
  backend.state.set('idle');
  backend.engine.set({ provider: null, model: '', alias: '' });
  backend.resources.set({});
  backend.progress.set({ current: 0, total: 0, desc: '', elapsed: 0 });
  const { default: Strip } = await import('../renderer/src/components/StatusStrip.svelte');
  render(Strip);
  await tick();
  return backend;
}

describe('status strip', () => {
  beforeEach(() => {
    cleanup();
    rpc.calls.length = 0;
    delete rpc.handlers['models.cancel_load'];
  });

  it('shows the state, the model, the engine and the resources', async () => {
    const backend = await open();
    expect(screen.getByTestId('model').textContent.trim()).toBe('No model');
    backend.engine.set({ provider: 'CoreML', model: 'm', alias: 'gigaam-v3-ctc' });
    backend.resources.set({ cpu_percent: 40, ram_percent: 50, ram_used_mb: 1024, ram_total_mb: 2048 });
    backend.state.set('recording');
    await tick();
    expect(screen.getByTestId('state-pill').textContent).toContain('Recording');
    expect(screen.getByTestId('model').textContent).toContain('gigaam-v3-ctc');
    expect(screen.getByTestId('engine').textContent).toContain('CoreML');
    expect(screen.getByTestId('engine').className).toContain('text-success-text');
    expect(screen.getByTestId('resources').textContent).toContain('CPU');
    expect(screen.getByRole('meter')).toBeTruthy();
  });

  it('shows loading progress with bytes and elapsed time, and Cancel calls the runtime', async () => {
    rpc.handlers['models.cancel_load'] = () => ({ cancelled: true });
    const backend = await open();
    backend.state.set('model_loading');
    backend.progress.set({ current: 10 * 1024 * 1024, total: 40 * 1024 * 1024, desc: 'x', elapsed: 4 });
    await tick();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('25');
    expect(screen.getByTestId('loading').textContent).toContain('10.0 MB / 40.0 MB (25%) · 4 s');
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(rpc.called('models.cancel_load').length).toBe(1));
  });

  it('is indeterminate while no size is known', async () => {
    const backend = await open();
    backend.state.set('model_loading');
    backend.progress.set({ current: 0, total: 0, desc: '', elapsed: 3 });
    await tick();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBeNull();
  });

  it('says so when the runtime has no way to cancel yet, instead of failing silently', async () => {
    const backend = await open();
    backend.state.set('model_loading');
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(rpc.called('models.cancel_load').length).toBe(1));
    const shown = get(toasts).map((t) => `${t.title} ${t.description}`).join(' ');
    expect(shown).toContain('Could not cancel the load');
    expect(shown).toContain('not available');
    // The button is usable again afterwards.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel' }).disabled).toBe(false));
  });
});
