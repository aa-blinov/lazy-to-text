// The main process's native-dialog and shell handlers, driven through a fake
// `electron`. The native sheets themselves are Electron's; what is ours, and
// what is checked here, is what each handler asks for and what it hands back
// to the page: a cancelled dialog is null, a path is a string, a link that is
// not http(s) is refused.
import { createRequire } from 'node:module';
import { join, resolve, sep } from 'node:path';
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
      getLocale: () => 'en-US', setAboutPanelOptions: vi.fn(), getVersion: () => '9.9.9', getLoginItemSettings: () => ({}), setLoginItemSettings: vi.fn(), releaseSingleInstanceLock: vi.fn(), getPath: () => '/tmp/l2t-test', focus: vi.fn(),
    },
    protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() },
    session: { defaultSession: null },
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

// Every handler asks who is calling: a frame of one of the app's windows
// showing one of the app's pages. The window registry is stood in for here;
// the foreign-frame cases below are the ones that matter.
const appFrame = { url: 'l2t-app://app/index.html' };
const event = { sender: {}, senderFrame: appFrame };
let windowsModule;
beforeAll(() => {
  windowsModule = require(join(import.meta.dirname, '..', 'electron', 'windows.cjs'));
  windowsModule.isRendererContents = () => true;
});

describe('who may call', () => {
  const channels = ['l2t:connection', 'l2t:dialog:open-file', 'l2t:dialog:confirm', 'l2t:shell:open-external',
    'l2t:shell:show-item', 'l2t:clipboard:write', 'l2t:backend:restart'];

  it('refuses a page that is not one of the app pages, on every handler', async () => {
    for (const url of ['file:///tmp/evil/evil.html', 'https://example.com/', 'l2t-app://other/index.html',
      'l2t-app://app/../../etc/passwd', 'http://127.0.0.1:5173/index.html', '']) {
      for (const name of channels) {
        await expect(Promise.resolve().then(() => handlers.get(name)({ sender: {}, senderFrame: { url } }, {})),
          `${name} from ${url}`).rejects.toThrow('Not allowed');
      }
    }
  });

  it('refuses a call with no frame, and a sender that is not one of the app windows', async () => {
    await expect(Promise.resolve().then(() => handlers.get('l2t:connection')({ sender: {} }))).rejects.toThrow('Not allowed');
    windowsModule.isRendererContents = () => false;
    try {
      await expect(Promise.resolve().then(() => handlers.get('l2t:connection')(event))).rejects.toThrow('Not allowed');
    } finally {
      windowsModule.isRendererContents = () => true;
    }
  });

  it('hands the connection to the app windows only, and says so plainly when there is none', async () => {
    await expect(Promise.resolve().then(() => handlers.get('l2t:connection')(event))).rejects.toThrow('The engine is not running.');
  });

  it('ignores a fire-and-forget message from a foreign page', () => {
    electron.nativeTheme.themeSource = 'system';
    listeners.get('l2t:theme')({ sender: {}, senderFrame: { url: 'file:///x.html' } }, 'dark');
    expect(electron.nativeTheme.themeSource).toBe('system');
  });
});

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
    const dir = resolve(sep, 'm');
    await handlers.get('l2t:dialog:open-directory')(event, { defaultPath: dir });
    const [, options] = calls.at(-1);
    expect(options.properties).toEqual(['openDirectory', 'createDirectory']);
    expect(options.defaultPath).toBe(dir);
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

