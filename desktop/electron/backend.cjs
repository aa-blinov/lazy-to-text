'use strict';
// Starts the Python runtime (app/server) as a child process and reads the
// one JSON line it prints when it is listening:
//   {"ready": true, "port": 51234, "token": "...", "pid": 123}
// Everything else the child writes goes to stderr and its own app.log.

const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const readline = require('node:readline');

const REPO_ROOT = path.resolve(__dirname, '..', '..');

/** The command that starts the runtime: an override, the packaged binary or `uv run`. */
function resolveCommand(app) {
  if (process.env.L2T_BACKEND_CMD) {
    const [cmd, ...args] = process.env.L2T_BACKEND_CMD.split(' ');
    return { cmd, args, cwd: REPO_ROOT };
  }
  if (app.isPackaged) {
    const exe = process.platform === 'win32' ? 'lazy-to-text-server.exe' : 'lazy-to-text-server';
    const dir = path.join(process.resourcesPath, 'backend');
    return { cmd: path.join(dir, exe), args: [], cwd: dir };
  }
  return {
    cmd: 'uv',
    args: ['run', '--frozen', 'python', '-m', 'app.server'],
    cwd: REPO_ROOT,
  };
}

class Backend {
  constructor(app) {
    this.app = app;
    this.child = null;
    this.connection = null;
    this.onExit = () => {};
    this.stderrTail = [];
  }

  start(timeoutMs = 60000) {
    const { cmd, args, cwd } = resolveCommand(this.app);
    if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) {
      return Promise.reject(new Error(`The backend is missing: ${cmd}`));
    }
    return new Promise((resolve, reject) => {
      const child = spawn(cmd, args, {
        cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      });
      this.child = child;
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        this.stop();
        reject(new Error('The backend did not start in time.\n' + this.stderrTail.join('\n')));
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
            const error = new Error(msg.error || 'backend refused to start');
            error.code = msg.error;
            reject(error);
          }
        } catch {
          // Not the ready line; some libraries print to stdout. Ignore.
        }
      });
      readline.createInterface({ input: child.stderr }).on('line', (line) => {
        this.stderrTail.push(line);
        if (this.stderrTail.length > 60) this.stderrTail.shift();
        if (process.env.L2T_DEV) console.error('[backend]', line);
      });
      child.on('error', (err) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(err);
      });
      child.on('exit', (code, signal) => {
        clearTimeout(timer);
        this.child = null;
        if (!settled) {
          settled = true;
          reject(new Error(`The backend exited with code ${code}.\n` + this.stderrTail.join('\n')));
        }
        this.onExit(code, signal);
      });
    });
  }

  /** Close stdin (the runtime's "parent is gone" signal), then escalate. */
  stop() {
    const child = this.child;
    if (!child) return Promise.resolve();
    return new Promise((resolve) => {
      const kill = setTimeout(() => child.kill('SIGKILL'), 8000);
      child.once('exit', () => {
        clearTimeout(kill);
        resolve();
      });
      try {
        child.stdin.end();
      } catch {
        // already closed
      }
      setTimeout(() => child.kill('SIGTERM'), 2500);
    });
  }
}

module.exports = { Backend, resolveCommand };
