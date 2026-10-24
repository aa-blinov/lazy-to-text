'use strict';
// The windows (start-up, main, capsule), the tray, and the rules for when
// the capsule is on screen. The capsule is drawn by the renderer; whether it
// is visible, and on which display, is decided here from runtime events.

const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const {
  BrowserWindow, Tray, Menu, screen, nativeImage, app, shell, session, nativeTheme } = require('electron');
const { connectEvents } = require('./events.cjs');
const guard = require('./guard.cjs');
const geometry = require('./geometry.cjs');
const strings = require('./strings.cjs');
const env = require('./env.cjs');

let cfg = null;
let main = null;
let overlay = null;
let splash = null;
let tray = null;
let stopEvents = null;
let quitFlag = false;
let language = 'en';
let engineStopped = false;
let saveTimer = null;

// The confirmation is up for 3 s in the page (components/capsule/copy.js);
// the window outlives it by a little so the page is never cut off first.
const DELIVERY_MS = 3200;
// Wide enough for the capsule at its own width cap (448 px) plus its gutter;
// the window is transparent and click-through, so the extra width is free.
const OVERLAY_SIZE = { width: 520, height: 96 };
const MAIN_DEFAULT = { width: 1120, height: 760 };
const MAIN_MIN = { width: 900, height: 600 };

let runtimeState = 'idle';
let deliveryUntil = 0;
let deliveryTimer = null;
let anchorDisplayId = null;

/** The kit's Gruvbox paper for the window ground, light or dark, before the page paints. */
function paperColor() {
  return nativeTheme.shouldUseDarkColors ? '#282828' : '#fbf1c7';
}

function configure(options) {
  cfg = options;
}

function setLanguage(value) {
  const next = strings.normalise(value);
  if (next === language) return false;
  language = next;
  refreshTray();
  return true;
}

function t() {
  return strings.forLanguage(language);
}

function webPreferences(preload = cfg.preload) {
  return {
    preload,
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
    allowRunningInsecureContent: false,
    spellcheck: false,
  };
}

// ---- what a window may do --------------------------------------------------

/** Deny permission prompts and every window or webview the page might open. */
function hardenSession() {
  const ses = session.defaultSession;
  if (!ses) return;
  ses.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
}

/**
 * A window shows its own page and nothing else. A link to the web goes to
 * the browser; anything else, a different page or a file, goes nowhere.
 */
function lockdown(win, allowed) {
  const wc = win.webContents;
  const guardNav = (event, url) => {
    if (allowed(url)) return;
    event.preventDefault();
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
  };
  wc.on('will-navigate', guardNav);
  wc.on('will-redirect', guardNav);
  wc.on('will-attach-webview', (event) => event.preventDefault());
  wc.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ---- start-up window -------------------------------------------------------

function splashState(kind, extra = {}) {
  const s = t().splash;
  const base = { lang: language, labels: { retry: s.retry, quit: s.quit, log: s.log, details: s.details } };
  if (kind === 'error') {
    return { ...base, mode: 'error', title: s.errorTitle, message: extra.message || '', detail: extra.detail || '', logPath: extra.logPath || '' };
  }
  return { ...base, mode: 'loading', title: s.loadingTitle, body: s.loadingBody };
}

function showSplash(kind, extra) {
  const state = splashState(kind, extra);
  if (splash && !splash.isDestroyed()) {
    splash.webContents.send('l2t:splash:state', state);
    if (!splash.isVisible()) splash.show();
    return splash;
  }
  splash = new BrowserWindow({
    width: 520,
    height: 320,
    useContentSize: true,
    resizable: false,
    minimizable: true,
    maximizable: false,
    fullscreenable: false,
    show: false,
    title: 'Lazy to Text',
    backgroundColor: paperColor(),
    webPreferences: webPreferences(cfg.splashPreload),
  });
  splash.removeMenu?.();
  lockdown(splash, (url) => guard.isSplashUrl(url));
  splash.once('ready-to-show', () => splash.show());
  splash.on('closed', () => {
    splash = null;
    if (!quitFlag && cfg.onSplashClosed) cfg.onSplashClosed();
  });
  splash.loadURL(guard.splashUrl(encodeURIComponent(JSON.stringify(state))));
  return splash;
}

function closeSplash() {
  if (!splash || splash.isDestroyed()) return;
  const win = splash;
  splash = null;
  // Closing it because the real window is up is not the user closing it.
  win.removeAllListeners('closed');
  win.destroy();
}

function getSplash() {
  return splash && !splash.isDestroyed() ? splash : null;
}

// ---- main window -----------------------------------------------------------

function stateFile() {
  return cfg.stateFile;
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(stateFile(), 'utf8'));
  } catch {
    return null;
  }
}

