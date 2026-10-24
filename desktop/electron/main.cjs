'use strict';
// Electron main process: owns windows, the tray and native dialogs, and
// keeps the Python runtime alive. It makes no product decisions; those
// are in the runtime and the renderer.

const path = require('node:path');
const {
  app, BrowserWindow, Menu, nativeTheme, ipcMain, dialog, shell, clipboard,
} = require('electron');
const { Backend } = require('./backend.cjs');
const windows = require('./windows.cjs');

const DEV = Boolean(process.env.L2T_DEV);
const PRELOAD = path.join(__dirname, 'preload.cjs');

let backend = null;
let quitting = false;
let startupError = null;
const pendingFiles = [];

app.setName('Lazy to Text');

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

function fileArgs(argv) {
  return argv.slice(app.isPackaged ? 1 : 2).filter((a) => !a.startsWith('-') && require('node:fs').existsSync(a));
}

app.on('second-instance', (_event, argv) => {
  windows.showMain();
  for (const file of fileArgs(argv)) deliverFile(file);
});

app.on('open-file', (event, file) => {
  event.preventDefault();
  deliverFile(file);
});

function deliverFile(file) {
  const main = windows.getMain();
  if (main && !main.webContents.isLoading()) {
    windows.showMain();
    main.webContents.send('l2t:file-open', file);
  } else {
    pendingFiles.push(file);
  }
}

function rendererUrl(page) {
  return DEV ? `http://127.0.0.1:5173/${page}` : null;
}

async function boot() {
  nativeTheme.themeSource = 'system';
  backend = new Backend(app);
  backend.onExit = (code) => {
    if (quitting) return;
    startupError = `The backend stopped (exit code ${code}).`;
    const main = windows.getMain();
    if (main) main.webContents.send('l2t:backend-exit', { code });
  };

  try {
    await backend.start();
  } catch (err) {
    startupError = err.code === 'already_running'
      ? 'Another copy of Lazy to Text is already running. Use its tray icon, or quit it first.'
      : String(err.message || err);
    if (err.code === 'already_running') {
      dialog.showErrorBox('Lazy to Text', startupError);
      app.exit(0);
      return;
    }
  }

  windows.configure({ preload: PRELOAD, rendererUrl, distDir: path.join(__dirname, '..', 'dist-renderer'), backend });
  const main = windows.createMain();
  main.webContents.once('did-finish-load', () => {
    for (const file of pendingFiles.splice(0)) main.webContents.send('l2t:file-open', file);
  });
  if (process.env.L2T_SELFTEST_DROP && process.env.L2T_SCREENSHOT) selftestDrop(main, process.env.L2T_SELFTEST_DROP, process.env.L2T_SCREENSHOT);
  else if (process.env.L2T_SCREENSHOT) captureAndExit(main, process.env.L2T_SCREENSHOT);
  windows.startOverlayFeed();
  installMenu();
  for (const file of fileArgs(process.argv)) pendingFiles.push(file);
}

// Verification aid: L2T_SCREENSHOT=/path.png renders the window once, saves
// it and quits, so a screen can be checked without a person at the machine.
function captureAndExit(win, file) {
  const fs = require('node:fs');
  win.webContents.once('did-finish-load', () => {
    // L2T_SCREEN=<screen id> opens that screen first, for the site's screenshots.
    if (process.env.L2T_SCREEN) {
      setTimeout(() => win.webContents.send('l2t:navigate', process.env.L2T_SCREEN), 2500);
    }
    setTimeout(async () => {
      if (process.env.L2T_SCREEN) await new Promise((r) => setTimeout(r, 1500));
      const image = await win.webContents.capturePage();
      fs.writeFileSync(file, image.toPNG());
      fs.writeFileSync(`${file}.txt`, await win.webContents.executeJavaScript('document.body.innerText'));
      quit();
    }, Number(process.env.L2T_SCREENSHOT_DELAY || 3500));
  });
}

