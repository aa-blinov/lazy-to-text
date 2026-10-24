'use strict';
// Starts the Python runtime (app/server) as a child process and reads the
// one JSON line it prints when it is listening:
//   {"ready": true, "port": 51234, "token": "...", "pid": 123}
// Everything else the child writes goes to stderr and its own app.log.
//
// One Backend can be started again after it stopped or died: `start()`
// makes a new child, and a late exit of an older child is ignored.

const { spawn } = require('node:child_process');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const http = require('node:http');
const readline = require('node:readline');
const env = require('./env.cjs');
const guard = require('./guard.cjs');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const START_TIMEOUT_MS = 60000;

/** The command that starts the runtime: an override, the packaged binary or `uv run`. */
function resolveCommand(app) {
  const override = env.backendOverride(app);
  if (override) {
    const [cmd, ...args] = override.split(' ');
    return { cmd, args, cwd: REPO_ROOT };
  }
  // The packaged window's origin is not one the runtime knows by default.
  const origin = ['--allow-origin', `${guard.APP_SCHEME}://${guard.APP_HOST}`];
  if (app.isPackaged) {
    const exe = process.platform === 'win32' ? 'lazy-to-text-server.exe' : 'lazy-to-text-server';
    const dir = path.join(process.resourcesPath, 'backend');
    return { cmd: path.join(dir, exe), args: origin, cwd: dir };
  }
  return {
    cmd: 'uv',
    args: ['run', '--frozen', 'python', '-m', 'app.server', ...origin, ...(env.dev(app) ? ['--dev'] : [])],
    cwd: REPO_ROOT,
  };
}

/**
 * Where the runtime writes app.log, for a failure message before the
 * runtime has been able to say so itself (platformdirs' per-user log dir).
 */
function guessLogPath(app) {
  if (!app.isPackaged) return path.join(REPO_ROOT, 'logs', 'app.log');
  const home = os.homedir();
  if (process.platform === 'darwin') return path.join(home, 'Library', 'Logs', 'LazyToText', 'app.log');
  if (process.platform === 'win32') {
    const base = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
    return path.join(base, 'LazyToText', 'Log', 'app.log');
  }
  const state = process.env.XDG_STATE_HOME || path.join(home, '.local', 'state');
  return path.join(state, 'LazyToText', 'log', 'app.log');
}

/** A start failure with a short readable message and the child's last lines apart. */
class StartError extends Error {
  constructor(kind, message, detail = '', code = undefined) {
    super(message);
    this.kind = kind;
    this.detail = detail;
    this.code = code;
  }
}

class Backend {
  constructor(app) {
    this.app = app;
    this.child = null;
    this.connection = null;
    this.logPath = null;
    this.onExit = () => {};
    this.stderrTail = [];
    this.stopping = false;
  }

  /** The command line, for messages. */
  command() {
    return resolveCommand(this.app);
  }

  start(timeoutMs = START_TIMEOUT_MS) {
    const { cmd, args, cwd } = resolveCommand(this.app);
    this.stderrTail = [];
    this.stopping = false;
    if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) {
      return Promise.reject(new StartError('missing', `The engine is missing: ${cmd}`, '', undefined));
    }
    return new Promise((resolve, reject) => {
      let child;
      try {
        child = spawn(cmd, args, {
          cwd,
          stdio: ['pipe', 'pipe', 'pipe'],
          // ORT_DISABLE_TELEMETRY: onnxruntime reports to Microsoft on every model load
          // unless told not to before it is imported (QA-SEC-1); the runtime sets it too.
          env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', ORT_DISABLE_TELEMETRY: '1' },
          windowsHide: true,
        });
      } catch (err) {
        reject(new StartError('spawn', String(err.message || err)));
        return;
      }
      this.child = child;
      let settled = false;
      const tail = () => this.stderrTail.join('\n');
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        this.stop();
        reject(new StartError('timeout', 'The engine did not start in time.', tail()));
      }, timeoutMs);

