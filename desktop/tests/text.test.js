import { describe, expect, it } from 'vitest';
import { middleEllipsis, subject } from '../renderer/src/lib/text.js';

describe('middleEllipsis', () => {
  it('leaves a short string alone', () => {
    expect(middleEllipsis('Work', 44)).toBe('Work');
  });

  it('keeps both ends, so names that share a start stay apart', () => {
    const a = middleEllipsis('Supercalifragilisticexpialidocious' + 'a'.repeat(80) + '-one', 44);
    const b = middleEllipsis('Supercalifragilisticexpialidocious' + 'a'.repeat(80) + '-two', 44);
    expect(a.length).toBe(44);
    expect(a).not.toBe(b);
    expect(a.startsWith('Supercalifragilistic')).toBe(true);
    expect(a.endsWith('-one')).toBe(true);
  });
});

describe('subject', () => {
  it('collapses whitespace and cuts a long text with an ellipsis', () => {
    expect(subject('one\n two\t three')).toBe('one two three');
    const cut = subject('x'.repeat(100), 40);
    expect(cut.length).toBe(40);
    expect(cut.endsWith('…')).toBe(true);
  });

  it('is empty for nothing', () => {
    expect(subject(null)).toBe('');
  });
});
