'use strict';
// The three windows (main, capsule), the tray, and the rules for when the
// capsule is on screen. The capsule is drawn by the renderer; whether it
// is visible, and on which display, is decided here from runtime events.

const path = require('node:path');
const { BrowserWindow, Tray, Menu, screen, nativeImage, app } = require('electron');
const { connectEvents } = require('./events.cjs');

let cfg = null;
let main = null;
let overlay = null;
let tray = null;
let stopEvents = null;
let quitFlag = false;

// Delivery confirmation stays up this long, then the capsule goes.
const DELIVERY_MS = 2600;
const OVERLAY_SIZE = { width: 360, height: 96 };

let runtimeState = 'idle';
let deliveryUntil = 0;
let deliveryTimer = null;

function configure(options) {
  cfg = options;
}

function load(win, page) {
  const url = cfg.rendererUrl(page);
  if (url) return win.loadURL(url);
  return win.loadFile(path.join(cfg.distDir, page));
}

function webPreferences() {
  return {
    preload: cfg.preload,
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
  };
}

// ---- main window -----------------------------------------------------------

function createMain() {
  const isMac = process.platform === 'darwin';
  main = new BrowserWindow({
    width: 1120,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: 'Lazy to Text',
    backgroundColor: '#fbf1c7',
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 16, y: 14 } : undefined,
    webPreferences: webPreferences(),
  });
  main.once('ready-to-show', () => main.show());
  main.on('close', (event) => {
    if (quitFlag || !hasTray()) return;
    event.preventDefault();
    main.hide();
  });
  main.on('closed', () => { main = null; });
  // A page may not navigate the app window away, nor open windows.
  main.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('http://127.0.0.1:5173') && !url.startsWith('file://')) event.preventDefault();
  });
  main.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });
  load(main, 'index.html');
  return main;
}

function getMain() {
  return main && !main.isDestroyed() ? main : null;
}

function showMain() {
  const win = getMain();
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (process.platform === 'darwin') app.dock?.show();
}

// ---- tray ------------------------------------------------------------------

const TRAY_IMAGES = { idle: 'tray_idle.png', recording: 'tray_recording.png', processing: 'tray_processing.png' };

function trayImage(state) {
  const file = TRAY_IMAGES[state === 'model_loading' ? 'processing' : state] || TRAY_IMAGES.idle;
  const img = nativeImage.createFromPath(path.join(__dirname, '..', 'assets', file));
  return process.platform === 'darwin' ? img.resize({ height: 18 }) : img;
}

function createTray() {
  try {
    tray = new Tray(trayImage('idle'));
  } catch {
    tray = null;
    return;
  }
  tray.setToolTip('Lazy to text');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show window', click: showMain },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]));
  if (process.platform !== 'darwin') {
    tray.on('click', showMain);
    tray.on('double-click', showMain);
  }
}

function hasTray() {
  return Boolean(tray) && !tray.isDestroyed();
}

const TRAY_TIPS = {
  idle: 'Lazy to text',
  recording: 'Lazy to text — recording',
  processing: 'Lazy to text — processing',
  model_loading: 'Lazy to text — loading model',
};

function setTrayState(state) {
  if (!hasTray()) return;
  tray.setImage(trayImage(state));
  tray.setToolTip(TRAY_TIPS[state] || TRAY_TIPS.idle);
}

// ---- capsule ---------------------------------------------------------------

function createOverlay() {
  overlay = new BrowserWindow({
    ...OVERLAY_SIZE,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    focusable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    webPreferences: webPreferences(),
  });
  overlay.setIgnoreMouseEvents(true);
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
  load(overlay, 'overlay.html');
  overlay.on('closed', () => { overlay = null; });
}

/** The display the user is looking at: the one under the pointer. */
function activeDisplay() {
  return screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
}

function placeOverlay() {
  if (!overlay || overlay.isDestroyed()) return;
  const { workArea } = activeDisplay();
  const x = Math.round(workArea.x + (workArea.width - OVERLAY_SIZE.width) / 2);
  const y = Math.round(workArea.y + workArea.height - OVERLAY_SIZE.height - 48);
  overlay.setBounds({ x, y, ...OVERLAY_SIZE });
}

let overlayShown = false;

function wantOverlay() {
  return runtimeState === 'recording' || runtimeState === 'processing' || Date.now() < deliveryUntil;
}

function syncOverlay() {
  if (!overlay || overlay.isDestroyed()) return;
  const want = wantOverlay();
  if (want && !overlayShown) {
    // Placed once per appearance and never again while it is up: re-anchoring
    // in the middle of a dictation is the jump the Qt capsule used to make.
    placeOverlay();
    overlay.showInactive();
    overlayShown = true;
  } else if (!want && overlayShown) {
    overlay.hide();
    overlayShown = false;
  }
}

function startOverlayFeed() {
  const connection = cfg.backend && cfg.backend.connection;
  createOverlay();
  createTray();
  if (!connection) return;
  stopEvents = connectEvents(connection, {
    state: ({ state }) => {
      runtimeState = state;
      setTrayState(state);
      syncOverlay();
    },
    delivery: () => {
      deliveryUntil = Date.now() + DELIVERY_MS;
      clearTimeout(deliveryTimer);
      deliveryTimer = setTimeout(syncOverlay, DELIVERY_MS + 50);
      syncOverlay();
    },
  });
}

function destroyAll() {
  quitFlag = true;
  if (stopEvents) stopEvents();
  clearTimeout(deliveryTimer);
  for (const win of [overlay, main]) {
    if (win && !win.isDestroyed()) win.destroy();
  }
  if (hasTray()) tray.destroy();
}

module.exports = {
  configure, createMain, getMain, showMain, createTray: () => {}, startOverlayFeed,
  hasTray, destroyAll, setTrayState,
};
