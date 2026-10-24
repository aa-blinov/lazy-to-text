// Runs before the first paint, from its own file because the page policy
// allows no inline script. It gives <html> the palette and the light or dark
// mode the user last had, so a window never opens in the wrong colours and
// then flips: the app proper needs the runtime's answer to know them, and
// that arrives after the first paint. The values are written by
// src/lib/theme.js each time the theme is applied.
(function () {
  var palettes = ['gruvbox', 'github', 'dracula', 'nord', 'solarized', 'catppuccin'];
  var root = document.documentElement;
  try {
    var look = JSON.parse(localStorage.getItem('l2t.look') || 'null') || {};
    var palette = palettes.indexOf(look.palette) >= 0 ? look.palette : palettes[0];
    var dark = look.theme === 'dark' ||
      (look.theme !== 'light' && typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches);
    root.setAttribute('data-theme', palette);
    root.setAttribute('data-mode', dark ? 'dark' : 'light');
    var scale = Number(localStorage.getItem('l2t.scale'));
    if (scale >= 0.85 && scale <= 1.75 && scale !== 1) root.style.fontSize = scale * 100 + '%';
  } catch (e) {
    // No storage (a private window, a test renderer): the page's own defaults stand.
    if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches) {
      root.setAttribute('data-mode', 'dark');
    }
  }
})();
