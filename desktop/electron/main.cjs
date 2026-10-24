'use strict';
// Electron main process: owns windows, the tray and native dialogs, and
// keeps the Python runtime alive. It makes no product decisions; those
// are in the runtime and the renderer.
//
// What it does decide is what the user sees when the runtime is not there:
// a start-up window while it starts, an error window with Retry when it
// cannot, and, once it dies under a running window, a message to every
// window, an idle capsule and tray, and a Restart that works.

const path = require('node:path');
const fs = require('node:fs');
const {
  app, BrowserWindow, Menu, nativeTheme, ipcMain, dialog, shell, clipboard, protocol,
} = require('electron');
const env = require('./env.cjs');
const guard = require('./guard.cjs');
const strings = require('./strings.cjs');
const { Backend, StartError, guessLogPath, START_TIMEOUT_MS } = require('./backend.cjs');
const windows = require('./windows.cjs');

const DEV = env.dev(app);
const PRELOAD = path.join(__dirname, 'preload.cjs');
const SPLASH_PRELOAD = path.join(__dirname, 'splash-preload.cjs');
const DIST_DIR = path.join(__dirname, '..', 'dist-renderer');

// 'starting' until the runtime has said it is listening, then 'ready'; 'dead'
// once it has gone (a window may still be up); 'failed' when it never started.
let phase = 'starting';
let backend = null;
let lastFailure = null;
let lastExit = null;
let restartPromise = null;
let quitPromise = null;
let relaunchRequested = false;
let verifyingStream = false;
let focusRefreshAt = 0;
const pendingFiles = [];

// The window is served from its own scheme, not file://, so the file:// fuse can be off.
protocol.registerSchemesAsPrivileged([{
  scheme: guard.APP_SCHEME,
  privileges: { standard: true, secure: true, supportFetchAPI: true },
}]);

app.setName('Lazy to Text');

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.exit(0);

function fileArgs(argv) {
  return argv.slice(app.isPackaged ? 1 : 2).filter((a) => a && !a.startsWith('-') && fs.existsSync(a));
}

app.on('second-instance', (_event, argv) => {
  showSomething();
  for (const file of fileArgs(argv)) deliverFile(file);
});

// Delivered at any time, including before the app is ready: queued until a
// window can take it.
app.on('open-file', (event, file) => {
  event.preventDefault();
  deliverFile(file);
});

function deliverFile(file) {
  const win = windows.getMain();
  if (win && !win.webContents.isLoading()) {
    windows.showMain();
    windows.sendToApp(win.webContents, 'l2t:file-open', file);
  } else {
    pendingFiles.push(file);
  }
}

/** Bring forward whatever there is: the window, or the start-up page. */
function showSomething() {
  if (windows.getMain()) windows.showMain();
  else if (windows.getSplash()) windows.getSplash().show();
  else windows.showMain();
}

// ---- language --------------------------------------------------------------

function applyLanguage(value) {
  const next = strings.normalise(value);
  const changed = next !== languageNow;
  languageNow = next;
  windows.setLanguage(next);
  if (changed) installMenu();
}

/** The runtime's own idea of the language and where its log is; best effort. */
async function refreshFromSnapshot() {
  if (!backend || phase !== 'ready') return;
  const snapshot = await backend.snapshot();
  if (!snapshot) return;
  if (typeof snapshot.log_path === 'string' && snapshot.log_path) backend.logPath = snapshot.log_path;
  const language = snapshot.config && snapshot.config.ui && snapshot.config.ui.language;
  if (language) applyLanguage(language);
}

// ---- start, supervise, restart --------------------------------------------

/** A message for a person from a start failure, with the raw detail kept apart. */
function describeFailure(err) {
  const s = strings.forLanguage(currentLanguage()).startFailures;
  if (err instanceof StartError) {
    if (err.kind === 'missing') return s.missing.replace('{path}', String(err.message).replace(/^The engine is missing: /, ''));
    if (err.kind === 'exited') return strings.format(s.exited, { code: err.code ?? '?' });
    if (err.kind === 'timeout') return strings.format(s.timeout, { seconds: Math.round(START_TIMEOUT_MS / 1000) });
    if (err.kind === 'already_running') return strings.forLanguage(currentLanguage()).alreadyRunning;
    return err.message || s.generic;
  }
  return (err && err.message) || s.generic;
}

