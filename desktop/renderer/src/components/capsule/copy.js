// What the capsule says. Same rules as the Qt capsule (spec 007): every
// delivery title names the outcome in the past tense, and none of them
// claims "Pasted", because no platform API confirms the target app pasted.

export const DELIVERY_OUTCOMES = ['pasted', 'copied', 'failed'];

/** How long a delivery confirmation stays after the state returns to idle. */
export const DELIVERY_VISIBLE_MS = 3000;

/** The one-line body: the delivered text with whitespace collapsed. */
export function collapse(text) {
  return String(text || '').split(/\s+/).filter(Boolean).join(' ');
}

/**
 * Title, body and dot tone for what the capsule shows, or null for idle and
 * for an outcome it does not know (which must not change the capsule).
 * `tr` is the translator; `detail` is the paste shortcut, given only when the
 * user has to press it, and `text` is shown as given, never translated.
 */
export function capsuleCopy({ state, delivery }, tr) {
  if (delivery) {
    const { outcome, detail, text } = delivery;
    if (!DELIVERY_OUTCOMES.includes(outcome)) return null;
    if (outcome === 'pasted') {
      return { kind: outcome, tone: 'success', title: tr('Paste sent'), body: collapse(text) || tr('Copied to clipboard') };
    }
    if (outcome === 'failed') {
      // The text went nowhere, so it is not shown; the reason is what matters.
      return { kind: outcome, tone: 'danger', title: tr('Delivery failed'), body: tr('Nothing was pasted. The reason is in Logs.') };
    }
    const title = detail ? tr('Copied — press %1').replace('%1', detail) : tr('Copied');
    return { kind: outcome, tone: 'info', title, body: collapse(text) || tr('Copied to clipboard') };
  }
  if (state === 'recording') {
    return { kind: 'recording', tone: 'danger', title: tr('Recording'), body: tr('Speak now') };
  }
  if (state === 'processing') {
    return { kind: 'processing', tone: 'accent', title: tr('Processing'), body: tr('Transcribing speech') };
  }
  return null;
}

/** mm:ss for the recording clock. */
export function clock(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