function saveState() {
  const win = getMain();
  if (!win || win.isMinimized() || win.isFullScreen()) return;
  const bounds = win.isMaximized() ? win.getNormalBounds() : win.getBounds();
  try {
    fs.mkdirSync(path.dirname(stateFile()), { recursive: true });
    fs.writeFileSync(stateFile(), JSON.stringify({ ...bounds, maximized: win.isMaximized() }));
  } catch {
    // losing the window position is not worth an error
  }
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveState, 500);
}

function createMain({ hidden = false } = {}) {
  const isMac = process.platform === 'darwin';
  const primary = screen.getPrimaryDisplay();
  const bounds = geometry.computeBounds({
    saved: readState(),
    displays: screen.getAllDisplays(),
    primary,
    defaults: MAIN_DEFAULT,
    min: MAIN_MIN,
  });
  main = new BrowserWindow({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    minWidth: Math.min(MAIN_MIN.width, primary.workArea.width),
    minHeight: Math.min(MAIN_MIN.height, primary.workArea.height),
    show: false,
    title: 'Lazy to Text',
    backgroundColor: paperColor(),
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 16, y: 14 } : undefined,
    // Windows and Linux: the menu bar appears on Alt, not over the window all the time.
    autoHideMenuBar: !isMac,
    webPreferences: webPreferences(),
  });
  if (bounds.maximized) main.maximize();
  // Started by the login item: stay in the tray. Without a tray there is
  // nothing to bring the window back from, so it opens.
  main.once('ready-to-show', () => { if (!(hidden && hasTray())) main.show(); });
  main.on('resize', scheduleSave);
  main.on('move', scheduleSave);
  main.on('close', (event) => {
    saveState();
    if (quitFlag || !hasTray()) return;
    event.preventDefault();
    main.hide();
  });
  main.on('focus', () => cfg.onMainFocus && cfg.onMainFocus());
  main.on('closed', () => {
    main = null;
    // With no tray there is nothing to bring the window back from: closing it ends the app.
    if (!quitFlag && !hasTray() && cfg.onMainClosed) cfg.onMainClosed();
  });
  lockdown(main, (url) => guard.isRendererUrl(url));
  main.loadURL(guard.rendererUrl('index.html'));
  return main;
}

function getMain() {
  return main && !main.isDestroyed() ? main : null;
}

function showMain() {
  let win = getMain();
  if (!win && cfg.onNeedMain) win = cfg.onNeedMain();
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (process.platform === 'darwin') app.dock?.show();
}

/** Every web contents that belongs to the app's own renderer windows. */
function rendererContents() {
  return [getMain(), overlay && !overlay.isDestroyed() ? overlay : null]
    .filter(Boolean)
    .map((w) => w.webContents)
    .filter((wc) => !wc.isDestroyed());
}

function isRendererContents(wc) {
  return rendererContents().includes(wc);
}

function isSplashContents(wc) {
  const win = getSplash();
  return Boolean(win) && win.webContents === wc;
}

/** The page a web contents has committed, or '' when that cannot be told. */
function currentUrl(wc) {
  try {
    const frame = wc.mainFrame;
    if (frame && typeof frame.url === 'string' && frame.url) return frame.url;
    return typeof wc.getURL === 'function' ? wc.getURL() : '';
  } catch {
    return '';
  }
}

/**
 * Send to one web contents only while it shows one of the app's own pages.
 * The preload is attached to whatever a window ends up loading, so a
 * message (the restart event carries the connection token) must not follow
 * the window to a page that is not ours. True when it was sent.
 */
function sendToApp(wc, channel, payload) {
  if (!wc || wc.isDestroyed() || !guard.isRendererUrl(currentUrl(wc))) return false;
  wc.send(channel, payload);
  return true;
}