let languageNow = strings.normalise(app.getLocale());
function currentLanguage() {
  return languageNow;
}

async function startEngine() {
  phase = 'starting';
  lastFailure = null;
  try {
    const connection = await backend.start();
    phase = 'ready';
    lastExit = null;
    await refreshFromSnapshot();
    return connection;
  } catch (err) {
    phase = 'failed';
    lastFailure = {
      message: describeFailure(err),
      detail: err instanceof StartError ? err.detail : '',
      kind: err instanceof StartError ? err.kind : 'generic',
    };
    throw err;
  }
}

function logPath() {
  return (backend && backend.logPath) || guessLogPath(app);
}

function showStartFailure() {
  windows.showSplash('error', {
    message: lastFailure ? lastFailure.message : '',
    detail: lastFailure ? lastFailure.detail : '',
    logPath: logPath(),
  });
}

async function alreadyRunning() {
  const s = strings.forLanguage(currentLanguage());
  app.focus({ steal: true });
  windows.closeSplash();
  await dialog.showMessageBox({
    type: 'info',
    title: s.appName,
    message: s.appName,
    detail: s.alreadyRunning,
    buttons: ['OK'],
  });
  app.exit(0);
}

async function boot() {
  nativeTheme.themeSource = 'system';
  windows.hardenSession();
  registerAppProtocol();

  guard.configure({ dev: DEV });
  windows.configure({
    preload: PRELOAD,
    splashPreload: SPLASH_PRELOAD,
    stateFile: path.join(app.getPath('userData'), 'window-state.json'),
    get backend() { return backend; },
    onNeedMain: () => (phase === 'ready' || phase === 'dead' ? openMain() : null),
    onMainClosed: () => quit(),
    onSplashClosed: () => { if (phase !== 'ready') quit(); },
    onMainFocus: () => {
      if (Date.now() - focusRefreshAt < 5000) return;
      focusRefreshAt = Date.now();
      refreshFromSnapshot();
    },
    onStreamLost: () => verifyStream(),
    onRestartEngine: () => { restartEngine().catch(() => {}); },
    onQuit: () => quit(),
  });

  backend = new Backend(app);
  backend.onExit = (code, signal) => engineDied({ code, signal });
  // The system's language until the runtime says which one the user chose.
  windows.setLanguage(languageNow);
  installMenu();

  // Visible at once: a cold start can take a minute, and a blank dock icon
  // reads as a launch that did not happen.
  windows.showSplash('loading');

  try {
    await startEngine();
  } catch (err) {
    if (err instanceof StartError && err.kind === 'already_running') {
      await alreadyRunning();
      return;
    }
    showStartFailure();
    return;
  }
  proceedAfterStart();
}

/** The runtime is up for the first time: open the real window. */
function proceedAfterStart() {
  windows.startOverlayFeed();
  const win = openMain();
  win.once('ready-to-show', () => windows.closeSplash());
  // A window that never reports ready must not leave the splash up forever.
  setTimeout(() => windows.closeSplash(), 15000).unref?.();
  for (const file of fileArgs(process.argv)) pendingFiles.push(file);
  runSelftests(win);
}

let mainCreated = false;
function openMain() {
  const existing = windows.getMain();
  if (existing) return existing;
  const win = windows.createMain();
  win.webContents.once('did-finish-load', () => {
    for (const file of pendingFiles.splice(0)) windows.sendToApp(win.webContents, 'l2t:file-open', file);
  });
  if (mainCreated) win.once('ready-to-show', () => windows.closeSplash());
  mainCreated = true;
  return win;
}

/** The runtime process is gone, by any route. */
function engineDied(info) {
  if (quitPromise || phase !== 'ready') return;
  phase = 'dead';
  lastExit = { code: info.code ?? null, signal: info.signal ?? null };
  windows.engineLost();
  windows.broadcast('l2t:backend-exit', lastExit);
  const win = windows.getMain();
  // Hidden to the tray: the user must be able to see what happened, without
  // taking the focus from whatever they are working in.
  if (win && !win.isVisible()) win.showInactive();
}

