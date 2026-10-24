import { describe, expect, it, beforeEach } from 'vitest';
import { language, translateRuntime } from '../renderer/src/lib/i18n.js';

beforeEach(() => language.set('ru'));

describe('runtime sentences in Russian', () => {
  it('translates the two save refusals that had no entry', () => {
    expect(translateRuntime('That folder belongs to an installed application or the system. Choose another place.'))
      .toBe('Эта папка принадлежит установленному приложению или системе. Выберите другое место.');
    expect(translateRuntime('That folder belongs to an installed application. Choose another place.'))
      .toContain('установленному приложению');
  });

  it('writes the extension list with a Russian "или", not an English "or"', () => {
    expect(translateRuntime('Choose a text file name that ends in .txt, .md, .markdown or .text.'))
      .toBe('Выберите имя текстового файла с окончанием .txt, .md, .markdown или .text.');
    expect(translateRuntime('Choose a text file name that ends in .txt or .md.')).toContain('.txt или .md');
  });

  it('translates the short-recording sentence and the other dictation failures', () => {
    expect(translateRuntime('The recording was too short to transcribe. Speak a little longer before you stop.'))
      .toContain('Говорите чуть дольше');
    expect(translateRuntime('Nothing was recorded: no audio came from the microphone.')).toContain('Ничего не записано');
    expect(translateRuntime('Could not start recording: the microphone did not open.'))
      .toBe('Не удалось начать запись: микрофон не открылся.');
    expect(translateRuntime('Could not start recording: No microphone is available: boom.'))
      .toBe('Не удалось начать запись: Микрофон недоступен: boom.');
  });

  it('prefers the more specific template when two share a start', () => {
    expect(translateRuntime('Error processing recording: boom. The recording was kept at /a/b.wav.'))
      .toBe('Ошибка при обработке записи: boom. Запись сохранена здесь: /a/b.wav.');
    expect(translateRuntime('Error processing recording: boom.')).toBe('Ошибка при обработке записи: boom.');
    expect(translateRuntime('Could not transcribe the recording (the speech model failed, this was not silence): boom. The recording was kept at /a/b.wav.'))
      .toBe('Не удалось расшифровать запись (сбой модели распознавания, это не тишина): boom. Запись сохранена здесь: /a/b.wav.');
  });

  it('translates the connection-test limit', () => {
    expect(translateRuntime('Too many connection tests are running. Wait for one to finish.')).toContain('Слишком много проверок');
  });

  it('translates the connection-test sentences by template, with the host and the code kept', () => {
    expect(translateRuntime('The server did not answer at 127.0.0.1:1. Is it running?'))
      .toBe('Сервер 127.0.0.1:1 не отвечает. Он запущен?');
    expect(translateRuntime('The server at [::1]:11434 did not answer in time.')).toBe('Сервер [::1]:11434 не ответил вовремя.');
    expect(translateRuntime('The server answered with an error (HTTP 503).')).toBe('Сервер ответил ошибкой (HTTP 503).');
    expect(translateRuntime('The server answered with a redirect (HTTP 302), which is not followed.')).toContain('HTTP 302');
    expect(translateRuntime('The server refused the key.')).toBe('Сервер отклонил ключ.');
  });

  it('leaves English alone in English and unknown sentences as they came', () => {
    language.set('en');
    expect(translateRuntime('The recording was too short to transcribe. Speak a little longer before you stop.'))
      .toBe('The recording was too short to transcribe. Speak a little longer before you stop.');
    language.set('ru');
    expect(translateRuntime('Something nobody translated.')).toBe('Something nobody translated.');
  });
});
