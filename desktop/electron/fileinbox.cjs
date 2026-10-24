'use strict';
// Files handed to the app by the system (argv at a cold start, Open With,
// the second instance). A path is held here until the page confirms it got
// it, because "the page finished loading" is not "the page is listening":
// a push sent too early goes nowhere and the file is silently lost.
//
// Three ways out, all idempotent against each other:
//   - push: `send(path)` after the page loaded, repeated every `resendMs`
//     until the path is acknowledged (the preload acknowledges every path it
//     hands to an `onFileOpen` callback);
//   - ready(): the page says its inbox is installed; everything unacknowledged
//     is sent again at once;
//   - pending(): the page pulls what is queued, which also clears it.

function createFileInbox({ send, canSend, resendMs = 1000, maxResends = 60, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let queue = [];
  // After ready() a push reaches a page that is listening, so a pull that
  // follows must not return the same path a second time.
  let listening = false;
  const pushedToListener = new Set();
  let timer = null;
  let resends = 0;

  function stop() {
    if (timer) clearTimer(timer);
    timer = null;
  }

  function arm() {
    if (timer || queue.length === 0 || resends >= maxResends) return;
    timer = setTimer(() => {
      timer = null;
      resends += 1;
      flush();
    }, resendMs);
    if (timer && timer.unref) timer.unref();
  }

  function flush() {
    if (queue.length === 0) { stop(); return; }
    if (canSend()) {
      for (const path of queue.slice()) {
        send(path);
        if (listening) pushedToListener.add(path);
      }
    }
    arm();
  }

  return {
    add(path) {
      if (!queue.includes(path)) queue.push(path);
      resends = 0;
      flush();
    },
    // The page loaded (or reloaded): start pushing.
    loaded() { listening = false; pushedToListener.clear(); resends = 0; flush(); },
    ready() { listening = true; resends = 0; stop(); flush(); },
    ack(path) {
      queue = queue.filter((p) => p !== path);
      pushedToListener.delete(path);
      if (queue.length === 0) stop();
    },
    pending() {
      const out = queue.filter((p) => !pushedToListener.has(p));
      queue = [];
      pushedToListener.clear();
      stop();
      return out;
    },
    size: () => queue.length,
    stop,
  };
}

module.exports = { createFileInbox };