/**
 * The event stream ended or could not be opened. The child process exiting
 * is reported on its own; this is for a runtime that is alive and silent.
 * It is declared dead only after it has failed to answer /health three
 * times, because killing a slow but healthy engine loses a dictation.
 */
async function verifyStream() {
  if (verifyingStream || phase !== 'ready' || quitPromise) return;
  verifyingStream = true;
  try {
    for (let i = 0; i < 3; i += 1) {
      if (phase !== 'ready' || !backend.alive()) return;
      if (await backend.healthy(4000)) return;
      await new Promise((r) => setTimeout(r, 1000));
    }
    if (phase !== 'ready') return;
    await backend.kill();
    engineDied({ code: null, signal: 'SIGKILL' });
  } finally {
    verifyingStream = false;
  }
}

/** Start the runtime again. One attempt at a time; rejects with a readable message. */
function restartEngine() {
  if (restartPromise) return restartPromise;
  restartPromise = (async () => {
    if (phase === 'ready') {
      // A window that thinks the engine is gone while it answers (a dropped
      // stream, say) is not a reason to stop an engine that may be recording.
      if (backend.alive() && await backend.healthy(2000)) {
        return { port: backend.connection.port, token: backend.connection.token };
      }
      windows.engineLost();
    }
    await backend.stop();
    try {
      const connection = await startEngine();
      windows.engineBack(connection);
      const payload = { port: connection.port, token: connection.token };
      windows.broadcast('l2t:backend-restarted', payload);
      return payload;
    } catch (err) {
      phase = 'dead';
      throw new Error(lastFailure ? lastFailure.message : describeFailure(err));
    }
  })().finally(() => { restartPromise = null; });
  return restartPromise;
}

// ---- verification aids (only with --l2t-selftest) --------------------------

function runSelftests(win) {
  const out = env.hook('L2T_SELFTEST_OUT');
  const dialogKind = env.hook('L2T_SELFTEST_DIALOG');
  const drop = env.hook('L2T_SELFTEST_DROP');
  const shot = env.hook('L2T_SCREENSHOT');
  if (dialogKind && out) selftestDialog(win, dialogKind, out);
  else if (drop && shot) selftestDrop(win, drop, shot);
  else if (shot) captureAndExit(win, shot);
}

// L2T_SCREENSHOT=/path.png renders the window once, saves it and quits, so a
// screen can be checked without a person at the machine.
function captureAndExit(win, file) {
  win.webContents.once('did-finish-load', () => {
    // L2T_SCREEN=<screen id> opens that screen first, for the site's screenshots.
    const screen = env.hook('L2T_SCREEN');
    if (screen) setTimeout(() => windows.sendToApp(win.webContents, 'l2t:navigate', screen), 2500);
    setTimeout(async () => {
      if (screen) await new Promise((r) => setTimeout(r, 1500));
      const image = await win.webContents.capturePage();
      fs.writeFileSync(file, image.toPNG());
      fs.writeFileSync(`${file}.txt`, await win.webContents.executeJavaScript('document.body.innerText'));
      quit();
    }, Number(env.hook('L2T_SCREENSHOT_DELAY') || 3500));
  });
}

// L2T_SELFTEST_DROP=/path/to/audio performs a real drag and drop of that file
// onto the window through the DevTools protocol, waits, saves a screenshot to
// L2T_SCREENSHOT and quits. It exercises the same path a user's drop takes.
function selftestDrop(win, file, shot) {
  win.webContents.once('did-finish-load', () => {
    setTimeout(async () => {
      const dbg = win.webContents.debugger;
      dbg.attach('1.3');
      const point = { x: 600, y: 360 };
      const data = { items: [], files: [file], dragOperationsMask: 1 };
      for (const type of ['dragEnter', 'dragOver', 'drop']) {
        await dbg.sendCommand('Input.dispatchDragEvent', { type, ...point, data });
      }
      setTimeout(async () => {
        const image = await win.webContents.capturePage();
        fs.writeFileSync(shot, image.toPNG());
        quit();
      }, Number(env.hook('L2T_SELFTEST_WAIT') || 5000));
    }, Number(env.hook('L2T_SELFTEST_DELAY') || 9000));
  });
}

