import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { call, RpcError, _setConnection } from '../renderer/src/lib/rpc.js';

describe('rpc client', () => {
  beforeEach(() => _setConnection({ port: 4242, token: 'tok' }));
  afterEach(() => vi.restoreAllMocks());

  it('posts the method with the bearer token and returns the result', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ result: { pong: true } }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const out = await call('app.ping', { a: 1 });

    expect(out).toEqual({ pong: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:4242/rpc');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(JSON.parse(init.body)).toEqual({ method: 'app.ping', params: { a: 1 } });
  });

  it('turns an error body into an RpcError that keeps the code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ error: { code: 'no_stack', message: 'no audio device' } }),
      })),
    );

    await expect(call('recording.toggle')).rejects.toMatchObject({
      name: 'Error',
      code: 'no_stack',
      message: 'no audio device',
    });
    await expect(call('recording.toggle')).rejects.toBeInstanceOf(RpcError);
  });

  it('reports an HTTP failure as an error, not as a result', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, statusText: 'Unauthorized' })));

    await expect(call('app.ping')).rejects.toMatchObject({ code: 'http_401' });
  });

  it('translates a runtime sentence for the interface language, by whole string and by template', async () => {
    const { language } = await import('../renderer/src/lib/i18n.js');
    language.set('ru');
    try {
      const answer = (message) => vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ error: { code: 'bad_path', message } }) })));
      answer('That is not a folder.');
      await expect(call('models.storage.plan')).rejects.toMatchObject({ message: 'Это не папка.' });
      answer('Choose a text file name that ends in .txt, .md or .text.');
      await expect(call('files.save_text')).rejects.toMatchObject({ message: 'Выберите имя текстового файла с окончанием .txt, .md или .text.' });
      answer('No such thing, said the runtime.');
      await expect(call('x')).rejects.toMatchObject({ message: 'No such thing, said the runtime.' });
    } finally {
      language.set('en');
    }
  });

  it('leaves the sentence alone in English', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ error: { code: 'bad_path', message: 'That is not a folder.' } }) })));
    await expect(call('models.storage.plan')).rejects.toMatchObject({ message: 'That is not a folder.' });
  });
});
