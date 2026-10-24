'use strict';
// What counts as one of the app's own pages. Every IPC handler, every
// navigation and every window-open decision asks here, so the answer is
// written once.
//
// A packaged app serves its renderer, and the start-up page, from a custom
// scheme, `l2t-app://app/`, and loads nothing from `file://`. Chromium gives
// `file://` pages extra rights (the "GrantFileProtocolExtraPrivileges" fuse),
// which this app switches off, and in a packaged app a `file://` page inside
// app.asar did not load once it was off. A page on its own scheme also has an
// origin that a Content-Security-Policy and the runtime's CORS check can
// name. An unpackaged app in development loads the Vite server for the
// renderer; the start-up page is on the custom scheme in both.

const path = require('node:path');

const APP_SCHEME = 'l2t-app';
const APP_HOST = 'app';
const DEV_ORIGIN = 'http://127.0.0.1:5173';
const PAGES = new Set(['index.html', 'overlay.html', 'popup.html']);
// The only files served from the main process's own folder rather than the renderer build.
const SPLASH_FILES = new Set(['splash.html', 'splash.js']);

let dev = false;

function configure(options) {
  dev = Boolean(options.dev);
}

/** The start-up page, with its first state in the fragment (a fragment is never part of a path). */
function splashUrl(fragment = '') {
  return `${APP_SCHEME}://${APP_HOST}/splash.html${fragment ? `#${fragment}` : ''}`;
}

function rendererUrl(page) {
  return dev ? `${DEV_ORIGIN}/${page}` : `${APP_SCHEME}://${APP_HOST}/${page}`;
}

function parse(url) {
  try {
    return new URL(String(url));
  } catch {
    return null;
  }
}

/** True for exactly the renderer's pages, and for nothing else. */
function isRendererUrl(url) {
  const u = parse(url);
  if (!u) return false;
  if (dev) return u.origin === DEV_ORIGIN && PAGES.has(u.pathname.slice(1));
  return u.protocol === `${APP_SCHEME}:` && u.host === APP_HOST && PAGES.has(u.pathname.slice(1));
}

/** The start-up / error page; it has its own, smaller bridge. */
function isSplashUrl(url) {
  const u = parse(url);
  return Boolean(u) && u.protocol === `${APP_SCHEME}:` && u.host === APP_HOST && u.pathname === '/splash.html';
}

/** A file under `root` for a request path, or null when it escapes it. */
function resolveInside(root, requestPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(requestPath);
  } catch {
    return null;
  }
  if (decoded.includes('\0')) return null;
  const relative = decoded.replace(/^\/+/, '') || 'index.html';
  const full = path.resolve(root, relative);
  const base = path.resolve(root) + path.sep;
  return full.startsWith(base) ? full : null;
}

module.exports = {
  APP_SCHEME, APP_HOST, DEV_ORIGIN, SPLASH_FILES, configure, rendererUrl, splashUrl, isRendererUrl, isSplashUrl, resolveInside,
};