// L2T_SELFTEST_DIALOG=confirm|open|save opens that native dialog through the
// same bridge a page uses (window.l2t.dialog), writes what came back to
// L2T_SELFTEST_OUT and quits. A script presses the keys.
function selftestDialog(win, kind, out) {
  const savePath = JSON.stringify(env.hook('L2T_SELFTEST_SAVE') || 'selftest.txt');
  const calls = {
    confirm: "window.l2t.dialog.confirm({ message: 'Delete this entry?', detail: 'selftest', buttons: ['Delete', 'Cancel'], defaultId: 0, cancelId: 1 })",
    open: "window.l2t.dialog.openFile({ title: 'selftest open' })",
    save: `window.l2t.dialog.saveFile({ title: 'selftest save', defaultPath: ${savePath} })`,
  };
  win.webContents.once('did-finish-load', () => {
    setTimeout(async () => {
      app.focus({ steal: true });
      win.show();
      win.focus();
      const result = await win.webContents.executeJavaScript(calls[kind]);
      fs.writeFileSync(out, JSON.stringify({ kind, result }));
      quit();
    }, 4000);
  });
}

// ---- menu ------------------------------------------------------------------

const SCREEN_IDS = ['transcribe', 'models', 'history', 'postprocessing', 'settings', 'logs'];

function menuTemplate(lang, { isMac, isPackaged }) {
  const s = strings.forLanguage(lang);
  const screens = SCREEN_IDS.map((id, index) => ({
    label: s.screens[id],
    accelerator: `CmdOrCtrl+${index + 1}`,
    click: () => navigate(id),
  }));
  const zoomWindow = () => {
    const win = windows.getMain();
    if (!win) return;
    if (win.isMaximized()) win.unmaximize();
    else win.maximize();
  };
  return [
    ...(isMac ? [{
      label: s.appName,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: s.settings, accelerator: 'CmdOrCtrl+,', click: () => navigate('settings') },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' },
        { label: s.quitApp, accelerator: 'CmdOrCtrl+Q', click: () => quit() },
      ],
    }] : [{
      label: s.appName,
      submenu: [
        { label: s.settings, accelerator: 'CmdOrCtrl+,', click: () => navigate('settings') },
        { type: 'separator' },
        { label: s.quit, accelerator: 'CmdOrCtrl+Q', click: () => quit() },
      ],
    }]),
    { label: s.edit, submenu: [
      { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
    ] },
    { label: s.view, submenu: [
      ...(isPackaged ? [] : [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }]),
      { role: 'togglefullscreen' },
      { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
    ] },
    { label: s.window, submenu: [
      { label: s.minimize, accelerator: 'CmdOrCtrl+M', role: 'minimize' },
      isMac ? { label: s.zoom, role: 'zoom' } : { label: s.zoom, click: zoomWindow },
      // Closing the window hides it to the tray; with no tray it ends the app.
      ...(isMac ? [{ label: s.close, accelerator: 'CmdOrCtrl+W', role: 'close' }] : []),
      { type: 'separator' },
      ...screens,
      ...(isMac ? [{ type: 'separator' }, { label: s.bringAllToFront, role: 'front' }] : []),
    ] },
  ];
}

function installMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate(currentLanguage(), {
    isMac: process.platform === 'darwin',
    isPackaged: app.isPackaged,
  })));
}

function navigate(id) {
  windows.showMain();
  const main = windows.getMain();
  if (main) windows.sendToApp(main.webContents, 'l2t:navigate', id);
}

// ---- quit ------------------------------------------------------------------

/** One quit, however many times it is asked for; a relaunch is a quit that starts the app again. */
function quit() {
  if (quitPromise) return quitPromise;
  quitPromise = (async () => {
    windows.destroyAll();
    if (backend) await backend.stop();
    if (relaunchRequested) {
      app.releaseSingleInstanceLock();
      app.relaunch();
    }
    app.exit(0);
  })();
  return quitPromise;
}

