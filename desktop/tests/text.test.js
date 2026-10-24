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

describe('figures in text the catalogue left in English', async () => {
  const { localizeFigures, formatNumber, language, translateRuntime } = await import('../renderer/src/lib/i18n.js');

  it('writes Russian decimals, units and thousands, and leaves English alone', () => {
    const text = 'Measured 4.9% WER, RTF 0.009, loads in 1.2 s, 2,397 MB of weights, 260 MB.';
    expect(localizeFigures(text, 'en')).toBe(text);
    expect(localizeFigures(text, 'ru')).toBe(
      'Measured 4,9% WER, RTF 0,009, loads in 1,2 с, 2 397 МБ of weights, 260 МБ.',
    );
  });

  it('does not touch a model name that has a dot in it', () => {
    expect(localizeFigures('NVIDIA Parakeet 0.6B, 74M params', 'ru')).toBe('NVIDIA Parakeet 0.6B, 74M params');
  });

  it('formats a number by the interface language', () => {
    language.set('ru');
    try {
      expect(formatNumber(4.7, 1)).toBe('4,7');
      expect(formatNumber(0.018)).toBe('0,018');
    } finally {
      language.set('en');
    }
    expect(formatNumber(4.7, 1)).toBe('4.7');
  });

  it('does not let a template that is mostly a placeholder claim a sentence', () => {
    language.set('ru');
    try {
      expect(translateRuntime('loaded in 12 s')).toBe('loaded in 12 s');
    } finally {
      language.set('en');
    }
  });
});
