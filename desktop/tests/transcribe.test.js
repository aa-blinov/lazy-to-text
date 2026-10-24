import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';

const handlers = {};
const call = vi.fn();
vi.mock('../renderer/src/lib/rpc.js', () => ({
  call: (...a) => call(...a),
  subscribe: (name, cb) => {
    handlers[name] = cb;
    return () => {};
  },
}));

const lib = await import('../renderer/src/lib/transcribe.js');
const { language } = await import('../renderer/src/lib/i18n.js');
const Transcribe = (await import('../renderer/src/views/Transcribe.svelte')).default;

const PRESETS = {
  enabled: false, active_id: 'a', override_id: '',
  profiles: [{ id: 'a', name: 'Letters' }, { id: 'b', name: 'Work' }],
};

function route(table) {
  call.mockImplementation(async (method, params) => {
    const entry = table[method];
    if (entry instanceof Error) throw entry;
    return typeof entry === 'function' ? entry(params) : entry ?? {};
  });
}

class CodedError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

beforeEach(() => {
  call.mockReset();
  lib._reset();
  language.set('en');
  route({
    'files.formats': { extensions: ['.wav', '.mp3'] },
    'files.transcribe': (p) => ({ started: true, path: p.path, size: 2048 }),
    'presets.get': PRESETS,
  });
  lib.installFileInbox({ navigate: vi.fn() });
});
afterEach(() => {
  delete window.l2t;
});

describe('formatting', () => {
  it('writes sizes in 1024 steps', () => {
    expect(lib.formatSize(12)).toBe('12 B');
    expect(lib.formatSize(2048)).toBe('2 KB');
    expect(lib.formatSize(5 * 1024 ** 2)).toBe('5.0 MB');
    expect(lib.formatSize(3 * 1024 ** 3)).toBe('3.0 GB');
  });

  it('writes processing time in ms, seconds, then minutes', () => {
    expect(lib.formatElapsed(0.25)).toBe('250 ms');
    expect(lib.formatElapsed(12.34)).toBe('12.3 s');
    expect(lib.formatElapsed(125)).toBe('2:05.0');
  });

  it('pluralises words for English and Russian', () => {
    expect(lib.plural(1, '%1 word', '%1 words (few)', '%1 words')).toBe('1 word');
    expect(lib.plural(2, '%1 word', '%1 words (few)', '%1 words')).toBe('2 words');
    language.set('ru');
    expect(lib.plural(2, '%1 word', '%1 words (few)', '%1 words')).toBe('2 слова');
    expect(lib.plural(5, '%1 word', '%1 words (few)', '%1 words')).toBe('5 слов');
    expect(lib.plural(21, '%1 word', '%1 words (few)', '%1 words')).toBe('21 слово');
  });
});

describe('a run', () => {
  it('goes busy at once, then done with the text as the baseline', async () => {
    const started = lib.transcribePath('/a/memo.wav');
    expect(get(lib.run).phase).toBe('busy');
    expect(get(lib.status).kind).toBe('busy');
    await started;
    handlers['file.done']({ path: '/a/memo.wav', text: 'one two three', elapsed: 1.5 });

    const r = get(lib.run);
    expect(r).toMatchObject({ phase: 'done', text: 'one two three', baseline: 'one two three', size: 2048 });
    expect(get(lib.status)).toBeNull();
    expect(lib.describeFile(r)).toBe('2 KB  ·  1.5 s  ·  3 words');
  });

  it('shows Edited exactly while the text differs from what the model returned', async () => {
    await lib.transcribePath('/a/memo.wav');
    handlers['file.done']({ path: '/a/memo.wav', text: 'hello world', elapsed: 2 });
    lib.edit('hello there');
    expect(lib.describeFile(get(lib.run))).toContain('Edited');
    lib.edit('hello world');
    expect(lib.describeFile(get(lib.run))).not.toContain('Edited');
  });

  it('drops a result for a file that is no longer the one shown', async () => {
    await lib.transcribePath('/a/first.wav');
    await lib.transcribePath('/a/second.wav');
    handlers['file.done']({ path: '/a/first.wav', text: 'stale', elapsed: 1 });
    handlers['file.failed']({ path: '/a/first.wav', message: 'stale failure' });

    expect(get(lib.run)).toMatchObject({ phase: 'busy', path: '/a/second.wav' });
  });

  it('reports a failure with the file kept and the message on the status line', async () => {
    await lib.transcribePath('/a/bad.mp3');
    handlers['file.failed']({ path: '/a/bad.mp3', message: 'no audio' });

    expect(get(lib.run)).toMatchObject({ phase: 'error', path: '/a/bad.mp3' });
    expect(get(lib.status)).toMatchObject({ kind: 'error', text: 'Error: no audio', sticky: true });
  });

  it('treats an empty result as a warning, not a transcript', async () => {
    await lib.transcribePath('/a/quiet.wav');
    handlers['file.done']({ path: '/a/quiet.wav', text: '', elapsed: 1 });

    expect(get(lib.run).phase).toBe('done');
    expect(get(lib.status).kind).toBe('warning');
  });

  it('says why a run could not start', async () => {
    route({ 'files.transcribe': new CodedError('not_ready', "Model isn't ready yet — wait for it to finish loading.") });
    await lib.transcribePath('/a/memo.wav');

    expect(get(lib.run).phase).toBe('error');
    expect(get(lib.status).text).toContain("Model isn't ready yet");
  });

  it('keeps the previous identity when the file is gone', async () => {
    await lib.transcribePath('/a/memo.wav');
    handlers['file.done']({ path: '/a/memo.wav', text: 'hi', elapsed: 1 });
    route({ 'files.transcribe': new CodedError('not_found', 'x') });
    await lib.transcribePath('/a/gone.wav');

    const r = get(lib.run);
    expect(r).toMatchObject({ phase: 'error', path: '/a/memo.wav', text: '' });
    expect(get(lib.status).text).toBe('Error: That file is no longer there.');
  });

  it('follows the live elapsed time of the running file only', async () => {
    await lib.transcribePath('/a/memo.wav');
    handlers['file.progress']({ path: '/other.wav', elapsed: 9 });
    handlers['file.progress']({ path: '/a/memo.wav', elapsed: 4 });
    expect(get(lib.run).elapsed).toBe(4);
  });
});