if (gotLock) app.whenReady().then(boot);
app.on('before-quit', (event) => {
  if (!quitPromise) {
    event.preventDefault();
    quit();
  }
});
app.on('activate', () => showSomething());
app.on('window-all-closed', () => {
  // The tray keeps the app alive; without one, closing the last window quits.
  if (!windows.hasTray()) quit();
});

// Nothing in the app opens a window or embeds a page except through the
// handlers above; deny by default for every web contents that appears.
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
});

function registerAppProtocol() {
  const types = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.woff2': 'font/woff2', '.woff': 'font/woff', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
    '.map': 'application/json',
  };
  protocol.handle(guard.APP_SCHEME, async (request) => {
    let url;
    try {
      url = new URL(request.url);
    } catch {
      return new Response('', { status: 400 });
    }
    if (url.host !== guard.APP_HOST) return new Response('', { status: 404 });
    const name = url.pathname.replace(/^\//, '');
    // The start-up page lives beside this file; everything else is the renderer build,
    // which in development comes from the Vite server instead.
    let file = null;
    if (guard.SPLASH_FILES.has(name)) file = path.join(__dirname, name);
    else if (!DEV) file = guard.resolveInside(DIST_DIR, url.pathname);
    if (!file) return new Response('', { status: DEV ? 404 : 403 });
    try {
      const data = await fs.promises.readFile(file);
      return new Response(data, { headers: { 'content-type': types[path.extname(file).toLowerCase()] || 'application/octet-stream' } });
    } catch {
      return new Response('', { status: 404 });
    }
  });
}

// ---- IPC -------------------------------------------------------------------
//
// Every handler checks who is asking: a frame of one of the app's own
// windows, showing one of the app's own pages. A page that got somewhere
// else (a navigation that slipped through, a second window) has no bridge.

function fromApp(event) {
  const frame = event.senderFrame;
  return Boolean(frame) && windows.isRendererContents(event.sender) && guard.isRendererUrl(frame.url);
}

function fromSplash(event) {
  const frame = event.senderFrame;
  return Boolean(frame) && windows.isSplashContents(event.sender) && guard.isSplashUrl(frame.url);
}

function handle(channel, fn) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!fromApp(event)) throw new Error('Not allowed.');
    return fn(event, ...args);
  });
}

function listen(channel, fn) {
  ipcMain.on(channel, (event, ...args) => {
    if (!fromApp(event)) return;
    fn(event, ...args);
  });
}

const isString = (v, max = 4096) => typeof v === 'string' && v.length <= max && !v.includes('\0');

/** An absolute path that is already in its normal form, so it names what it appears to. */
function isCleanAbsolutePath(p) {
  return isString(p) && p.length > 0 && path.isAbsolute(p) && path.normalize(p) === p;
}

function cleanText(value, max) {
  return isString(value, max) ? value : undefined;
}

function cleanFilters(filters) {
  if (!Array.isArray(filters)) return undefined;
  const out = [];
  for (const f of filters.slice(0, 20)) {
    if (!f || !isString(f.name, 100) || !Array.isArray(f.extensions)) continue;
    const extensions = f.extensions.filter((e) => isString(e, 20) && /^[A-Za-z0-9*]+$/.test(e)).slice(0, 40);
    if (extensions.length) out.push({ name: f.name, extensions });
  }
  return out.length ? out : undefined;
}

/** A default for the save sheet: a bare file name or a clean absolute path. */
function cleanDefaultPath(value) {
  if (!isString(value, 1024) || !value) return undefined;
  if (isCleanAbsolutePath(value)) return value;
  return /[\\/]/.test(value) ? undefined : value;
}

function cleanDefaultDir(value) {
  return isCleanAbsolutePath(value) ? value : undefined;
}

