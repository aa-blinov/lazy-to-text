// A stand-in for lib/rpc.js. `handlers` maps a method name to a function of
// its params; `emit` plays a server event to whoever subscribed.
import { vi } from 'vitest';

export function makeRpc() {
  const handlers = {};
  const listeners = new Map();
  const calls = [];
  return {
    handlers,
    calls,
    call: vi.fn(async (method, params = {}) => {
      calls.push([method, params]);
      const handler = handlers[method];
      if (!handler) {
        const err = new Error(`no such method: ${method}`);
        err.code = 'unknown_method';
        throw err;
      }
      return handler(params);
    }),
    subscribe: vi.fn((name, cb) => {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(cb);
      return () => listeners.get(name)?.delete(cb);
    }),
    emit(name, data) {
      for (const cb of listeners.get(name) ?? []) cb(data);
    },
    called(method) {
      return calls.filter(([m]) => m === method).map(([, p]) => p);
    },
  };
}
