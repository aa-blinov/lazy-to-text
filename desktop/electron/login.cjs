'use strict';
// Starting with the computer. The choice lives in config.yaml
// (ui.start_at_login, written by the runtime); this module only makes the
// operating system agree with it.
//
//   macOS, Windows   app.setLoginItemSettings
//   Linux            an XDG autostart entry in ~/.config/autostart
//
// The app is an application that lives in the tray and answers to global
// hotkeys, so a launch at login must not open a window: `--hidden` (and, on
// macOS, the login-item flags) say so, and the main process reads them back
// with `startedHidden`.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HIDDEN_FLAG = '--hidden';
const DESKTOP_FILE = 'lazy-to-text.desktop';

/** The executable the login item has to start. */
function launchPath({ app, env = process.env, platform = process.platform }) {
  // The portable build runs from a temporary folder it unpacks into on every
  // start; the path to remember is the portable exe itself.
  if (platform === 'win32' && env.PORTABLE_EXECUTABLE_FILE) return env.PORTABLE_EXECUTABLE_FILE;
  // An AppImage is a mounted image: its own path is the stable one.
  if (platform === 'linux' && env.APPIMAGE) return env.APPIMAGE;
  // Asked of Electron: the main process never reads its own binary from the process object (a test holds it to that).
  return app.getPath('exe');
}

/** `Exec=` quoting per the Desktop Entry specification. */
function execLine(file) {
  const quoted = String(file).replace(/(["`$\\])/g, '\\$1').replace(/%/g, '%%');
  return `"${quoted}" ${HIDDEN_FLAG}`;
}

function autostartDir(env = process.env, home = os.homedir()) {
  return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'autostart');
}

function desktopEntry(file, name = 'Lazy to Text') {
  return [
    '[Desktop Entry]',
    'Type=Application',
    `Name=${name}`,
    'Comment=Local speech-to-text',
    `Exec=${execLine(file)}`,
    'Terminal=false',
    'X-GNOME-Autostart-enabled=true',
    '',
  ].join('\n');
}

/**
 * Make the operating system start (or stop starting) the app at login.
 * Returns what was done, for the log and for tests:
 * `{ applied: true, how }` or `{ applied: false, reason }`.
 */
function applyStartAtLogin(enabled, {
  app, platform = process.platform, env = process.env, fsImpl = fs, home = os.homedir(), log = () => {},
}) {
  const on = enabled === true;
  // A development run would register the Electron binary inside node_modules.
  if (!app.isPackaged && !env.L2T_LOGIN_ITEM_FORCE) return { applied: false, reason: 'unpackaged' };
  try {
    if (platform === 'linux') {
      const dir = autostartDir(env, home);
      const file = path.join(dir, DESKTOP_FILE);
      if (on) {
        fsImpl.mkdirSync(dir, { recursive: true });
        fsImpl.writeFileSync(file, desktopEntry(launchPath({ app, env, platform })), { mode: 0o644 });
      } else {
        fsImpl.rmSync(file, { force: true });
      }
      return { applied: true, how: 'xdg-autostart', file };
    }
    if (platform === 'darwin' || platform === 'win32') {
      const settings = { openAtLogin: on };
      if (on) {
        // openAsHidden is honoured up to macOS 12; later systems report
        // wasOpenedAtLogin instead, which startedHidden also reads.
        if (platform === 'darwin') settings.openAsHidden = true;
        settings.args = [HIDDEN_FLAG];
        if (platform === 'win32') settings.path = launchPath({ app, env, platform });
      } else if (platform === 'win32') {
        // Remove the entry the same executable and arguments created.
        settings.path = launchPath({ app, env, platform });
        settings.args = [HIDDEN_FLAG];
      }
      app.setLoginItemSettings(settings);
      return { applied: true, how: 'login-item' };
    }
  } catch (err) {
    log(`Could not change the login item: ${err && err.message}`);
    return { applied: false, reason: 'error', message: String(err && err.message) };
  }
  return { applied: false, reason: 'unsupported' };
}

/** Was this launch made by the login item, meaning: stay in the tray. */
function startedHidden({ argv = process.argv, app, platform = process.platform }) {
  if (argv.includes(HIDDEN_FLAG)) return true;
  if (platform !== 'darwin') return false;
  try {
    const info = app.getLoginItemSettings();
    return Boolean(info && (info.wasOpenedAtLogin || info.wasOpenedAsHidden));
  } catch {
    return false;
  }
}

module.exports = {
  HIDDEN_FLAG, DESKTOP_FILE, applyStartAtLogin, startedHidden, execLine, desktopEntry, autostartDir, launchPath,
};