function optionsOf(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

handle('l2t:connection', () => {
  if (!backend || phase !== 'ready' || !backend.connection) {
    throw new Error(
      phase === 'dead' ? 'The engine is not running.' : ((lastFailure && lastFailure.message) || 'The engine is not running.'),
    );
  }
  return { port: backend.connection.port, token: backend.connection.token };
});

handle('l2t:backend:restart', async () => {
  try {
    return { ok: true, connection: await restartEngine() };
  } catch (err) {
    return { ok: false, message: String((err && err.message) || strings.forLanguage(currentLanguage()).restartFailed) };
  }
});

ipcMain.on('l2t:backend:log-path', (event) => {
  event.returnValue = fromApp(event) ? logPath() : null;
});

listen('l2t:theme', (_e, choice) => {
  nativeTheme.themeSource = ['light', 'dark'].includes(choice) ? choice : 'system';
});

handle('l2t:dialog:open-file', async (event, options) => {
  const o = optionsOf(options);
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters: cleanFilters(o.filters),
    title: cleanText(o.title, 200),
  });
  return result.canceled ? null : result.filePaths[0];
});

handle('l2t:dialog:open-directory', async (event, options) => {
  const o = optionsOf(options);
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: cleanDefaultDir(o.defaultPath),
    title: cleanText(o.title, 200),
  });
  return result.canceled ? null : result.filePaths[0];
});

handle('l2t:dialog:save-file', async (event, options) => {
  const o = optionsOf(options);
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showSaveDialog(win, {
    defaultPath: cleanDefaultPath(o.defaultPath),
    filters: cleanFilters(o.filters),
    title: cleanText(o.title, 200),
  });
  return result.canceled ? null : result.filePath;
});

const BOX_TYPES = ['none', 'info', 'error', 'question', 'warning'];

handle('l2t:dialog:confirm', async (event, options) => {
  const o = optionsOf(options);
  const win = BrowserWindow.fromWebContents(event.sender);
  const given = Array.isArray(o.buttons) ? o.buttons.filter((b) => isString(b, 60)).slice(0, 4) : [];
  const buttons = given.length ? given : ['OK', 'Cancel'];
  const inRange = (n) => Number.isInteger(n) && n >= 0 && n < buttons.length;
  const result = await dialog.showMessageBox(win, {
    type: BOX_TYPES.includes(o.type) ? o.type : 'question',
    message: cleanText(o.message, 2000) || '',
    detail: cleanText(o.detail, 4000) || '',
    buttons,
    defaultId: inRange(o.defaultId) ? o.defaultId : 0,
    cancelId: inRange(o.cancelId) ? o.cancelId : buttons.length - 1,
    noLink: true,
  });
  return result.response;
});

handle('l2t:shell:open-external', (_e, url) => {
  // Only web links: a page must not be able to launch an arbitrary protocol handler.
  if (!isString(url, 2048) || !/^https?:\/\//i.test(url)) return false;
  try {
    new URL(url);
  } catch {
    return false;
  }
  return shell.openExternal(url);
});

handle('l2t:shell:show-item', (_e, target) => {
  if (isCleanAbsolutePath(target)) shell.showItemInFolder(target);
});

handle('l2t:clipboard:write', (_e, text) => {
  clipboard.writeText(typeof text === 'string' ? text.slice(0, 10 * 1024 * 1024) : '');
  return true;
});

listen('l2t:window:show', () => windows.showMain());
listen('l2t:quit', () => quit());
listen('l2t:relaunch', () => {
  // A relaunch is a quit that asks for the app to start again; it does not
  // mark the app as quitting by itself, so the quit that follows still runs.
  relaunchRequested = true;
  quit();
});

// The start-up page: Retry and Quit, nothing else.
ipcMain.on('l2t:splash:retry', async (event) => {
  if (!fromSplash(event) || phase === 'starting' || phase === 'ready') return;
  windows.showSplash('loading');
  try {
    await startEngine();
  } catch (err) {
    if (err instanceof StartError && err.kind === 'already_running') {
      await alreadyRunning();
      return;
    }
    showStartFailure();
    return;
  }
  proceedAfterStart();
});

ipcMain.on('l2t:splash:quit', (event) => {
  if (fromSplash(event)) quit();
});

module.exports = {
  _internals: { menuTemplate, isCleanAbsolutePath, cleanDefaultPath, cleanFilters, applyLanguage, currentLanguage },
};
