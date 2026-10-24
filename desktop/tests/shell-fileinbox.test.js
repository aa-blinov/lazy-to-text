// QA-SHELL-F2: a file handed over at a cold start must survive a page that
// has loaded but is not listening yet. The queue keeps it until acknowledged.
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

const require = createRequire(import.meta.url);
const { createFileInbox } = require(join(import.meta.dirname, '..', 'electron', 'fileinbox.cjs'));

describe('the file inbox', () => {
  let sent;
  let loaded;
  let inbox;
  beforeEach(() => {
    vi.useFakeTimers();
    sent = [];
    loaded = false;
    inbox = createFileInbox({ send: (p) => sent.push(p), canSend: () => loaded });
  });
  afterEach(() => { inbox.stop(); vi.useRealTimers(); });

  it('holds a file while the page is loading and sends it when it has loaded', () => {
    inbox.add('/a.wav');
    expect(sent).toEqual([]);
    loaded = true;
    inbox.loaded();
    expect(sent).toEqual(['/a.wav']);
  });

  it('sends again every second until the page acknowledges it', () => {
    loaded = true;
    inbox.add('/a.wav');
    vi.advanceTimersByTime(2100);
    expect(sent).toEqual(['/a.wav', '/a.wav', '/a.wav']);
    inbox.ack('/a.wav');
    vi.advanceTimersByTime(5000);
    expect(sent).toHaveLength(3);
    expect(inbox.size()).toBe(0);
  });

  it('sends at once when the page says it is ready', () => {
    loaded = true;
    inbox.add('/a.wav');
    sent.length = 0;
    inbox.ready();
    expect(sent).toEqual(['/a.wav']);
  });

  it('hands the queue over on a pull and clears it', () => {
    inbox.add('/a.wav');
    inbox.add('/b.wav');
    expect(inbox.pending()).toEqual(['/a.wav', '/b.wav']);
    expect(inbox.pending()).toEqual([]);
    loaded = true;
    vi.advanceTimersByTime(5000);
    expect(sent).toEqual([]);
  });

  it('does not return on a pull what a ready page was just sent', () => {
    loaded = true;
    inbox.add('/a.wav');
    inbox.ready();
    expect(inbox.pending()).toEqual([]);
  });

  it('returns on a pull what was pushed before the page listened', () => {
    loaded = true;
    inbox.add('/a.wav');
    expect(inbox.pending()).toEqual(['/a.wav']);
  });

  it('does not queue the same path twice', () => {
    inbox.add('/a.wav');
    inbox.add('/a.wav');
    expect(inbox.size()).toBe(1);
  });

  it('gives up after a bounded number of resends', () => {
    loaded = true;
    inbox.add('/a.wav');
    vi.advanceTimersByTime(200000);
    expect(sent.length).toBeLessThanOrEqual(62);
  });
});
