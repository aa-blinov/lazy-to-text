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
});
