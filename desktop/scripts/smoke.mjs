// Start the packaged app once, on the platform it was built for, and check
// that the runtime came up behind the window. The app renders itself to a
// PNG and writes the visible text next to it (L2T_SCREENSHOT), then quits.
//
//   node scripts/smoke.mjs <unpacked-dir>
//
// A fresh profile has no model, so the first-run screen is expected; it is
// shown only from the runtime's snapshot, as are the sidebar and the status
// strip's state. A shell that opened over a dead runtime shows an error
// instead and fails here.
//
// The test hooks are live only with `--l2t-selftest` on the command line, so
// the variables alone (L2T_SCREENSHOT and the rest) do nothing in a shipped app.
//
// Linux and Chromium's sandbox. A packaged app has to run with the sandbox
// on, and a runner that restricts unprivileged user namespaces (Ubuntu 24.04
// does) only allows it through the setuid `chrome-sandbox` helper, which
// the workflow gives the right owner and mode before this runs.
// L2T_SMOKE_SANDBOX picks what happens when it is not usable:
//   require  fail (the default when the helper is set up)
//   prefer   run with the sandbox, fall back to --no-sandbox with a warning
//   off      --no-sandbox (a laptop, where nobody has set the helper up)
// Without a variable: `require` if the helper is setuid root, else `off`.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = process.argv[2];
if (!dir || !existsSync(dir)) {
  console.error(`smoke: no such directory: ${dir}`);
  process.exit(2);
}

function findExecutable(root) {
  if (process.platform === 'darwin') {
    const app = readdirSync(root).find((n) => n.endsWith('.app'));
    return join(root, app, 'Contents', 'MacOS', app.replace(/\.app$/, ''));
  }
  const names = readdirSync(root).filter((n) => {
    const lower = n.toLowerCase();
    if (!lower.includes('lazy') || lower.includes('uninstall')) return false;
    const full = join(root, n);
    if (!statSync(full).isFile()) return false;
    return process.platform === 'win32' ? lower.endsWith('.exe') : (statSync(full).mode & 0o111) !== 0;
  });
  if (!names.length) throw new Error(`no executable in ${root}: ${readdirSync(root).join(', ')}`);
  return join(root, names[0]);
}

/** Whether Chromium can use its setuid sandbox helper next to the executable. */
function sandboxHelperReady(root) {
  try {
    const st = statSync(join(root, 'chrome-sandbox'));
    return st.uid === 0 && (st.mode & 0o4000) !== 0;
  } catch {
    return false;
  }
}

const exe = findExecutable(dir);
const SELFTEST = '--l2t-selftest';

function sandboxMode() {
  const asked = process.env.L2T_SMOKE_SANDBOX;
  if (['require', 'prefer', 'off'].includes(asked)) return asked;
  return process.platform === 'linux' && sandboxHelperReady(dir) ? 'require' : 'off';
}

/** One start of the app; resolves with its exit code, the screenshot paths and its stderr. */
function runOnce(extraArgs) {
  const home = mkdtempSync(join(tmpdir(), 'l2t-smoke-'));
  const shot = join(home, 'shell.png');
  // Windows keeps its real profile, which on a runner is empty anyway. A run
  // with USERPROFILE and APPDATA redirected aborted at start (exit
  // 0x80000003) while the same app started by hand ran; the cause was not
  // isolated, only the redirection removed.
  const isolated = process.platform === 'win32' ? {} : {
    HOME: home,
    XDG_CONFIG_HOME: join(home, '.config'),
    XDG_CACHE_HOME: join(home, '.cache'),
    XDG_DATA_HOME: join(home, '.local', 'share'),
  };
  const env = {
    ...process.env,
    ...isolated,
    L2T_SCREENSHOT: shot,
    L2T_SCREENSHOT_DELAY: '12000',
    ELECTRON_ENABLE_LOGGING: '1',
  };
  // Nor a GPU: a Windows runner without one aborts Chromium at start.
  const args = [SELFTEST, ...(process.platform === 'win32' || process.platform === 'linux' ? ['--disable-gpu'] : []), ...extraArgs];
  // The profile is scratch as well: a macOS app keeps Electron's own data under the account, not under HOME.
  args.push(`--user-data-dir=${join(home, 'electron-profile')}`);

  console.log(`smoke: starting ${exe} ${args.join(' ')}`);
  return new Promise((resolve) => {
    const child = spawn(exe, args, { env, stdio: ['pipe', 'inherit', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', (chunk) => {
      process.stderr.write(chunk);
      stderr = (stderr + chunk.toString()).slice(-20000);
    });
    const killer = setTimeout(() => {
      console.error('smoke: the app did not finish in 180 s');
      child.kill('SIGKILL');
    }, 180000);
    child.on('exit', (code) => {
      clearTimeout(killer);
      resolve({ code, shot, home, stderr });
    });
  });
}

function check({ code, shot }) {
  if (code !== 0) return `the app exited with ${code}`;
  if (!existsSync(shot) || statSync(shot).size < 5000) return 'no screenshot was written';
  const text = readFileSync(`${shot}.txt`, 'utf8');
  console.log(`smoke: window text: ${JSON.stringify(text.slice(0, 200))}`);
  const firstRun = text.includes('Start dictating');
  const shell = ['Transcribe', 'Models', 'IDLE'].every((word) => text.includes(word));
  if (!firstRun && !shell) return 'the window shows neither the first-run screen nor the shell';
  return null;
}

// Only Linux has the setuid helper question; macOS and Windows run sandboxed as they are.
const onLinux = process.platform === 'linux';
const mode = onLinux ? sandboxMode() : 'require';
let attempt = await runOnce(onLinux && mode === 'off' ? ['--no-sandbox'] : []);
let failure = check(attempt);
if (failure && mode === 'prefer') {
  console.log(`::warning::smoke: with the Chromium sandbox on, ${failure}; retrying with --no-sandbox`);
  rmSync(attempt.home, { recursive: true, force: true });
  attempt = await runOnce(['--no-sandbox']);
  failure = check(attempt);
}
rmSync(attempt.home, { recursive: true, force: true });
if (failure) {
  console.error(`smoke: ${failure}`);
  process.exit(1);
}
if (onLinux && mode === 'off') {
  console.log('::warning::smoke: ran with --no-sandbox; the Chromium sandbox was not exercised');
}
console.log('smoke: ok');
