// Runs electron-builder with the checks and the signing choice a bare
// `electron-builder` call would leave to luck:
//
//   node scripts/dist.mjs --dir              unpacked app for this machine
//   node scripts/dist.mjs --mac --arm64      dmg + zip
//   node scripts/dist.mjs --win | --linux
//
// Any other argument is passed through to electron-builder unchanged.
//
// What it adds:
//  - the runtime (../dist/lazy-to-text-server) and the renderer build must
//    exist, because electron-builder would package an app without them and
//    say nothing until the first launch;
//  - on macOS the runtime's architecture must match the target's;
//  - on macOS the runtime's Mach-O files are signed here, then excluded from
//    electron-builder's own pass (`signIgnore` in electron-builder.yml).
//    The runtime folder holds thousands of data files, and electron-builder
//    signs every one of them with a timestamp request apiece, which turns a
//    packaging step into a very long wait for nothing: only code needs a
//    signature;
//  - on macOS the signing identity and the entitlements that go with it:
//    a Developer ID identity (CSC_NAME or CSC_LINK) uses the strict files,
//    the local self-signed identity or an ad-hoc signature uses the local
//    files that add disable-library-validation, for the reason recorded in
//    build/entitlements.mac.local.plist.

import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, '..');
const repo = resolve(desktop, '..');
const LOCAL_IDENTITY = 'Lazy to Text Signing';

const args = process.argv.slice(2);
const mac = args.includes('--mac') || (process.platform === 'darwin'
  && !args.includes('--win') && !args.includes('--linux'));

function fail(message) {
  console.error(`dist: ${message}`);
  process.exit(1);
}

const runtimeName = process.platform === 'win32' ? 'lazy-to-text-server.exe' : 'lazy-to-text-server';
const runtimeDir = join(repo, 'dist', 'lazy-to-text-server');
if (!existsSync(join(runtimeDir, runtimeName))) {
  fail(`the runtime is not built: ${runtimeDir}\n`
    + '  uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py');
}
if (!existsSync(join(desktop, 'dist-renderer', 'index.html'))) {
  fail('the renderer is not built: run `npm run build` first');
}

const extra = [];

/** Every Mach-O file under a directory: libraries and executables. */
function machOFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) machOFiles(full, out);
    else if (/\.(so|dylib)$/.test(name) || (st.mode & 0o111)) out.push(full);
  }
  return out;
}

/** Sign the runtime in place, libraries first and executables last. */
function signRuntime(identity, entitlements, timestamp) {
  const files = machOFiles(runtimeDir);
  files.sort((a, b) => Number(/\.(so|dylib)$/.test(b)) - Number(/\.(so|dylib)$/.test(a)));
  for (const file of files) {
    const run = spawnSync('codesign', [
      '--force', '--sign', identity, '--options', 'runtime',
      timestamp ? '--timestamp' : '--timestamp=none',
      '--entitlements', join(desktop, entitlements), file,
    ], { encoding: 'utf8' });
    if (run.status !== 0) fail(`codesign failed on ${file}\n${run.stderr}`);
  }
  console.log(`dist: signed ${files.length} runtime files`);
}
if (mac && process.platform === 'darwin') {
  const wanted = args.includes('--x64') ? 'x86_64'
    : args.includes('--arm64') ? 'arm64'
      : (process.arch === 'arm64' ? 'arm64' : 'x86_64');
  const lipo = spawnSync('lipo', ['-archs', join(runtimeDir, runtimeName)], { encoding: 'utf8' });
  const have = (lipo.stdout || '').trim().split(/\s+/);
  if (!have.includes(wanted)) {
    fail(`the runtime is built for ${have.join(', ')} but the app targets ${wanted}; `
      + 'build the runtime on a machine of the target architecture');
  }

  const developerId = Boolean(process.env.CSC_NAME || process.env.CSC_LINK);
  if (!developerId) {
    const found = spawnSync('security', ['find-identity', '-v', '-p', 'codesigning'], { encoding: 'utf8' });
    const hasLocal = (found.stdout || '').includes(`"${LOCAL_IDENTITY}"`);
    const identity = hasLocal ? LOCAL_IDENTITY : '-';
    signRuntime(identity, 'build/entitlements.mac.local.inherit.plist', false);
    extra.push(`-c.mac.identity=${identity}`);
    extra.push('-c.mac.entitlements=build/entitlements.mac.local.plist');
    extra.push('-c.mac.entitlementsInherit=build/entitlements.mac.local.inherit.plist');
    console.log(`dist: signing with ${hasLocal ? `the local identity "${LOCAL_IDENTITY}"` : 'an ad-hoc signature'}`);
  } else {
    // The runtime is signed with the same Developer ID by the caller's
    // keychain: electron-builder imports CSC_LINK into a temporary keychain
    // that this script cannot see, so only CSC_NAME is handled here.
    if (process.env.CSC_NAME) {
      signRuntime(process.env.CSC_NAME, 'build/entitlements.mac.inherit.plist', true);
    } else {
      fail('CSC_LINK alone is not enough for the runtime: import the certificate into a keychain and set CSC_NAME');
    }
    console.log('dist: signing with the Developer ID named by CSC_NAME');
  }
}

const bin = join(desktop, 'node_modules', '.bin', process.platform === 'win32' ? 'electron-builder.cmd' : 'electron-builder');
const result = spawnSync(bin, [...args, ...extra], {
  cwd: desktop,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
process.exit(result.status ?? 1);
