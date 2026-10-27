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
 * `tr` is the translator and `translateRuntime` the one for sentences the
 * runtime wrote (a failure's `detail`); `detail` is the paste shortcut, given only when the
 * user has to press it, and `text` is shown as given, never translated.
 * While processing, `phase` says which wait it is ('' for the recogniser,
 * 'postprocessing' for the language-model step, 'delivering' just after it) and `postprocess` whether the
 * step is switched on, which decides whether the two steps are drawn.
 */
export function capsuleCopy({ state, delivery, phase = '', postprocess = false }, tr, translateRuntime = (x) => x) {
  if (delivery) {
    const { outcome, detail, text } = delivery;
    if (!DELIVERY_OUTCOMES.includes(outcome)) return null;
    if (outcome === 'pasted') {
      return { kind: outcome, tone: 'success', title: tr('Paste sent'), body: collapse(text) || tr('Copied to clipboard') };
    }
    if (outcome === 'failed') {
      // The text went nowhere, so it is not shown; the reason is what matters.
      // The runtime's own sentence says it when it has one; a recording too
      // short to read is not a delivery problem and gets its own title.
      const reason = String(detail || '').trim();
      const title = delivery.kind === 'too_short' ? tr('Recording too short') : tr('Delivery failed');
      return {
        kind: outcome,
        tone: 'danger',
        title,
        body: reason ? translateRuntime(reason) : tr('Nothing was pasted. The reason is in Logs.'),
      };
    }
    const title = detail ? tr('Copied. Press %1').replace('%1', detail) : tr('Copied');
    return { kind: outcome, tone: 'info', title, body: collapse(text) || tr('Copied to clipboard') };
  }
  if (state === 'recording') {
    return { kind: 'recording', tone: 'danger', title: tr('Recording'), body: tr('Speak now') };
  }
  if (state === 'processing') {
    const second = phase === 'postprocessing' || phase === 'delivering';
    const steps = postprocess || second ? processingSteps(second ? 1 : 0, tr) : null;
    return {
      kind: 'processing',
      tone: 'accent',
      title: second ? tr('Post-processing') : tr('Transcribing'),
      body: second ? tr('Tidying the text') : tr('Transcribing speech'),
      steps,
    };
  }
  return null;
}

/** The two waits after a recording, each marked done, active or waiting. */
export function processingSteps(active, tr) {
  return [tr('Transcription'), tr('Post-processing')].map((label, i) => ({
    label,
    status: i < active ? 'done' : i === active ? 'active' : 'waiting',
  }));
}

/** mm:ss for the recording clock. */
export function clock(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * A long reason shortened in the middle, so the end survives: it is usually
 * where the recording was kept or what went wrong last. The capsule shows two
 * lines and cannot show a tooltip (its window ignores the mouse), so the cut
 * has to be made here rather than by the line clamp, which keeps the head.
 */
export function clampMiddle(text, max = 110) {
  const s = String(text || '');
  if (s.length <= max) return s;
  const tail = Math.ceil((max - 1) * 0.45);
  const head = max - 1 - tail;
  return `${s.slice(0, head).trimEnd()}\u2026${s.slice(s.length - tail).trimStart()}`;
}
