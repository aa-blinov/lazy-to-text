import { describe, expect, it } from 'vitest';
import { joinTurns, parseTurns, renameSpeaker, speakerList, speakerRole, SPEAKER_ROLES } from '../renderer/src/lib/speakers.js';

const TEXT = 'Speaker 1: One.\n\nSpeaker 2: Two: with a colon.\n\nSpeaker 1: Three.';

describe('speaker turns', () => {
  it('reads a diarized text and writes the same text back', () => {
    const turns = parseTurns(TEXT);
    expect(turns).toEqual([
      { speaker: 'Speaker 1', text: 'One.' },
      { speaker: 'Speaker 2', text: 'Two: with a colon.' },
      { speaker: 'Speaker 1', text: 'Three.' },
    ]);
    expect(joinTurns(turns)).toBe(TEXT);
  });

  it('is null for text that is not a conversation', () => {
    expect(parseTurns('')).toBeNull();
    expect(parseTurns('one paragraph only')).toBeNull();
    expect(parseTurns('Speaker 1: One.\n\nno label here')).toBeNull();
    expect(parseTurns('Speaker 1: One.\n\nSpeaker 1: Two.')).toBeNull();
  });

  it('renames every turn of a speaker, and cleans a name that could not be read back', () => {
    const turns = parseTurns(TEXT);
    expect(renameSpeaker(turns, 'Speaker 1', 'Anna').map((t) => t.speaker)).toEqual(['Anna', 'Speaker 2', 'Anna']);
    expect(renameSpeaker(turns, 'Speaker 1', 'A: b\nc')[0].speaker).toBe('A b c');
    expect(renameSpeaker(turns, 'Speaker 1', '  ')).toBe(turns);
    expect(renameSpeaker(turns, 'Speaker 1', 'Speaker 1')).toBe(turns);
  });

  it('gives a speaker a colour by place, wrapping after the last', () => {
    const list = speakerList(parseTurns(TEXT));
    expect(list).toEqual(['Speaker 1', 'Speaker 2']);
    expect(speakerRole(list, 'Speaker 1')).toBe(SPEAKER_ROLES[0]);
    expect(speakerRole(list, 'Speaker 2')).toBe(SPEAKER_ROLES[1]);
    const many = Array.from({ length: SPEAKER_ROLES.length + 1 }, (_, i) => `S${i}`);
    expect(speakerRole(many, many[many.length - 1])).toBe(SPEAKER_ROLES[0]);
  });
});