      readline.createInterface({ input: child.stdout }).on('line', (line) => {
        if (settled) return;
        try {
          const msg = JSON.parse(line);
          if (msg.ready === true) {
            settled = true;
            clearTimeout(timer);
            this.connection = { port: msg.port, token: msg.token };
            resolve(this.connection);
          } else if (msg.ready === false) {
            settled = true;
            clearTimeout(timer);
            reject(new StartError(msg.error === 'already_running' ? 'already_running' : 'refused',
              msg.error || 'The engine refused to start.', tail(), msg.error));
          }
        } catch {
          // Not the ready line; some libraries print to stdout. Ignore.
        }
      });
      readline.createInterface({ input: child.stderr }).on('line', (line) => {
        if (this.child !== child) return;
        this.stderrTail.push(line);
        if (this.stderrTail.length > 60) this.stderrTail.shift();
        if (env.dev(this.app)) console.error('[backend]', line);
      });
      child.on('error', (err) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(new StartError('spawn', String(err.message || err), tail()));
      });
      child.on('exit', (code, signal) => {
        clearTimeout(timer);
        const current = this.child === child;
        if (current) {
          this.child = null;
          this.connection = null;
        }
        if (!settled) {
          settled = true;
          reject(new StartError('exited', `The engine exited with code ${code}.`, tail(), code));
          return;
        }
        // An exit of a child that was replaced, or one we asked for, is not news.
        if (current && !this.stopping) this.onExit(code, signal);
      });
    });
  }

  /** True while a child process exists. */
  alive() {
    return Boolean(this.child) && this.child.exitCode === null && !this.child.killed;
  }

  /** Close stdin (the runtime's "parent is gone" signal), then escalate. */
  stop() {
    const child = this.child;
    this.stopping = true;
    if (!child) return Promise.resolve();
    return new Promise((resolve) => {
      let timers = [];
      const done = () => {
        timers.forEach(clearTimeout);
        resolve();
      };
      child.once('exit', done);
      timers.push(setTimeout(() => child.kill('SIGKILL'), 8000));
      try {
        child.stdin.end();
      } catch {
        // already closed
      }
      timers.push(setTimeout(() => child.kill('SIGTERM'), 2500));
      if (child.exitCode !== null) done();
    });
  }

  /** Kill a runtime that is alive and not answering, without ceremony. */
  kill() {
    const child = this.child;
    this.stopping = true;
    if (!child) return Promise.resolve();
    return new Promise((resolve) => {
      child.once('exit', () => resolve());
      try {
        child.kill('SIGKILL');
      } catch {
        resolve();
      }
      if (child.exitCode !== null) resolve();
    });
  }

  /** One request to the loopback channel; resolves with the parsed body. */
  request(method, pathName, { body, timeout = 5000 } = {}) {
    const connection = this.connection;
    if (!connection) return Promise.reject(new Error('The engine is not running.'));
    return new Promise((resolve, reject) => {
      const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
      const req = http.request({
        host: '127.0.0.1',
        port: connection.port,
        path: pathName,
        method,
        timeout,
        headers: {
          Authorization: `Bearer ${connection.token}`,
          ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}),
        },
      }, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}`));
            return;
          }
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
          } catch (err) {
            reject(err);
          }
        });
      });
      req.on('timeout', () => req.destroy(new Error('timeout')));
      req.on('error', reject);
      if (payload) req.write(payload);
      req.end();
    });
  }

  /** `GET /health` answers 200 while the channel is alive. */
  async healthy(timeout = 4000) {
    try {
      const body = await this.request('GET', '/health', { timeout });
      return body && body.ok === true;
    } catch {
      return false;
    }
  }

  /** The runtime's own snapshot: the language and the log path. Null on any failure. */
  async snapshot() {
    try {
      const body = await this.request('POST', '/rpc', { body: { method: 'app.snapshot', params: {} }, timeout: 8000 });
      return body && body.result ? body.result : null;
    } catch {
      return null;
    }
  }
}

module.exports = { Backend, StartError, resolveCommand, guessLogPath, START_TIMEOUT_MS };
