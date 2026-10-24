// The rules of the Logs screen, as plain functions: what counts as noise,
// what a filter keeps, and how a record is written out as text.

// Top-level packages that flood the view with request lines during a model
// load. Hidden unless the network toggle is on.
export const NOISY_LOGGERS = ['httpx', 'httpcore', 'urllib3', 'huggingface_hub', 'requests', 'asyncio'];

export const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'];

const RANK = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

export function levelRank(level) {
  return RANK[String(level || '').toUpperCase()] ?? RANK.INFO;
}

export function isNoisy(name) {
  return NOISY_LOGGERS.includes(String(name || '').split('.', 1)[0]);
}

/** Whether a logger belongs to this application rather than to a library. */
export function isOwn(name) {
  return String(name || '').startsWith('app.');
}

/**
 * Tailwind classes for the level word. A status word uses the *-text roles
 * (AA on the page), never the signal fills.
 */
export function levelClass(level) {
  const rank = levelRank(level);
  if (rank >= RANK.ERROR) return 'text-danger-text';
  if (rank >= RANK.WARNING) return 'text-warning-text';
  if (rank >= RANK.INFO) return 'text-accent-text';
  return 'text-ink-faint';
}

/**
 * Brightness answers "was this line addressed to the user?". Bookkeeping at
 * INFO and below recedes; a warning or an error never does.
 */
export function messageClass(record) {
  if (record.user_message) return 'text-ink';
  return levelRank(record.level) <= RANK.INFO ? 'text-ink-faint' : 'text-ink';
}

/**
 * The records a filter keeps. `query` is matched case-insensitively against
 * level, logger and message together, as the Qt view does; `logger` is an
 * exact logger name or empty for all; `minLevel` hides anything quieter.
 */
export function visibleRecords(records, { query = '', showNetwork = false, minLevel = 'DEBUG', logger = '', onlyUser = false } = {}) {
  const needle = query.trim().toLowerCase();
  const floor = levelRank(minLevel);
  return records.filter((r) => {
    if (isNoisy(r.logger) && !showNetwork) return false;
    if (levelRank(r.level) < floor) return false;
    if (logger && r.logger !== logger) return false;
    if (onlyUser && !r.user_message) return false;
    if (needle && !`${r.level} ${r.logger} ${r.message}`.toLowerCase().includes(needle)) return false;
    return true;
  });
}

export function recordText(r) {
  return `${r.time} [${r.level}] ${r.logger}: ${r.message}`;
}

/** The loggers present in the records, own ones first, for the filter. */
export function loggerNames(records) {
  const names = [...new Set(records.map((r) => r.logger))];
  return names.sort((a, b) => Number(isOwn(b)) - Number(isOwn(a)) || a.localeCompare(b));
}
