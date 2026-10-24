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

// ---- text the runtime wrote ----------------------------------------------
// The Python runtime answers in English whatever the interface language is.
// A sentence it sends is translated here when the catalogue has it: by the
// whole string first, then by a template ("Could not read audio from %1.
// ...": a name sits in the middle, so the whole string never matches).
// A sentence nobody translated is shown as it came, which is the right failure.

let patterns = null;
let patternsFor = null;

function templatePatterns(lang, table) {
  if (patterns && patternsFor === lang) return patterns;
  patternsFor = lang;
  patterns = [];
  for (const [source, target] of Object.entries(table)) {
    // A template that is mostly its placeholder ("%1 s") would claim sentences that are not its own.
    if (!/%\d/.test(source) || source.replace(/%\d/g, '').trim().length < 12) continue;
    const parts = source.split(/%\d/).map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const order = [...source.matchAll(/%(\d)/g)].map((m) => m[1]);
    patterns.push({ re: new RegExp(`^${parts.join('(.+?)')}$`, 's'), order, target });
  }
  return patterns;
}

/** Translate a sentence the runtime produced; unknown text comes back unchanged. */
export function translateRuntime(message, lang = get(language)) {
  const text = String(message ?? '');
  const table = catalogues[lang];
  if (!table || !text) return text;
  if (table[text]) return table[text];
  for (const { re, order, target } of templatePatterns(lang, table)) {
    const m = re.exec(text);
    if (!m) continue;
    let out = target;
    order.forEach((n, i) => {
      out = out.replaceAll(`%${n}`, m[i + 1]);
    });
    return out;
  }
  return text;
}

// ---- numbers ---------------------------------------------------------------

/**
 * A number the way the interface language writes it ("4,7" in Russian).
 * `digits` fixes the decimals; without it the value keeps what it has.
 */
export function formatNumber(value, digits, lang = get(language)) {
  const options = digits == null
    ? { maximumFractionDigits: 6 }
    : { minimumFractionDigits: digits, maximumFractionDigits: digits };
  return new Intl.NumberFormat(lang, options).format(Number(value));
}

/**
 * Figures inside a sentence that was translated by someone who left the
 * English forms alone (the model descriptions: "4.9% WER", "260 MB",
 * "RTF 0.009", "1.2 s"). English text is returned untouched.
 */
export function localizeFigures(text, lang = get(language)) {
  const source = String(text ?? '');
  if (lang !== 'ru') return source;
  return source
    .replace(/(\d),(\d{3})(?=\s(?:MB|GB))/g, '$1\u00a0$2')
    .replace(/(\d+)\.(\d+)(?=%|\s(?:MB|GB|s)\b)/g, '$1,$2')
    .replace(/(RTF\s)(\d+)\.(\d+)/g, '$1$2,$3')
    .replace(/(\d)\s(MB|GB)\b/g, (_, d, unit) => `${d}\u00a0${unit === 'MB' ? 'МБ' : 'ГБ'}`)
    .replace(/(\d)\ss\b/g, '$1\u00a0с');
}

export function normaliseLanguage(value) {
  return value === 'ru' ? 'ru' : 'en';
}
