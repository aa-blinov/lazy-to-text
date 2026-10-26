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

describe('errors in words', () => {
  it('strips the plumbing prefix and keeps what went wrong', () => {
    expect(lib.friendlyError('Subprocess error: TranscriptionError: Could not read audio from a.wav')).toBe('Could not read audio from a.wav');
    expect(lib.friendlyError('ValueError: bad')).toBe('bad');
    expect(lib.friendlyError('plain words')).toBe('plain words');
    expect(lib.friendlyError('')).toBe('Something went wrong.');
  });

  it('never shows library internals or build paths', () => {
    const raw = 'Subprocess error: TranscriptionError: [ONNXRuntimeError] : 1 : FAIL : Non-zero status code returned while running Reshape node /Users/cloudtest/vss/_work/1/s/onnxruntime/core/providers/cpu/tensor/reshape_helper.h:45';
    const out = lib.friendlyError(raw);
    expect(out).toBe('The model could not process this file. The Logs have the details.');
    expect(out).not.toMatch(/cloudtest|ONNX|Reshape/);
  });

  it('puts the plain text on the status line when a run fails', async () => {
    await lib.transcribePath('/a/bad.mp3');
    handlers['file.failed']({ path: '/a/bad.mp3', message: 'Subprocess error: TranscriptionError: Could not read audio' });
    expect(get(lib.status).text).toBe('Error: Could not read audio');
  });
});

describe('a result that arrived while the stream was out', () => {
  it('is read back from the runtime after a reconnect', async () => {
    await lib.transcribePath('/a/long.wav');
    route({ 'files.result': { result: { path: '/a/long.wav', status: 'done', text: 'it finished meanwhile', elapsed: 9 } } });
    handlers['__connected']({ after: 'blink' });
    await vi.waitFor(() => expect(get(lib.run).phase).toBe('done'));
    expect(get(lib.run).text).toBe('it finished meanwhile');
  });

  it('shows a failure that happened meanwhile, and leaves a still-running run alone', async () => {
    await lib.transcribePath('/a/long.wav');
    route({ 'files.result': { result: { path: '/a/long.wav', status: 'running' } } });
    await lib.syncRun();
    expect(get(lib.run).phase).toBe('busy');

    route({ 'files.result': { result: { path: '/a/long.wav', status: 'failed', message: 'Could not read audio' } } });
    await lib.syncRun();
    expect(get(lib.run).phase).toBe('error');
    expect(get(lib.status).text).toBe('Error: Could not read audio');
  });

  it('marks a run as failed when the engine goes away under it', async () => {
    await lib.transcribePath('/a/long.wav');
    handlers['__disconnected']({});
    expect(get(lib.run).phase).toBe('error');
    expect(get(lib.status).text).toBe('Error: The engine stopped.');
  });
});

