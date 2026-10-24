// Search, filter and sort of the model cards, as plain functions so the page
// and its tests share one definition. The language filter matches the free
// text the registry writes in `languages`, exactly as the Qt view does.

export const LANGUAGE_FILTERS = [
  { value: '', label: 'Any language' },
  { value: 'Russian', label: 'Russian' },
  { value: 'English', label: 'English' },
  { value: 'multilingual', label: 'Multilingual' },
];

export const SORTS = [
  { value: 'order', label: 'Recommended order' },
  { value: 'accuracy', label: 'Most accurate first' },
  { value: 'speed', label: 'Fastest first' },
  { value: 'size', label: 'Smallest first' },
];

export const ALL = '';

export function matchesLanguage(card, wanted) {
  if (!wanted) return true;
  const languages = card.languages.toLowerCase();
  if (wanted === 'multilingual') return languages.includes('multilingual') || languages.includes('langs');
  return languages.includes(wanted.toLowerCase());
}

/** `translate` maps an English catalogue string to the shown language. */
export function matchesQuery(card, query, translate = (s) => s) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    card.alias,
    card.canonical,
    card.display_name,
    translate(card.display_name),
    card.description,
    translate(card.description),
    card.languages,
    card.family,
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

export function visibleCards(cards, { query = '', language = '', family = ALL, sort = 'order' }, translate) {
  const position = new Map(cards.map((c, i) => [c.alias, i]));
  const filtered = cards.filter(
    (c) => (family === ALL || c.family === family) && matchesLanguage(c, language) && matchesQuery(c, query, translate),
  );
  // Unmeasured models sort last: a blank is not a zero.
  const num = (value) => (value === null || value === undefined || value === '' ? Infinity : Number(value));
  const keys = {
    accuracy: (c) => [num(c.wer), position.get(c.alias)],
    speed: (c) => [num(c.rtf), position.get(c.alias)],
    size: (c) => [c.size_mb, position.get(c.alias)],
    order: (c) => [position.get(c.alias)],
  };
  const key = keys[sort] ?? keys.order;
  return [...filtered].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < ka.length; i += 1) {
      if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
    }
    return 0;
  });
}

export function familiesOf(cards) {
  return [...new Set(cards.map((c) => c.family))];
}
