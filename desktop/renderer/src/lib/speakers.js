// A diarized transcript is plain text: one paragraph per speaker turn,
// "<label> N: text", blank line between (app/backends/onnx_backend.py). The
// screen shows those turns as a conversation, so this module reads the text
// into turns and writes turns back into text; the text stays the one source
// of truth, so Copy, Save and the edited-state check are unchanged.

const TURN = /^([^:\n]{1,40}): ([\s\S]*)$/;

/**
 * The turns of a diarized transcript, or null when the text is not one (a
 * paragraph without a "label: " start, or only one speaker), in which case
 * the screen shows the ordinary text box.
 */
export function parseTurns(text) {
  const blocks = String(text || '').split(/\n{2,}/).filter((b) => b.trim() !== '');
  if (blocks.length < 2) return null;
  const turns = [];
  for (const block of blocks) {
    const m = TURN.exec(block);
    if (!m) return null;
    turns.push({ speaker: m[1].trim(), text: m[2] });
  }
  return new Set(turns.map((t) => t.speaker)).size >= 2 ? turns : null;
}

export function joinTurns(turns) {
  return turns.map((t) => `${t.speaker}: ${t.text}`).join('\n\n');
}

/** Every turn of `from` becomes `to`. A name with a colon or a line break cannot be read back, so it is cleaned. */
export function renameSpeaker(turns, from, to) {
  const name = String(to || '').replace(/[:\r\n]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 40);
  if (!name || name === from) return turns;
  return turns.map((t) => (t.speaker === from ? { ...t, speaker: name } : t));
}

/** Speakers in order of first appearance. */
export function speakerList(turns) {
  return [...new Set(turns.map((t) => t.speaker))];
}

// Five roles of the kit, each walked to AA on the page; a speaker keeps its
// colour by its place in the list, in every palette and both modes.
export const SPEAKER_ROLES = ['accent', 'warning', 'success', 'danger', 'info'];

export function speakerRole(list, speaker) {
  const i = Math.max(0, list.indexOf(speaker));
  return SPEAKER_ROLES[i % SPEAKER_ROLES.length];
}
