// Interface language. Source strings are the English text; Russian comes
// from ru.json, generated from the Qt catalogue (app/i18n/app_ru.ts) by
// scripts/export_translations.py so both interfaces say the same thing.
// A string with no entry is shown as written, which is the right failure.

import { writable, derived, get } from 'svelte/store';
import ru from '../i18n/ru.json';

// Strings that exist only in this interface live in i18n/ru.<area>.json,
// one file per area so two people never edit the same file. They are merged
// over the Qt catalogue, which stays the source for everything shared.
const extras = import.meta.glob('../i18n/ru.*.json', { eager: true, import: 'default' });
const russian = Object.assign({}, ru, ...Object.values(extras));

export const language = writable('en');

const catalogues = { ru: russian };

export const t = derived(language, ($lang) => {
  const table = catalogues[$lang] ?? null;
  return (source, vars) => {
    let text = (table && table[source]) || source;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
    }
    return text;
  };
});

export function tr(source, vars) {
  return get(t)(source, vars);
}

export function normaliseLanguage(value) {
  return value === 'ru' ? 'ru' : 'en';
}
