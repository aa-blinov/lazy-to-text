// Development loop: the Vite dev server for the renderer, then Electron
// pointed at it. The Python runtime is started by Electron itself.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const electronBin = require('electron');

const vite = spawn('npx', ['vite', '--config', 'vite.config.js'], { stdio: 'inherit', shell: process.platform === 'win32' });

async function waitForVite() {
  for (let i = 0; i < 100; i++) {
    try {
      const res = await fetch('http://127.0.0.1:5173/');
      if (res.ok) return;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('Vite did not start');
}

await waitForVite();
const electron = spawn(electronBin, ['.'], { stdio: 'inherit', env: { ...process.env, L2T_DEV: '1' } });
electron.on('exit', () => { vite.kill(); process.exit(0); });
process.on('SIGINT', () => { electron.kill(); vite.kill(); });
