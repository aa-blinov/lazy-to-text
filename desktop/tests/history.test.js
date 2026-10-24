import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { toasts, clearToasts } from '@monos/ui';

const handlers = {};
const call = vi.fn();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => call(...a),
  subscribe: (name, cb) => {
    handlers[name] = cb;
    return () => {};
  },
}));

const lib = await import('../renderer/src/lib/history.js');
const { language } = await import('../renderer/src/lib/i18n.js');
const History = (await import('../renderer/src/views/History.svelte')).default;

const entry = (id, text, over = {}) => ({
  id, timestamp: id, text, duration: 3.25, model: 'gigaam-v3-ctc', alias: 'GigaAM v3',
  language: 'ru', datetime: '10:00:00 01.01.2026', ...over,
});

let store;
function listing(entries, over = {}) {
  return { enabled: true, entries, start_hotkey: 'ctrl+f8', max_entries: 1000, ...over };
}

beforeEach(() => {
  call.mockReset();
  clearToasts();
  language.set('en');
  store = [entry(3, 'Buy milk and bread'), entry(2, 'Call the bank'), entry(1, 'Quarterly report draft')];
  call.mockImplementation(async (method, params) => {
    if (method === 'history.list') return listing(store);
    if (method === 'history.delete') {
      const deleted = store.find((e) => e.id === params.id);
      store = store.filter((e) => e.id !== params.id);
      return { deleted, total: store.length };
    }
    if (method === 'history.restore') {
      store = [...store, params.entry].sort((a, b) => b.id - a.id);
      return { restored: true, total: store.length };
    }
    if (method === 'history.clear') {
      const cleared = store.length;
      store = [];
      return { cleared };
    }
    if (method === 'history.export') return { exported: store.length, path: params.path };
    return {};
  });
});
afterEach(() => {
  delete window.l2t;
});

describe('helpers', () => {
  it('searches the text only, ignoring case', () => {
    const rows = [entry(1, 'Hello World', { alias: 'zzz' }), entry(2, 'other')];
    expect(lib.filterEntries(rows, 'WORLD').map((e) => e.id)).toEqual([1]);
    expect(lib.filterEntries(rows, 'zzz')).toEqual([]);
    expect(lib.filterEntries(rows, '  ')).toBe(rows);
  });

  it('writes a hotkey as a key cap', () => {
    expect(lib.formatHotkey('ctrl+f8')).toBe('Ctrl+F8');
    expect(lib.formatHotkey('right_cmd')).toBe('Right cmd');
    expect(lib.formatHotkey('')).toBe('');
  });

  it('counts entries, and shows shown-of-total while a search narrows them', () => {
    expect(lib.countLabel(3, 3, false)).toBe('3 entries');
    expect(lib.countLabel(1, 1, false)).toBe('1 entry');
    expect(lib.countLabel(1, 3, true)).toBe('1 of 3 entries');
    language.set('ru');
    expect(lib.countLabel(2, 3, false)).toBe('3 записи');
  });
});

describe('the screen', () => {
  it('lists entries newest first with the alias and one-decimal duration', async () => {
    render(History);
    expect(await screen.findByText('Buy milk and bread')).toBeTruthy();
    expect(screen.getAllByText('GigaAM v3').length).toBe(3);
    expect(screen.getAllByText('3.3 s').length).toBe(3);
    expect(screen.getByTestId('count').textContent.trim()).toBe('3 entries');
  });

  it('narrows as you type and clears on Escape from anywhere', async () => {
    render(History);
    await screen.findByText('Call the bank');
    const field = screen.getByRole('searchbox');
    await fireEvent.input(field, { target: { value: 'bank' } });

    await waitFor(() => expect(screen.queryByText('Buy milk and bread')).toBeNull());
    expect(screen.getByTestId('count').textContent.trim()).toBe('1 of 3 entries');

    await fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.getByText('Buy milk and bread')).toBeTruthy());
  });

  it('says nothing matches, not that nothing was dictated, when a search finds none', async () => {
    render(History);
    await screen.findByText('Call the bank');
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'zzzz' } });
    expect(await screen.findByText('No matching transcriptions')).toBeTruthy();
    expect(screen.queryByText('Nothing dictated yet')).toBeNull();
  });

  it('shows the start hotkey in the empty state', async () => {
    store = [];
    render(History);
    expect(await screen.findByText('Nothing dictated yet')).toBeTruthy();
    expect(screen.getByText('Ctrl+F8')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Clear history' }).disabled).toBe(true);
  });

  it('deletes at once and offers an undo that restores the entry', async () => {
    render(History);
    await screen.findByText('Call the bank');
    const row = screen.getByText('Call the bank').closest('tr');
    await fireEvent.click(row.querySelector('button[aria-label="Delete"]'));

    await waitFor(() => expect(call).toHaveBeenCalledWith('history.delete', { id: 2 }));
    const toast = get(toasts).find((t) => t.action);
    expect(toast.action.label).toBe('Undo');

    toast.action.onClick();
    await waitFor(() => expect(call).toHaveBeenCalledWith('history.restore', {
      entry: expect.objectContaining({ id: 2, text: 'Call the bank' }),
    }));
  });

  it('reloads when the runtime says the history changed', async () => {
    render(History);
    await screen.findByText('Call the bank');
    store = [entry(9, 'A new dictation'), ...store];
    handlers.history({});
    expect(await screen.findByText('A new dictation')).toBeTruthy();
  });

  it('copies the full text of a row', async () => {
    const writeText = vi.fn(async () => true);
    window.l2t = { clipboard: { writeText } };
    render(History);
    const row = (await screen.findByText('Call the bank')).closest('tr');
    await fireEvent.click(row.querySelector('button[aria-label="Copy"]'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Call the bank'));
  });

  it('opens the details with the whole text', async () => {
    store = [entry(5, 'word '.repeat(200).trim())];
    render(History);
    await fireEvent.click(await screen.findByTitle(store[0].text));
    const body = await screen.findByTestId('detail-text');
    expect(body.textContent).toBe(store[0].text);
  });

  it('asks natively before clearing, and clears only on a yes', async () => {
    const confirm = vi.fn(async () => 1);
    window.l2t = { dialog: { confirm } };
    render(History);
    await screen.findByText('Call the bank');

    await fireEvent.click(screen.getByRole('button', { name: 'Clear history' }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(confirm.mock.calls[0][0].detail).toBe('Delete all 3 transcriptions? This cannot be undone.');
    expect(call).not.toHaveBeenCalledWith('history.clear', expect.anything());

    confirm.mockResolvedValue(0);
    await fireEvent.click(screen.getByRole('button', { name: 'Clear history' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('history.clear'));
  });

  it('exports to the chosen path and not at all when the dialog is cancelled', async () => {
    const saveFile = vi.fn(async () => null);
    window.l2t = { dialog: { saveFile } };
    render(History);
    await screen.findByText('Call the bank');

    await fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await waitFor(() => expect(saveFile).toHaveBeenCalled());
    expect(call).not.toHaveBeenCalledWith('history.export', expect.anything());

    saveFile.mockResolvedValue('/tmp/out.txt');
    await fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('history.export', { path: '/tmp/out.txt' }));
  });
});