/** Send to the main window and the capsule, while each shows an app page. */
function broadcast(channel, payload) {
  for (const wc of rendererContents()) sendToApp(wc, channel, payload);
}

// ---- tray ------------------------------------------------------------------

// macOS gets black-on-transparent "Template" glyphs, which the menu bar
// recolours for light and dark; Windows and Linux get the paper tile with a
// status dot, which reads on any tray colour. scripts/make_icons.py draws both.
function trayImage(state) {
  const name = { model_loading: 'processing' }[state] || (['recording', 'processing'].includes(state) ? state : 'idle');
  const mac = process.platform === 'darwin';
  const file = mac ? `tray_${name}Template.png` : `tray_${name}.png`;
  const img = nativeImage.createFromPath(path.join(__dirname, '..', 'assets', file));
  return mac ? img.resize({ height: 18 }) : img.resize({ height: 20 });
}

/**
 * Whether a tray can show on this Linux desktop. Electron does not throw
 * from `new Tray()` on a desktop with no StatusNotifier host (stock GNOME),
 * so the icon would be created and never seen, and a window hidden "to the
 * tray" would be gone. Ask the session bus whether anyone serves the
 * protocol; when that cannot be answered, assume nobody does, because a
 * window that closes the app is a smaller harm than one nobody can find.
 */
function linuxTrayHost() {
  for (const name of ['org.kde.StatusNotifierWatcher', 'org.freedesktop.StatusNotifierWatcher']) {
    const run = spawnSync('gdbus', [
      'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
      '--method', 'org.freedesktop.DBus.NameHasOwner', name,
    ], { encoding: 'utf8', timeout: 2000 });
    if (run.status === 0 && /true/.test(run.stdout || '')) return true;
  }
  return false;
}

function trayWanted() {
  // A test hook: a desktop with no tray, to see that closing the window then quits.
  if (env.hook('L2T_SELFTEST_NO_TRAY')) return false;
  if (process.platform !== 'linux') return true;
  return cfg.linuxTrayHost ? cfg.linuxTrayHost() : linuxTrayHost();
}

function createTray() {
  if (!trayWanted()) {
    tray = null;
    return;
  }
  try {
    tray = new Tray(trayImage('idle'));
  } catch {
    tray = null;
    return;
  }
  refreshTray();
  if (process.platform !== 'darwin') {
    tray.on('click', showMain);
    tray.on('double-click', showMain);
  }
}

function hasTray() {
  return Boolean(tray) && !tray.isDestroyed();
}

function refreshTray() {
  if (!hasTray()) return;
  const s = t();
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: s.show, click: showMain },
    { label: s.restartEngine, visible: engineStopped, click: () => cfg.onRestartEngine && cfg.onRestartEngine() },
    { type: 'separator' },
    { label: s.quit, click: () => (cfg.onQuit ? cfg.onQuit() : app.quit()) },
  ]));
  tray.setToolTip(engineStopped ? s.tip.stopped : (s.tip[runtimeState] || s.tip.idle));
}

function setTrayState(state) {
  if (!hasTray()) return;
  tray.setImage(trayImage(state));
  tray.setToolTip(t().tip[state] || t().tip.idle);
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
    // An NSPanel on macOS: the window kind that may float over a full-screen app.
    type: process.platform === 'darwin' ? 'panel' : undefined,
    webPreferences: webPreferences(),
  });
  overlay.setIgnoreMouseEvents(true);
  overlay.setAlwaysOnTop(true, 'screen-saver');
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
  lockdown(overlay, (url) => guard.isRendererUrl(url));
  overlay.loadURL(guard.rendererUrl('overlay.html'));
  overlay.on('closed', () => { overlay = null; });
}

/** The display the user is looking at: the one under the pointer. */
function activeDisplay() {
  try {
    return screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  } catch {
    return screen.getPrimaryDisplay();
  }
}

/** The capsule's display: the one it appeared on if it still exists, else the pointer's, else the primary. */
function anchorDisplay() {
  const all = screen.getAllDisplays();
  const kept = anchorDisplayId === null ? null : all.find((d) => d.id === anchorDisplayId);
  const display = kept || activeDisplay() || screen.getPrimaryDisplay();
  anchorDisplayId = display.id;
  return display;
}