describe('dropping', () => {
  it('takes the first dropped file with a supported extension', () => {
    window.l2t = { pathForFile: (f) => f.path };
    const files = [{ path: '/a/notes.txt' }, { path: '/a/Voice.MP3' }, { path: '/a/b.wav' }];
    expect(lib.pickDropped(files)).toBe('/a/Voice.MP3');
    expect(lib.pickDropped([{ path: '/a/notes.txt' }])).toBeNull();
  });

  it('accepts a drop anywhere on the window and starts a strict run', async () => {
    window.l2t = { pathForFile: (f) => f.path };
    const drop = new Event('drop', { cancelable: true });
    drop.dataTransfer = { types: ['Files'], files: [{ path: '/a/memo.wav' }] };
    window.dispatchEvent(drop);

    await waitFor(() => expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/memo.wav', strict: true }));
    expect(get(lib.dragging)).toBe(false);
  });

  it('refuses a drop while a run is in progress', async () => {
    window.l2t = { pathForFile: (f) => f.path };
    await lib.transcribePath('/a/memo.wav');
    call.mockClear();
    const drop = new Event('drop', { cancelable: true });
    drop.dataTransfer = { types: ['Files'], files: [{ path: '/a/other.wav' }] };
    window.dispatchEvent(drop);

    expect(call).not.toHaveBeenCalled();
  });

  it('opens a file the operating system hands over and brings the screen forward', async () => {
    const navigate = vi.fn();
    let onOpen;
    window.l2t = { onFileOpen: (cb) => (onOpen = cb), window: { show: vi.fn() } };
    lib._reset();
    lib.installFileInbox({ navigate });
    onOpen('/a/from-finder.m4a');

    expect(navigate).toHaveBeenCalled();
    expect(window.l2t.window.show).toHaveBeenCalled();
    await waitFor(() => expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/from-finder.m4a', strict: false }));
  });
});

describe('the screen', () => {
  it('invites a drop while idle and hides Copy and Save', () => {
    render(Transcribe);
    expect(screen.getByText('Drop an audio or video file here')).toBeTruthy();
    expect(screen.getByText('No transcript yet')).toBeTruthy();
    expect(screen.queryByText('Copy')).toBeNull();
    expect(screen.queryByText('Save .txt')).toBeNull();
  });

  it('names the file and the busy status during a run, and disables Browse', async () => {
    render(Transcribe);
    await lib.transcribePath('/a/memo.wav');
    await waitFor(() => expect(screen.getByTestId('file-name').textContent.trim()).toBe('memo.wav'));
    expect(screen.getByTestId('file-detail').textContent).toContain('Transcribing…');
    expect(screen.getByText('Working. The window stays usable.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /browse/i }).disabled).toBe(true);
  });

  it('shows the editable transcript with Copy and Save, and copies what is on screen', async () => {
    const writeText = vi.fn(async () => true);
    window.l2t = { clipboard: { writeText } };
    render(Transcribe);
    await lib.transcribePath('/a/memo.wav');
    handlers['file.done']({ path: '/a/memo.wav', text: 'original text', elapsed: 1 });

    const box = await screen.findByTestId('transcript');
    await fireEvent.input(box, { target: { value: 'edited text' } });
    expect(screen.getByTestId('file-detail').textContent).toContain('Edited');

    await fireEvent.click(screen.getByRole('button', { name: /copy/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('edited text'));
    expect(screen.getByText('Copied to clipboard.')).toBeTruthy();
  });

  it('shows the failure and keeps the file line at Failed', async () => {
    render(Transcribe);
    await lib.transcribePath('/a/bad.mp3');
    handlers['file.failed']({ path: '/a/bad.mp3', message: 'cannot decode' });

    await waitFor(() => expect(screen.getByText('Error: cannot decode')).toBeTruthy());
    expect(screen.getByTestId('file-detail').textContent).toBe('Failed');
  });

  it('hides the preset strip with one preset and shows it with two', async () => {
    route({ 'presets.get': { ...PRESETS, profiles: [PRESETS.profiles[0]] } });
    const first = render(Transcribe);
    await new Promise((r) => setTimeout(r, 0));
    expect(first.queryByText('Preset for this file')).toBeNull();
    first.unmount();

    route({ 'presets.get': PRESETS });
    render(Transcribe);
    expect(await screen.findByText('Preset for this file')).toBeTruthy();
  });

  it('pins the shown preset when the box is ticked and unpins when it is cleared', async () => {
    route({
      'presets.get': PRESETS,
      'presets.set_override': ({ id }) => ({ ...PRESETS, override_id: id }),
    });
    render(Transcribe);
    const box = await screen.findByRole('checkbox');

    await fireEvent.click(box);
    await waitFor(() => expect(call).toHaveBeenCalledWith('presets.set_override', { id: 'a' }));
    await fireEvent.click(box);
    await waitFor(() => expect(call).toHaveBeenCalledWith('presets.set_override', { id: '' }));
  });

  it('falls back to the default when the pinned preset no longer exists', async () => {
    route({ 'presets.get': { ...PRESETS, override_id: 'deleted' } });
    render(Transcribe);
    const box = await screen.findByRole('checkbox');
    expect(box.checked).toBe(false);
  });
});