// Verification aid: L2T_SELFTEST_DROP=/path/to/audio performs a real drag and
// drop of that file onto the window through the DevTools protocol, waits,
// saves a screenshot to L2T_SCREENSHOT and quits. It exercises the same
// path a user's drop takes (drag events, File, webUtils.getPathForFile).
function selftestDrop(win, file, shot) {
  const fs = require('node:fs');
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
      }, Number(process.env.L2T_SELFTEST_WAIT || 5000));
    }, Number(process.env.L2T_SELFTEST_DELAY || 9000));
  });
}

function installMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: 'Settings…', accelerator: 'CmdOrCtrl+,', click: () => navigate('settings') },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' },
        { label: 'Quit Lazy to Text', accelerator: 'CmdOrCtrl+Q', click: () => quit() },
      ],
    }] : [{
      label: 'Lazy to Text',
      submenu: [
        { label: 'Settings…', accelerator: 'CmdOrCtrl+,', click: () => navigate('settings') },
        { type: 'separator' },
        { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => quit() },
      ],
    }]),
    { label: 'Edit', submenu: [
      { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
    ] },
    { label: 'View', submenu: [
      { role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function navigate(id) {
  windows.showMain();
  const main = windows.getMain();
  if (main) main.webContents.send('l2t:navigate', id);
}

async function quit() {
  if (quitting) return;
  quitting = true;
  windows.destroyAll();
  if (backend) await backend.stop();
  app.exit(0);
}

app.whenReady().then(boot);
app.on('before-quit', (event) => {
  if (!quitting) {
    event.preventDefault();
    quit();
  }
});
app.on('activate', () => windows.showMain());
app.on('window-all-closed', () => {
  // The tray keeps the app alive; without one, closing the window quits.
  if (!windows.hasTray()) quit();
});

// ---- IPC -------------------------------------------------------------------

ipcMain.handle('l2t:connection', () => {
  if (!backend || !backend.connection) throw new Error(startupError || 'The backend is not running.');
  return backend.connection;
});

ipcMain.on('l2t:theme', (_e, choice) => {
  nativeTheme.themeSource = ['light', 'dark'].includes(choice) ? choice : 'system';
});

ipcMain.handle('l2t:dialog:open-file', async (event, options = {}) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    properties: ['openFile'],
    filters: options.filters,
    title: options.title,
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('l2t:dialog:open-directory', async (event, options = {}) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: options.defaultPath,
    title: options.title,
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('l2t:dialog:save-file', async (event, options = {}) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showSaveDialog(win, {
    defaultPath: options.defaultPath,
    filters: options.filters,
    title: options.title,
  });
  return result.canceled ? null : result.filePath;
});

ipcMain.handle('l2t:dialog:confirm', async (event, options = {}) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const buttons = options.buttons || ['OK', 'Cancel'];
  const result = await dialog.showMessageBox(win, {
    type: options.type || 'question',
    message: options.message || '',
    detail: options.detail || '',
    buttons,
    defaultId: options.defaultId ?? 0,
    cancelId: options.cancelId ?? buttons.length - 1,
    noLink: true,
  });
  return result.response;
});

ipcMain.handle('l2t:shell:open-external', (_e, url) => {
  // Only web links: a page must not be able to launch an arbitrary protocol handler.
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) return shell.openExternal(url);
  return false;
});

ipcMain.handle('l2t:shell:show-item', (_e, target) => {
  if (typeof target === 'string' && path.isAbsolute(target)) shell.showItemInFolder(target);
});

ipcMain.handle('l2t:clipboard:write', (_e, text) => {
  clipboard.writeText(String(text ?? ''));
  return true;
});

ipcMain.on('l2t:window:show', () => windows.showMain());
ipcMain.on('l2t:quit', () => quit());
ipcMain.on('l2t:relaunch', () => {
  quitting = true;
  app.relaunch();
  quit();
});
