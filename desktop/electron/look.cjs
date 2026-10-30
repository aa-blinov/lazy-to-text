'use strict';
// The user's look (palette and light / dark / system) as the shell needs it
// BEFORE the renderer has loaded: the start-up window and the ground of every
// window are painted by the shell, and the renderer only tells it the choice
// once it is up. So the choice is kept in a small file next to the window
// state and read at start, and the colours come from this table.
//
// The table is the kit's own (@monos/ui src/themes.js), cut to the roles the
// shell paints; tests/shell-look.test.js holds it equal to the kit's, so a
// palette change there cannot leave the start-up window behind.

const fs = require('node:fs');

const PALETTES = {
  gruvbox: {
    light: { bg: '#fbf1c7', surface: '#ebdbb2', ink: '#3c3836', inkSoft: '#6a5e55', line: '#d5c4a1', accent: '#458588', danger: '#cc241d' },
    dark: { bg: '#282828', surface: '#3c3836', ink: '#ebdbb2', inkSoft: '#b1a491', line: '#504945', accent: '#83a598', danger: '#fb4934' },
  },
  github: {
    light: { bg: '#ffffff', surface: '#f6f8fa', ink: '#1f2328', inkSoft: '#626972', line: '#d0d7de', accent: '#0969da', danger: '#cf222e' },
    dark: { bg: '#0d1117', surface: '#161b22', ink: '#e6edf3', inkSoft: '#8b949e', line: '#30363d', accent: '#58a6ff', danger: '#f85149' },
  },
  dracula: {
    light: { bg: '#fffbeb', surface: '#f1f1f3', ink: '#1f1f1f', inkSoft: '#5f5a42', line: '#cfcfde', accent: '#036a96', danger: '#cb3a2a' },
    dark: { bg: '#282a36', surface: '#343746', ink: '#f8f8f2', inkSoft: '#adb6d0', line: '#44475a', accent: '#8be9fd', danger: '#ff5555' },
  },
  nord: {
    light: { bg: '#eceff4', surface: '#e5e9f0', ink: '#2e3440', inkSoft: '#4c566a', line: '#d8dee9', accent: '#5e81ac', danger: '#bf616a' },
    dark: { bg: '#2e3440', surface: '#3b4252', ink: '#eceff4', inkSoft: '#b1b6c3', line: '#434c5e', accent: '#81a1c1', danger: '#bf616a' },
  },
  solarized: {
    light: { bg: '#fdf6e3', surface: '#eee8d5', ink: '#556b72', inkSoft: '#56686f', line: '#e0d5c1', accent: '#268bd2', danger: '#dc322f' },
    dark: { bg: '#002b36', surface: '#073642', ink: '#8b9c9e', inkSoft: '#909fa3', line: '#0a4b58', accent: '#268bd2', danger: '#dc322f' },
  },
  catppuccin: {
    light: { bg: '#eff1f5', surface: '#e6e9ef', ink: '#4c4f69', inkSoft: '#5c5f71', line: '#ccd0da', accent: '#1e66f5', danger: '#d20f39' },
    dark: { bg: '#1e1e2e', surface: '#181825', ink: '#cdd6f4', inkSoft: '#9ba0b7', line: '#313244', accent: '#89b4fa', danger: '#f38ba8' },
  },
};

const DEFAULT = { theme: 'system', palette: 'gruvbox' };

function normalise(look) {
  const theme = look && ['light', 'dark'].includes(look.theme) ? look.theme : 'system';
  const palette = look && Object.prototype.hasOwnProperty.call(PALETTES, look.palette) ? look.palette : DEFAULT.palette;
  return { theme, palette };
}

function load(file) {
  try {
    return normalise(JSON.parse(fs.readFileSync(file, 'utf8')));
  } catch {
    return { ...DEFAULT };
  }
}

function save(file, look) {
  try {
    fs.writeFileSync(file, JSON.stringify(normalise(look)));
  } catch {
    // Unwritable: the next start opens in the defaults and the renderer corrects it.
  }
}

/** The colours of a look; `systemDark` is what the OS reports, used only for `system`. */
function colours(look, systemDark) {
  const { theme, palette } = normalise(look);
  const dark = theme === 'system' ? Boolean(systemDark) : theme === 'dark';
  return { dark, ...PALETTES[palette][dark ? 'dark' : 'light'] };
}

module.exports = { PALETTES, DEFAULT, normalise, load, save, colours };
