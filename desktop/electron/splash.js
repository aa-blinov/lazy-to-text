'use strict';
// The start-up page. It draws whatever state the main process hands it: a
// loading message while the runtime starts, or the reason it did not, with
// Retry and Quit. All text arrives in the state, so there is no catalogue
// here. The first state is in the URL's fragment (#<json>), later ones come over IPC.

(function () {
  const $ = (id) => document.getElementById(id);

  const HEX = /^#[0-9a-fA-F]{6}$/;
  // The user's palette, in the mode the window is in: the CSS holds the
  // defaults, these override them.
  function paint(c) {
    if (!c || typeof c !== 'object') return;
    const style = document.documentElement.style;
    const roles = { bg: '--bg', ink: '--ink', muted: '--muted', line: '--line', accent: '--accent', danger: '--danger', panel: '--panel' };
    for (const key of Object.keys(roles)) {
      if (HEX.test(c[key])) style.setProperty(roles[key], c[key]);
    }
    style.colorScheme = c.dark ? 'dark' : 'light';
  }

  function draw(state) {
    if (!state || typeof state !== 'object') return;
    paint(state.colours);
    const failed = state.mode === 'error';
    document.documentElement.lang = state.lang === 'ru' ? 'ru' : 'en';
    $('root').classList.toggle('error', failed);
    $('root').setAttribute('role', failed ? 'alert' : 'status');
    $('spinner').hidden = failed;
    $('title').textContent = state.title || '';
    $('body').textContent = failed ? '' : (state.body || '');
    $('body').hidden = failed || !state.body;
    $('message').textContent = state.message || '';
    $('message').hidden = !failed || !state.message;
    $('detailsText').textContent = state.detail || '';
    $('detailsLabel').textContent = state.labels ? state.labels.details : '';
    $('details').hidden = !failed || !state.detail;
    $('logPath').textContent = state.logPath || '';
    $('logLabel').textContent = state.labels ? state.labels.log : '';
    $('log').hidden = !failed || !state.logPath;
    $('actions').hidden = !failed;
    if (state.labels) {
      $('retry').textContent = state.labels.retry;
      $('quit').textContent = state.labels.quit;
    }
    document.title = 'Lazy to Text';
    if (failed) $('retry').focus();
  }

  const bridge = window.l2tSplash;
  $('retry').addEventListener('click', () => {
    $('retry').disabled = true;
    if (bridge) bridge.retry();
  });
  $('quit').addEventListener('click', () => bridge && bridge.quit());
  if (bridge) {
    bridge.onColours(paint);
    bridge.onState((state) => {
      $('retry').disabled = false;
      draw(state);
    });
  }

  try {
    const raw = decodeURIComponent(location.hash.slice(1));
    if (raw) draw(JSON.parse(raw));
  } catch {
    // an unreadable first state: the next one over IPC fills the page
  }
})();
