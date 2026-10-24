// The main process's native-dialog and shell handlers, driven through a fake
// `electron`. The native sheets themselves are Electron's; what is ours, and
// what is checked here, is what each handler asks for and what it hands back
// to the page: a cancelled dialog is null, a path is a string, a link that is
// not http(s) is refused.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { beforeAll, describe, expect, it, vi } from 'vitest';

const require = createRequire(import.meta.url);
const handlers = new Map();
const listeners = new Map();
const calls = [];
const state = { openResult: { canceled: false, filePaths: ['/a/b.wav'] }, saveResult: { canceled: false, filePath: '/x.txt' }, boxResult: { response: 0 } };

function fakeElectron() {
  const win = { id: 1 };
  return {
    app: {
      setName: vi.fn(), requestSingleInstanceLock: () => true, quit: vi.fn(), exit: vi.fn(),
      whenReady: () => new Promise(() => {}), on: vi.fn(), relaunch: vi.fn(), isPackaged: false, name: 'Lazy to Text',
    },
    BrowserWindow: { fromWebContents: () => win },
    Menu: { setApplicationMenu: vi.fn(), buildFromTemplate: (t) => t },
    Tray: class {},
    nativeTheme: { themeSource: 'system' },
    nativeImage: { createFromPath: () => ({ resize: () => ({}) }) },
    screen: {},
    ipcMain: {
      handle: (name, fn) => handlers.set(name, fn),
      on: (name, fn) => listeners.set(name, fn),
    },
    dialog: {
      showOpenDialog: async (_w, o) => { calls.push(['open', o]); return state.openResult; },
      showSaveDialog: async (_w, o) => { calls.push(['save', o]); return state.saveResult; },
      showMessageBox: async (_w, o) => { calls.push(['box', o]); return state.boxResult; },
      showErrorBox: vi.fn(),
    },
    shell: { openExternal: vi.fn(async () => true), showItemInFolder: vi.fn() },
    clipboard: { writeText: vi.fn() },
  };
}

let electron;
beforeAll(() => {
  electron = fakeElectron();
  const Module = require('node:module');
  const original = Module._load;
  Module._load = function (request, ...rest) {
    return request === 'electron' ? electron : original.call(this, request, ...rest);
  };
  try {
    require(join(import.meta.dirname, '..', 'electron', 'main.cjs'));
  } finally {
    Module._load = original;
  }
});

const event = { sender: {} };

describe('native dialogs', () => {
  it('open-file returns the chosen path and null when cancelled', async () => {
    const open = handlers.get('l2t:dialog:open-file');
    expect(await open(event, { title: 'Pick', filters: [{ name: 'Audio', extensions: ['wav'] }] })).toBe('/a/b.wav');
    expect(calls.at(-1)[1].properties).toEqual(['openFile']);

    state.openResult = { canceled: true, filePaths: [] };
    expect(await open(event, {})).toBeNull();
    state.openResult = { canceled: false, filePaths: ['/a/b.wav'] };
  });

  it('open-directory can create a folder', async () => {
    await handlers.get('l2t:dialog:open-directory')(event, { defaultPath: '/m' });
    const [, options] = calls.at(-1);
    expect(options.properties).toEqual(['openDirectory', 'createDirectory']);
    expect(options.defaultPath).toBe('/m');
  });

  it('save-file returns the path, null when cancelled', async () => {
    const save = handlers.get('l2t:dialog:save-file');
    expect(await save(event, { defaultPath: 'x.txt' })).toBe('/x.txt');
    state.saveResult = { canceled: true };
    expect(await save(event, {})).toBeNull();
  });

  it('confirm answers with the index of the pressed button and defaults Cancel last', async () => {
    const confirm = handlers.get('l2t:dialog:confirm');
    state.boxResult = { response: 1 };
    expect(await confirm(event, { message: 'Delete?', buttons: ['Delete', 'Cancel'] })).toBe(1);
    const [, options] = calls.at(-1);
    expect(options.cancelId).toBe(1);
    expect(options.noLink).toBe(true);
  });
});

describe('shell and clipboard', () => {
  it('opens only web links', async () => {
    const open = handlers.get('l2t:shell:open-external');
    await open(event, 'https://example.com/x');
    expect(electron.shell.openExternal).toHaveBeenCalledWith('https://example.com/x');

    electron.shell.openExternal.mockClear();
    for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'ms-settings:privacy', 42]) {
      expect(await open(event, bad)).toBe(false);
    }
    expect(electron.shell.openExternal).not.toHaveBeenCalled();
  });

  it('reveals only absolute paths', () => {
    const show = handlers.get('l2t:shell:show-item');
    show(event, 'relative/file.txt');
    expect(electron.shell.showItemInFolder).not.toHaveBeenCalled();
    show(event, '/abs/file.txt');
    expect(electron.shell.showItemInFolder).toHaveBeenCalledWith('/abs/file.txt');
  });

  it('writes text to the clipboard as a string', async () => {
    await handlers.get('l2t:clipboard:write')(event, null);
    expect(electron.clipboard.writeText).toHaveBeenCalledWith('');
  });

  it('maps an unknown theme to system', () => {
    listeners.get('l2t:theme')(event, 'dark');
    expect(electron.nativeTheme.themeSource).toBe('dark');
    listeners.get('l2t:theme')(event, 'purple');
    expect(electron.nativeTheme.themeSource).toBe('system');
  });
});
