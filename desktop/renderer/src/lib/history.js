// History helpers shared by the screen and its tests: pure functions plus the
// calls that change the store. The screen keeps its own list; the runtime's
// `history` event tells it when to read again.

import { call } from './rpc.js';
import { tr, formatNumber, language } from './i18n.js';
import { get } from 'svelte/store';
import { plural, writeClipboard } from './transcribe.js';

/** Case-insensitive match over the text column only, as in the Qt view. */
export function filterEntries(entries, query) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return entries;
  return entries.filter((e) => e.text.toLocaleLowerCase().includes(needle));
}

/** "ctrl+f8" as a key cap reads "Ctrl+F8". */
export function formatHotkey(value) {
  return String(value || '')
    .split('+')
    .map((p) => p.trim().replaceAll('_', ' '))
    .filter(Boolean)
    .map((p) => p[0].toUpperCase() + p.slice(1))
    .join('+');
}

export function formatDuration(seconds) {
  return tr('%1 s').replace('%1', formatNumber(seconds, 1));
}

/** "ru" as the interface language names it ("Russian", "русский"); "auto" is `autoLabel`. */
export function languageName(code, ui = 'en', autoLabel = 'Automatic') {
  const raw = String(code || '').trim();
  if (!raw || raw === 'auto') return autoLabel;
  try {
    return new Intl.DisplayNames([ui], { type: 'language' }).of(raw) || raw;
  } catch {
    return raw;
  }
}

/** "N entries", or "shown of N entries" while a search narrows the list. */
export function countLabel(shown, total, filtered) {
  const totalText = plural(total, '%1 entry', '%1 entries (few)', '%1 entries');
  if (!filtered) return totalText;
  return tr('%1 of %2').replace('%1', String(shown)).replace('%2', totalText);
}

export const listEntries = () => call('history.list');
export const deleteEntry = (id) => call('history.delete', { id });
export const restoreEntry = (entry) => call('history.restore', { entry });
export const clearAll = () => call('history.clear');
// The path comes from the operating system's save dialog, which has already
// asked about replacing a file that is there: that answer is what `overwrite`
// carries. Without it the runtime refuses a name that exists.
// The runtime writes the English file. In another interface language the
// header and the labels would be English in a file the user reads, so the
// text is built here and written by `files.save_text`, with the same checks.
export function exportText(entries) {
  const lines = [tr('Transcription History Export'), '='.repeat(50), ''];
  for (const e of entries) {
    lines.push(
      `${tr('Date')}: ${e.datetime}`,
      `${tr('Duration')}: ${formatDuration(e.duration)}`,
      `${tr('Model')}: ${e.model} (${e.language})`,
      `${tr('Text')}: ${e.text}`,
      '-'.repeat(30),
      '',
    );
  }
  return lines.join('\n') + '\n';
}

export async function exportTo(path, entries = []) {
  if (get(language) === 'en' || !entries.length) return call('history.export', { path, overwrite: true });
  await call('files.save_text', { path, text: exportText(entries), overwrite: true });
  return { exported: entries.length, path };
}
export const copyEntry = (entry) => writeClipboard(entry.text);
