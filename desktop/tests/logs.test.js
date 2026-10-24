import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { makeRpc } from './helpers/fakeRpc.js';
import {
  isNoisy, visibleRecords, levelClass, messageClass, recordText, loggerNames, levelRank,
} from '../renderer/src/components/logs/model.js';

const rpc = makeRpc();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => rpc.call(...a),
  subscribe: (...a) => rpc.subscribe(...a),
  RpcError: class extends Error {},
}));

const R = (id, level, logger, message, user_message = false) => ({ id, time: '12:00:0' + (id % 10), level, logger, message, user_message });
const records = [
  R(1, 'DEBUG', 'app.state_manager', 'checked the clipboard'),
  R(2, 'INFO', 'httpx', 'HTTP Request: GET https://hf.co'),
  R(3, 'INFO', 'app.state_manager', 'Delivery sent', true),
  R(4, 'WARNING', 'app.state_manager', 'Post-processing failed (the server answered HTTP 401)', true),
  R(5, 'ERROR', 'app.backends.onnx', 'Could not load the model'),
];

describe('log rules', () => {
  it('treats a library by its top-level package as network noise', () => {
    expect(isNoisy('httpx')).toBe(true);
    expect(isNoisy('httpx._client')).toBe(true);
    expect(isNoisy('huggingface_hub.file_download')).toBe(true);
    expect(isNoisy('app.state_manager')).toBe(false);
  });

  it('hides network records until asked, and matches level, logger and message together', () => {
    expect(visibleRecords(records).map((r) => r.id)).toEqual([1, 3, 4, 5]);
    expect(visibleRecords(records, { showNetwork: true }).map((r) => r.id)).toEqual([1, 2, 3, 4, 5]);
    expect(visibleRecords(records, { query: ' ONNX ' }).map((r) => r.id)).toEqual([5]);
    expect(visibleRecords(records, { query: 'warning' }).map((r) => r.id)).toEqual([4]);
    // The haystack is "level logger message", so a phrase can span the three.
    expect(visibleRecords(records, { query: 'state_manager delivery' }).map((r) => r.id)).toEqual([3]);
    expect(visibleRecords(records, { query: 'delivery state_manager' }).map((r) => r.id)).toEqual([]);
  });

  it('filters by level floor, by logger and by the user-facing flag', () => {
    expect(visibleRecords(records, { minLevel: 'WARNING' }).map((r) => r.id)).toEqual([4, 5]);
    expect(visibleRecords(records, { logger: 'app.backends.onnx' }).map((r) => r.id)).toEqual([5]);
    expect(visibleRecords(records, { onlyUser: true }).map((r) => r.id)).toEqual([3, 4]);
  });

  it('colours levels with text roles and lets bookkeeping recede but never a warning', () => {
    expect(levelClass('ERROR')).toBe('text-danger-text');
    expect(levelClass('CRITICAL')).toBe('text-danger-text');
    expect(levelClass('WARNING')).toBe('text-warning-text');
    expect(levelClass('INFO')).toBe('text-accent-text');
    expect(levelClass('DEBUG')).toBe('text-ink-faint');
    expect(messageClass(R(1, 'INFO', 'app.x', 'm'))).toBe('text-ink-faint');
    expect(messageClass(R(1, 'INFO', 'app.x', 'm', true))).toBe('text-ink');
    expect(messageClass(R(1, 'WARNING', 'app.x', 'm'))).toBe('text-ink');
    expect(levelRank('mystery')).toBe(levelRank('INFO'));
  });

  it('writes a record as one line and lists own loggers first', () => {
    expect(recordText(records[3])).toBe(
      '12:00:04 [WARNING] app.state_manager: Post-processing failed (the server answered HTTP 401)',
    );
    expect(loggerNames(records)).toEqual(['app.backends.onnx', 'app.state_manager', 'httpx']);
  });
});