describe('dialog arguments', () => {
  it('drops a default path that is neither a file name nor a clean absolute path', async () => {
    const save = handlers.get('l2t:dialog:save-file');
    const abs = resolve(sep, 'home', 'me', 'notes.txt');
    for (const [given, kept] of [['notes.txt', 'notes.txt'], [abs, abs],
      ['../notes.txt', undefined], ['dir/notes.txt', undefined], ['/home/../notes.txt', undefined], [5, undefined], [{}, undefined]]) {
      await save(event, { defaultPath: given });
      expect(calls.at(-1)[1].defaultPath, String(given)).toBe(kept);
    }
  });

  it('passes only well-formed filters and bounded text to the open dialog', async () => {
    await handlers.get('l2t:dialog:open-file')(event, {
      title: 'x'.repeat(500),
      filters: [{ name: 'Audio', extensions: ['wav', 'm4a', '../x', 7] }, { name: 3, extensions: ['a'] }, 'junk'],
    });
    const [, options] = calls.at(-1);
    expect(options.title).toBeUndefined();
    expect(options.filters).toEqual([{ name: 'Audio', extensions: ['wav', 'm4a'] }]);
  });

  it('takes an options argument that is not an object as no options', async () => {
    await handlers.get('l2t:dialog:open-file')(event, 'hello');
    expect(calls.at(-1)[1].properties).toEqual(['openFile']);
    await handlers.get('l2t:dialog:open-file')(event, null);
    await handlers.get('l2t:dialog:open-file')(event);
  });

  it('keeps the confirm buttons to four short strings and the ids inside them', async () => {
    const confirm = handlers.get('l2t:dialog:confirm');
    await confirm(event, { message: 'm', buttons: ['A', 'B', 'C', 'D', 'E'], defaultId: 9, cancelId: -1, type: 'rm -rf' });
    let [, options] = calls.at(-1);
    expect(options.buttons).toEqual(['A', 'B', 'C', 'D']);
    expect([options.defaultId, options.cancelId, options.type]).toEqual([0, 3, 'question']);
    await confirm(event, { message: 'm', buttons: 'nope' });
    [, options] = calls.at(-1);
    expect(options.buttons).toEqual(['OK', 'Cancel']);
  });

  it('only hands a clean absolute folder to the folder dialog as its start', async () => {
    const pick = handlers.get('l2t:dialog:open-directory');
    await pick(event, { defaultPath: 'models' });
    expect(calls.at(-1)[1].defaultPath).toBeUndefined();
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

  it('reveals only absolute, normalised paths', () => {
    const show = handlers.get('l2t:shell:show-item');
    for (const bad of ['relative/file.txt', '/abs/../etc/passwd', '/abs//file.txt', '/abs/./file.txt', '/a\0b', 42, null, {}]) {
      show(event, bad);
    }
    expect(electron.shell.showItemInFolder).not.toHaveBeenCalled();
    const good = resolve(sep, 'abs', 'file.txt');
    show(event, good);
    expect(electron.shell.showItemInFolder).toHaveBeenCalledWith(good);
  });

  it('refuses a malformed web link and an overlong one', async () => {
    const open = handlers.get('l2t:shell:open-external');
    electron.shell.openExternal.mockClear();
    expect(await open(event, 'http://')).toBe(false);
    expect(await open(event, `https://example.com/${'a'.repeat(3000)}`)).toBe(false);
    expect(electron.shell.openExternal).not.toHaveBeenCalled();
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

describe('the window log path', () => {
  it('answers a sync message with a path, and with null to a foreign page', () => {
    const answer = { returnValue: 'unset' };
    listeners.get('l2t:backend:log-path')({ ...event, returnValue: undefined, set returnValue(v) { answer.returnValue = v; } });
    expect(typeof answer.returnValue).toBe('string');
    expect(answer.returnValue).toMatch(/app\.log$/);
    const foreign = { sender: {}, senderFrame: { url: 'file:///x.html' }, set returnValue(v) { answer.returnValue = v; } };
    listeners.get('l2t:backend:log-path')(foreign);
    expect(answer.returnValue).toBeNull();
  });
});

describe('the menu', () => {
  let menuTemplate;
  beforeAll(() => {
    menuTemplate = require(join(import.meta.dirname, '..', 'electron', 'main.cjs'))._internals.menuTemplate;
  });
  const find = (template, label) => template.find((m) => m.label === label);

  it('has a Window menu with Minimize, Zoom, Cmd+W close and a numbered entry per screen on macOS', () => {
    const mac = menuTemplate('en', { isMac: true, isPackaged: true });
    const windowMenu = find(mac, 'Window');
    expect(windowMenu).toBeTruthy();
    const items = windowMenu.submenu;
    expect(items.find((i) => i.role === 'minimize').accelerator).toBe('CmdOrCtrl+M');
    expect(items.find((i) => i.role === 'zoom')).toBeTruthy();
    expect(items.find((i) => i.role === 'close').accelerator).toBe('CmdOrCtrl+W');
    const screens = items.filter((i) => /^CmdOrCtrl\+[1-6]$/.test(i.accelerator ?? ''));
    expect(screens.map((i) => i.label)).toEqual(['Transcribe', 'Models', 'History', 'Post-processing', 'Settings', 'Logs']);
  });

  it('is translated into Russian, in the application menu too', () => {
    const ru = menuTemplate('ru', { isMac: true, isPackaged: true });
    const labels = JSON.stringify(ru);
    expect(labels).toContain('Выйти из Lazy to Text');
    expect(labels).toContain('Настройки…');
    expect(find(ru, 'Окно')).toBeTruthy();
    expect(find(ru, 'Правка')).toBeTruthy();
    expect(labels).not.toContain('"Quit Lazy to Text"');
  });

  it('has an About entry in the application menu on Windows and Linux that opens the page\'s own About', () => {
    const { menuTemplate } = require(join(import.meta.dirname, '..', 'electron', 'main.cjs'))._internals;
    for (const lang of ['en', 'ru']) {
      const submenu = menuTemplate(lang, { isMac: false, isPackaged: true })[0].submenu;
      const about = submenu.find((i) => i.label === (lang === 'ru' ? 'О приложении Lazy to Text' : 'About Lazy to Text'));
      expect(about, lang).toBeTruthy();
      expect(about.role).toBeUndefined();
      const shown = vi.spyOn(windowsModule, 'showMain').mockImplementation(() => {});
      const sent = vi.spyOn(windowsModule, 'sendToApp').mockImplementation(() => true);
      const main = { webContents: { id: 'main' } };
      const got = vi.spyOn(windowsModule, 'getMain').mockImplementation(() => main);
      about.click();
      expect(shown).toHaveBeenCalled();
      expect(sent).toHaveBeenCalledWith(main.webContents, 'l2t:navigate', 'about');
      shown.mockRestore(); sent.mockRestore(); got.mockRestore();
    }
  });

  it('gives the native About panel a description, the licence and the repository link, in the language of the app', () => {
    const { aboutOptions, REPO_URL } = require(join(import.meta.dirname, '..', 'electron', 'main.cjs'))._internals;
    const en = aboutOptions('en');
    expect(en).toMatchObject({ applicationName: 'Lazy to Text', applicationVersion: '9.9.9', website: REPO_URL });
    expect(en.credits).toContain('ONNX Runtime');
    expect(en.credits).toContain('MIT');
    expect(en.credits).toContain(REPO_URL);
    expect(en.credits).not.toMatch(/CUDA|NVIDIA/);
    expect(aboutOptions('ru').credits).toContain('лицензии MIT');
  });

  it('hands the panel its options whenever the menu is built', () => {
    const { applyLanguage } = require(join(import.meta.dirname, '..', 'electron', 'main.cjs'))._internals;
    electron.app.setAboutPanelOptions.mockClear();
    applyLanguage('ru');
    expect(electron.app.setAboutPanelOptions).toHaveBeenCalledWith(expect.objectContaining({ website: 'https://github.com/aa-blinov/lazy-to-text' }));
    applyLanguage('en');
  });

  it('labels the macOS application-menu roles itself, in both languages (QA-SHELL-F1)', () => {
    const app = (lang) => menuTemplate(lang, { isMac: true, isPackaged: true })[0].submenu;
    const label = (items, role) => items.find((i) => i.role === role).label;
    expect(['about', 'hide', 'hideOthers', 'unhide'].map((r) => label(app('ru'), r)))
      .toEqual(['О приложении Lazy to Text', 'Скрыть Lazy to Text', 'Скрыть остальные', 'Показать все']);
    expect(['about', 'hide', 'hideOthers', 'unhide'].map((r) => label(app('en'), r)))
      .toEqual(['About Lazy to Text', 'Hide Lazy to Text', 'Hide Others', 'Show All']);
  });

  it('serves the file handshake only to the app and clears the queue on a pull (QA-SHELL-F2)', async () => {
    expect(listeners.has('l2t:ready')).toBe(true);
    expect(listeners.has('l2t:file-ack')).toBe(true);
    expect(handlers.has('l2t:pending-files')).toBe(true);
  });

  it('is rebuilt in the language the runtime reports, and again when it changes back', () => {
    const { applyLanguage, currentLanguage } = require(join(import.meta.dirname, '..', 'electron', 'main.cjs'))._internals;
    electron.Menu.setApplicationMenu.mockClear();
    applyLanguage('ru');
    expect(currentLanguage()).toBe('ru');
    expect(JSON.stringify(electron.Menu.setApplicationMenu.mock.calls.at(-1)[0])).toContain('Окно');
    electron.Menu.setApplicationMenu.mockClear();
    applyLanguage('ru');
    expect(electron.Menu.setApplicationMenu).not.toHaveBeenCalled();
    applyLanguage('en');
    expect(currentLanguage()).toBe('en');
    expect(JSON.stringify(electron.Menu.setApplicationMenu.mock.calls.at(-1)[0])).toContain('Window');
  });

  it('keeps Reload and DevTools out of a packaged app', () => {
    const view = (packaged) => find(menuTemplate('en', { isMac: false, isPackaged: packaged }), 'View').submenu.map((i) => i.role);
    expect(view(true)).not.toContain('reload');
    expect(view(true)).not.toContain('toggleDevTools');
    expect(view(false)).toContain('toggleDevTools');
  });
});

describe('quit and relaunch', () => {
  it('a relaunch restarts the app and a quit after it is not a no-op', async () => {
    electron.app.exit.mockClear();
    electron.app.relaunch.mockClear();
    listeners.get('l2t:relaunch')(event);
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
    expect(electron.app.relaunch).toHaveBeenCalledTimes(1);
    expect(electron.app.releaseSingleInstanceLock).toHaveBeenCalled();
    expect(electron.app.exit).toHaveBeenCalledWith(0);
    // The quit that follows (the menu, the page) joins the one already
    // running instead of returning at its first line.
    listeners.get('l2t:quit')(event);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
    expect(electron.app.relaunch).toHaveBeenCalledTimes(1);
  });
});
