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
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, statSync } from 'node:fs';
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

const exe = findExecutable(dir);
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
// A CI runner has no setuid sandbox helper; the smoke run is not a security test.
// Nor a GPU: a Windows runner without one aborts Chromium at start.
const args = process.platform === 'linux' ? ['--no-sandbox', '--disable-gpu']
  : process.platform === 'win32' ? ['--disable-gpu'] : [];

console.log(`smoke: starting ${exe}`);
const child = spawn(exe, args, { env, stdio: ['pipe', 'inherit', 'inherit'] });
const killer = setTimeout(() => {
  console.error('smoke: the app did not finish in 180 s');
  child.kill('SIGKILL');
}, 180000);

child.on('exit', (code) => {
  clearTimeout(killer);
  if (code !== 0) {
    console.error(`smoke: the app exited with ${code}`);
    process.exit(1);
  }
  if (!existsSync(shot) || statSync(shot).size < 5000) {
    console.error('smoke: no screenshot was written');
    process.exit(1);
  }
  const text = readFileSync(`${shot}.txt`, 'utf8');
  console.log(`smoke: window text: ${JSON.stringify(text.slice(0, 200))}`);
  const firstRun = text.includes('Start dictating');
  const shell = ['Transcribe', 'Models', 'IDLE'].every((word) => text.includes(word));
  if (!firstRun && !shell) {
    console.error('smoke: the window shows neither the first-run screen nor the shell');
    process.exit(1);
  }
  console.log('smoke: ok');
});