async function open() {
  const store = await import('../renderer/src/components/logs/store.js');
  store.records.set([]);
  store.clearedUpTo.set(0);
  const { default: View } = await import('../renderer/src/views/Logs.svelte');
  const utils = render(View);
  return { store, ...utils };
}

beforeEach(() => {
  cleanup();
  rpc.calls.length = 0;
  rpc.handlers['logs.list'] = () => ({ records });
});

describe('logs screen', () => {
  it('lists the ring, tells user-facing lines from bookkeeping, and hides network lines', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5'));
    const rows = [...document.querySelectorAll('[data-level]')];
    expect(rows.map((r) => r.dataset.level)).toEqual(['DEBUG', 'INFO', 'WARNING', 'ERROR']);
    expect(rows.map((r) => r.dataset.user)).toEqual(['false', 'true', 'true', 'false']);
    expect(screen.queryByText(/HTTP Request/)).toBeNull();
    await fireEvent.click(screen.getByRole('switch', { name: /network logs/i }));
    expect(await screen.findByText(/HTTP Request/)).toBeTruthy();
  });

  it('adds a record that arrives as an event, once even if the list had it', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5'));
    rpc.emit('log', R(6, 'INFO', 'app.new', 'fresh line'));
    rpc.emit('log', R(6, 'INFO', 'app.new', 'fresh line'));
    expect(await screen.findByText('fresh line')).toBeTruthy();
    expect(screen.getAllByText('fresh line').length).toBe(1);
  });

  it('debounces the search and filters from the buffer', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5'));
    const search = screen.getByRole('searchbox');
    await fireEvent.input(search, { target: { value: 'onnx' } });
    expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5');
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 1 of 5'), { timeout: 1000 });
  });

  it('clears the view only, after asking, and stays cleared on return', async () => {
    const { store, unmount } = await open();
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5'));
    await fireEvent.click(screen.getByRole('button', { name: 'Clear logs' }));
    expect(get(store.records).length).toBe(5);
    const confirm = [...document.querySelectorAll('[role=alertdialog] button')].find((b) => b.textContent.trim() === 'Clear logs');
    await fireEvent.click(confirm);
    await waitFor(() => expect(get(store.records)).toEqual([]));
    expect(rpc.called('logs.clear')).toEqual([]);
    unmount();
    // Back on the screen: the runtime still holds its ring, but the cut stays.
    const view = render((await import('../renderer/src/views/Logs.svelte')).default);
    await waitFor(() => expect(rpc.called('logs.list').length).toBe(2));
    expect(view.container.querySelectorAll('[data-level]').length).toBe(0);
    expect(get(store.clearedUpTo)).toBe(5);
  });

  it('copies exactly the lines on screen', async () => {
    const writeText = vi.fn(async () => {});
    window.l2t = { clipboard: { writeText } };
    await open();
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('Lines: 4 of 5'));
    await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const text = writeText.mock.calls[0][0];
    expect(text.split('\n').length).toBe(4);
    expect(text).not.toContain('HTTP Request');
    delete window.l2t;
  });

  it('offers the log file location only where the shell can reveal it', async () => {
    await open();
    await waitFor(() => expect(screen.getByTestId('count')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Show log file' })).toBeNull();
  });

  it('says so when the buffer is empty and when the filters hide everything', async () => {
    rpc.handlers['logs.list'] = () => ({ records: [] });
    await open();
    expect(await screen.findByText('No entries yet')).toBeTruthy();
  });
});

describe('logs across a reconnection', () => {
  it('starts over when the window reconnects, so a new runtime numbering from 1 is not merged into the old list', async () => {
    const { records: store, clearedUpTo } = await import('../renderer/src/components/logs/store.js');
    const { epoch } = await import('../renderer/src/lib/backend.js');
    store.set([R(7, 'INFO', 'app.x', 'old life'), R(8, 'INFO', 'app.x', 'old life too')]);
    clearedUpTo.set(8);

    epoch.update((n) => n + 1);

    expect(get(store)).toEqual([]);
    expect(get(clearedUpTo)).toBe(0);
  });
});