describe('replacing an edited transcript', () => {
  async function editedTranscript() {
    await lib.transcribePath('/a/first.wav');
    handlers['file.done']({ path: '/a/first.wav', text: 'what the model said', elapsed: 1 });
    lib.edit('what I fixed by hand');
  }

  it('does not ask while the text is the model\'s own', async () => {
    await lib.transcribePath('/a/first.wav');
    handlers['file.done']({ path: '/a/first.wav', text: 'untouched', elapsed: 1 });
    const confirm = vi.fn();
    window.l2t = { dialog: { confirm } };
    await lib.transcribePath('/a/second.wav');
    expect(confirm).not.toHaveBeenCalled();
    expect(get(lib.run).path).toBe('/a/second.wav');
  });

  it('asks through the desktop dialog and keeps the text on "Keep editing"', async () => {
    await editedTranscript();
    const confirm = vi.fn(async () => 1);
    window.l2t = { dialog: { confirm } };

    await lib.transcribePath('/a/second.wav');

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0].buttons).toEqual(['Replace', 'Keep editing']);
    expect(get(lib.run)).toMatchObject({ path: '/a/first.wav', text: 'what I fixed by hand', phase: 'done' });
    expect(call.mock.calls.filter(([m]) => m === 'files.transcribe').length).toBe(1);
  });

  it('replaces the text once the user agrees', async () => {
    await editedTranscript();
    window.l2t = { dialog: { confirm: vi.fn(async () => 0) } };
    await lib.transcribePath('/a/second.wav');
    expect(get(lib.run)).toMatchObject({ path: '/a/second.wav', phase: 'busy' });
  });

  it('asks in the window when there is no desktop dialog, and waits for the answer', async () => {
    await editedTranscript();
    const started = lib.transcribePath('/a/second.wav');
    await Promise.resolve();
    expect(get(lib.discardAsk)).not.toBeNull();
    expect(get(lib.run).path).toBe('/a/first.wav');

    lib.answerDiscard(false);
    await started;
    expect(get(lib.discardAsk)).toBeNull();
    expect(get(lib.run)).toMatchObject({ path: '/a/first.wav', text: 'what I fixed by hand' });

    const again = lib.transcribePath('/a/third.wav');
    await Promise.resolve();
    lib.answerDiscard(true);
    await again;
    expect(get(lib.run).path).toBe('/a/third.wav');
  });

  it('asks for a drop too, since a drop anywhere is the easy way to lose the text', async () => {
    await editedTranscript();
    const confirm = vi.fn(async () => 1);
    window.l2t = { dialog: { confirm }, pathForFile: () => '/a/dropped.wav' };
    const drop = new Event('drop', { cancelable: true });
    drop.dataTransfer = { types: ['Files'], files: [{ name: 'dropped.wav' }] };
    window.dispatchEvent(drop);
    await vi.waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(get(lib.run).path).toBe('/a/first.wav');
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

  it('says why a run could not start while a model is loading', async () => {
    const { state } = await import('../renderer/src/lib/backend.js');
    state.set('model_loading');
    route({ 'files.transcribe': new CodedError('not_ready', "Model isn't ready yet — wait for it to finish loading.") });
    await lib.transcribePath('/a/memo.wav');
    state.set('idle');

    expect(get(lib.run).phase).toBe('error');
    expect(get(lib.status).text).toContain("Model isn't ready yet");
  });

  it('does not tell the user to wait when no model is loaded at all, and points at Models', async () => {
    const { state, engine } = await import('../renderer/src/lib/backend.js');
    state.set('idle');
    engine.set({ provider: null, model: '', alias: '' });
    route({ 'files.transcribe': new CodedError('not_ready', "Model isn't ready yet — wait for it to finish loading.") });
    await lib.transcribePath('/a/memo.wav');

    expect(get(lib.status).text).not.toContain('wait');
    expect(get(lib.status)).toMatchObject({ kind: 'warning', action: 'models' });
    expect(get(lib.run).phase).not.toBe('busy');
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

describe('files given at a cold start', () => {
  const NOT_READY = () => new CodedError('not_ready', "Model isn't ready yet — wait for it to finish loading.");

  async function stores() {
    return import('../renderer/src/lib/backend.js');
  }

  it('pulls the queued paths from the shell once its inbox is installed, and says it is ready', async () => {
    window.l2t = {
      onFileOpen: vi.fn(),
      ready: vi.fn(),
      pendingFiles: vi.fn(async () => ['/a/cold.wav']),
    };
    const navigate = vi.fn();
    lib._reset();
    lib.installFileInbox({ navigate });

    expect(window.l2t.ready).toHaveBeenCalledTimes(1);
    expect(window.l2t.ready.mock.invocationCallOrder[0]).toBeGreaterThan(window.l2t.onFileOpen.mock.invocationCallOrder[0]);
    await waitFor(() => expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/cold.wav', strict: false }));
    expect(navigate).toHaveBeenCalled();
  });

  it('does not run one path twice when the push and the pull both bring it', async () => {
    let onOpen;
    window.l2t = {
      onFileOpen: (cb) => (onOpen = cb),
      pendingFiles: async () => ['/a/twice.wav'],
    };
    lib._reset();
    lib.installFileInbox({ navigate: vi.fn() });
    onOpen('/a/twice.wav');
    await waitFor(() => expect(call.mock.calls.filter(([m]) => m === 'files.transcribe')).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(call.mock.calls.filter(([m]) => m === 'files.transcribe')).toHaveLength(1);
  });

  it('keeps a file the runtime refused as not ready, and transcribes it when the model arrives', async () => {
    const { engine, state } = await stores();
    state.set('idle');
    engine.set({ provider: null, model: '', alias: '' });
    let ready = false;
    route({
      'files.transcribe': (p) => {
        if (!ready) throw NOT_READY();
        return { started: true, path: p.path, size: 10 };
      },
    });
    await lib.openPath('/a/cold.wav');

    // Not a dead end: the line points at Models, the file is still wanted.
    expect(get(lib.status)).toMatchObject({ kind: 'warning', action: 'models' });
    expect(get(lib.run).phase).not.toBe('busy');

    ready = true;
    state.set('model_loading');
    expect(get(lib.status).text).toContain('as soon as it is ready');
    engine.set({ provider: 'CPU', model: 'vosk', alias: 'vosk-ru-small' });
    state.set('idle');

    await waitFor(() => expect(get(lib.run)).toMatchObject({ phase: 'busy', path: '/a/cold.wav' }));
    expect(call.mock.calls.filter(([m]) => m === 'files.transcribe')).toHaveLength(2);
    engine.set({ provider: null, model: '', alias: '' });
  });

  it('forgets the waiting file when the user starts another run by hand', async () => {
    const { engine, state } = await stores();
    state.set('idle');
    engine.set({ provider: null, model: '', alias: '' });
    let ready = false;
    route({
      'files.transcribe': (p) => {
        if (!ready) throw NOT_READY();
        return { started: true, path: p.path, size: 10 };
      },
    });
    await lib.openPath('/a/cold.wav');
    await lib.transcribePath('/a/mine.wav');

    ready = true;
    engine.set({ provider: 'CPU', model: 'vosk', alias: 'x' });
    await new Promise((r) => setTimeout(r, 20));
    expect(call.mock.calls.filter(([m, p]) => m === 'files.transcribe' && p.path === '/a/cold.wav')).toHaveLength(1);
    engine.set({ provider: null, model: '', alias: '' });
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
    const box = await screen.findByRole('checkbox', { name: /Preset for this file/ });

    await fireEvent.click(box);
    await waitFor(() => expect(call).toHaveBeenCalledWith('presets.set_override', { id: 'a' }));
    await fireEvent.click(box);
    await waitFor(() => expect(call).toHaveBeenCalledWith('presets.set_override', { id: '' }));
  });

  it('falls back to the default when the pinned preset no longer exists', async () => {
    route({ 'presets.get': { ...PRESETS, override_id: 'deleted' } });
    render(Transcribe);
    const box = await screen.findByRole('checkbox', { name: /Preset for this file/ });
    expect(box.checked).toBe(false);
  });

describe('second QA round', () => {
  const DECODE = 'Could not read audio from corrupt.mp3. The file may be damaged, cut short, or not an audio or video file.';

  it('translates the runtime\'s file-decode sentence, whose file name sits in the middle', async () => {
    language.set('ru');
    await lib.transcribePath('/a/corrupt.mp3');
    handlers['file.failed']({ path: '/a/corrupt.mp3', message: DECODE });

    expect(get(lib.status).text).toBe(
      'Ошибка: Не удалось прочитать звук из файла «corrupt.mp3». Файл может быть повреждён, оборван или не быть аудио- или видеофайлом.',
    );
  });

  it('shows an unknown runtime sentence as it came', async () => {
    language.set('ru');
    await lib.transcribePath('/a/x.wav');
    handlers['file.failed']({ path: '/a/x.wav', message: 'Something nobody translated.' });
    expect(get(lib.status).text).toBe('Ошибка: Something nobody translated.');
  });

  it('writes sizes and times with the interface language\'s decimal separator', () => {
    language.set('ru');
    expect(lib.formatSize(5 * 1024 ** 2)).toMatch(/^5,0\s/);
    expect(lib.formatElapsed(4.7)).toBe('4,7 с');
  });

  it('does not keep naming a file that failed once the next run is refused before it starts', async () => {
    const { state, engine } = await import('../renderer/src/lib/backend.js');
    state.set('idle');
    engine.set({ provider: null, model: '', alias: '' });
    await lib.transcribePath('/a/empty.wav');
    handlers['file.failed']({ path: '/a/empty.wav', message: 'Could not read audio from empty.wav. The file may be damaged, cut short, or not an audio or video file.' });
    expect(get(lib.run)).toMatchObject({ phase: 'error', path: '/a/empty.wav' });

    route({ 'files.transcribe': new CodedError('not_ready', 'No model is loaded. Open Models and choose one.') });
    await lib.transcribePath('/a/next.wav');

    expect(get(lib.run).path).toBeNull();
    expect(get(lib.status)).toMatchObject({ action: 'models' });
  });

  it('passes overwrite with a path the save dialog returned, and explains an existing file', async () => {
    window.l2t = { dialog: { saveFile: vi.fn(async () => '/a/out.txt') } };
    await lib.transcribePath('/a/memo.wav');
    handlers['file.done']({ path: '/a/memo.wav', text: 'hello', elapsed: 1 });
    await lib.saveText();
    expect(call).toHaveBeenCalledWith('files.save_text', { path: '/a/out.txt', text: 'hello', overwrite: true });

    route({ 'files.save_text': new CodedError('exists', 'A file with that name already exists. Choose another name, or confirm that it may be replaced.') });
    await lib.saveText();
    expect(get(lib.status).text).toBe('Save failed: A file with that name already exists. Choose another name, or confirm that it may be replaced.');
  });
});
});

describe('files that arrive while the first-run page is up', () => {
  it('holds an operating-system open until the shell is shown, then runs only the latest', async () => {
    const { shellShown } = await import('../renderer/src/lib/nav.js');
    const navigate = vi.fn();
    let onOpen;
    window.l2t = { onFileOpen: (cb) => (onOpen = cb), window: { show: vi.fn() } };
    lib._reset();
    shellShown.set(false);
    lib.installFileInbox({ navigate });
    call.mockClear();

    onOpen('/a/first.wav');
    onOpen('/a/second.wav');
    await Promise.resolve();
    expect(call).not.toHaveBeenCalledWith('files.transcribe', expect.anything());
    expect(navigate).not.toHaveBeenCalled();

    shellShown.set(true);

    await waitFor(() => expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/second.wav', strict: false }));
    expect(call).not.toHaveBeenCalledWith('files.transcribe', { path: '/a/first.wav', strict: false });
    expect(navigate).toHaveBeenCalled();
  });

  it('holds a drop the same way, and keeps it strict', async () => {
    const { shellShown } = await import('../renderer/src/lib/nav.js');
    window.l2t = { pathForFile: (f) => f.path };
    lib._reset();
    shellShown.set(false);
    lib.installFileInbox({ navigate: vi.fn() });
    call.mockClear();
    const drop = new Event('drop', { cancelable: true });
    drop.dataTransfer = { types: ['Files'], files: [{ path: '/a/memo.wav' }] };
    window.dispatchEvent(drop);
    expect(call).not.toHaveBeenCalledWith('files.transcribe', expect.anything());

    shellShown.set(true);

    await waitFor(() => expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/memo.wav', strict: true }));
  });
});

describe('splitting by speakers', () => {
  let store;
  beforeEach(async () => {
    store = await import('../renderer/src/components/models/store.js');
    store.modelState.set({ active: null, cached: {}, deleting: [], storage_busy: false });
  });

  const box = () => screen.getByRole('checkbox', { name: /Split by speakers/ });

  it('is greyed out until the model is downloaded, and says why on hover', async () => {
    render(Transcribe);

    expect(box().disabled).toBe(true);
    const wrap = screen.getByTestId('diarize-option');
    await fireEvent.mouseEnter(wrap);
    await waitFor(() => expect(document.querySelector('[role="tooltip"]')?.textContent).toMatch(/Download the diarization model in Models/), { timeout: 2000 });
  });

  it('can be ticked once the model is on disk, and has no tooltip then', async () => {
    store.modelState.set({ active: null, cached: { diarization: true }, deleting: [], storage_busy: false });
    render(Transcribe);

    expect(box().disabled).toBe(false);
    await fireEvent.click(box());
    expect(get(lib.diarize)).toBe(true);
  });

  it('sends the option and the localised label with the file when ticked', async () => {
    store.modelState.set({ active: null, cached: { diarization: true }, deleting: [], storage_busy: false });
    lib.diarize.set(true);

    await lib.transcribePath('/a/two-voices.wav');

    expect(call).toHaveBeenCalledWith('files.transcribe', {
      path: '/a/two-voices.wav', strict: false, diarize: true, speaker_label: 'Speaker',
    });
  });

  it('sends nothing extra when the box is clear', async () => {
    store.modelState.set({ active: null, cached: { diarization: true }, deleting: [], storage_busy: false });

    await lib.transcribePath('/a/one.wav');

    expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/one.wav', strict: false });
  });

  it('drops a tick when the model has gone since, instead of starting a run that fails', async () => {
    lib.diarize.set(true);

    await lib.transcribePath('/a/gone.wav');

    expect(call).toHaveBeenCalledWith('files.transcribe', { path: '/a/gone.wav', strict: false });
  });

  it('unticks the box and points to Models when the runtime says the model is missing', async () => {
    store.modelState.set({ active: null, cached: { diarization: true }, deleting: [], storage_busy: false });
    lib.diarize.set(true);
    route({
      'files.transcribe': () => { throw new CodedError('diarization_missing', 'not downloaded'); },
    });

    await lib.transcribePath('/a/x.wav');

    expect(get(lib.diarize)).toBe(false);
    expect(get(lib.status)).toMatchObject({ kind: 'warning', action: 'models' });
  });
});