function placeOverlay() {
  if (!overlay || overlay.isDestroyed()) return;
  const { workArea } = anchorDisplay();
  // Inside the work area even on a narrow display, with a gutter either side.
  const size = { width: Math.min(OVERLAY_SIZE.width, Math.max(240, workArea.width - 32)), height: OVERLAY_SIZE.height };
  overlay.setBounds(geometry.capsuleBounds(workArea, size));
}

let overlayShown = false;

function wantOverlay() {
  if (engineStopped) return false;
  return runtimeState === 'recording' || runtimeState === 'processing' || Date.now() < deliveryUntil;
}

function syncOverlay() {
  if (!overlay || overlay.isDestroyed()) return;
  const want = wantOverlay();
  if (want && !overlayShown) {
    // Anchored once per appearance: re-anchoring in the middle of a dictation
    // is the jump the Qt capsule used to make. Only a display going away or
    // changing size places it again (see the display handlers below).
    anchorDisplayId = null;
    placeOverlay();
    // A hidden application's windows are not on screen, and showing the
    // capsule would not wake it. Unhide without taking focus.
    if (process.platform === 'darwin' && app.isHidden && app.isHidden()) app.show();
    overlay.showInactive();
    overlay.moveTop();
    overlayShown = true;
  } else if (!want && overlayShown) {
    overlay.hide();
    overlayShown = false;
  }
}

function onDisplaysChanged() {
  if (overlayShown) placeOverlay();
}

function startEventFeed(connection) {
  if (stopEvents) stopEvents();
  stopEvents = connectEvents(connection, {
    state: ({ state }) => {
      runtimeState = state;
      engineStopped = false;
      setTrayState(state);
      syncOverlay();
    },
    delivery: () => {
      deliveryUntil = Date.now() + DELIVERY_MS;
      clearTimeout(deliveryTimer);
      deliveryTimer = setTimeout(syncOverlay, DELIVERY_MS + 50);
      syncOverlay();
    },
    settings: (payload) => { if (cfg.onSettings) cfg.onSettings(payload); },
  }, () => cfg.onStreamLost && cfg.onStreamLost());
}

/** Create the capsule and the tray, and follow the runtime if it is up. */
function startOverlayFeed() {
  createOverlay();
  createTray();
  screen.on('display-removed', onDisplaysChanged);
  screen.on('display-added', onDisplaysChanged);
  screen.on('display-metrics-changed', onDisplaysChanged);
  const connection = cfg.backend && cfg.backend.connection;
  if (connection) startEventFeed(connection);
}

/**
 * The runtime is gone. Nothing is recording any more, so nothing may say so:
 * the capsule goes, the tray returns to idle and says the engine stopped.
 */
function engineLost() {
  if (stopEvents) stopEvents();
  stopEvents = null;
  runtimeState = 'idle';
  deliveryUntil = 0;
  clearTimeout(deliveryTimer);
  engineStopped = true;
  setTrayState('idle');
  refreshTray();
  syncOverlay();
}

/** The runtime is up again (or for the first time): follow it. */
function engineBack(connection) {
  engineStopped = false;
  runtimeState = 'idle';
  setTrayState('idle');
  refreshTray();
  startEventFeed(connection);
}

function destroyAll() {
  quitFlag = true;
  clearTimeout(saveTimer);
  saveState();
  if (stopEvents) stopEvents();
  clearTimeout(deliveryTimer);
  for (const win of [overlay, main, splash]) {
    if (win && !win.isDestroyed()) win.destroy();
  }
  if (hasTray()) tray.destroy();
}

module.exports = {
  configure, hardenSession, showSplash, closeSplash, getSplash, createMain, getMain, showMain,
  startOverlayFeed, engineLost, engineBack, hasTray, destroyAll, setTrayState, setLanguage,
  broadcast, sendToApp, isRendererContents, isSplashContents,
  // For tests.
  _internals: { OVERLAY_SIZE, MAIN_DEFAULT, MAIN_MIN, DELIVERY_MS, linuxTrayHost, wantOverlay, syncOverlay },
};
