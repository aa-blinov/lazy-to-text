'use strict';
// Which developer and test hooks this process honours.
//
// A shipped build used to obey L2T_BACKEND_CMD, L2T_DEV, L2T_SCREENSHOT and
// the L2T_SELFTEST_* variables from its environment, so a stray variable
// could start any command or write the window's text to a file. They now
// need an argument on the command line as well (`--l2t-selftest`), which a
// variable in the environment cannot supply, and the ones that load code
// from a local server (L2T_DEV) are honoured only by an unpackaged app.

const SELFTEST_FLAG = '--l2t-selftest';

function selftest(argv = process.argv) {
  return argv.includes(SELFTEST_FLAG);
}

/** The value of a test hook, or undefined unless the self-test flag is present. */
function hook(name, env = process.env, argv = process.argv) {
  return selftest(argv) ? env[name] : undefined;
}

/** L2T_DEV: renderer from the Vite server. Never in a packaged app. */
function dev(app, env = process.env) {
  return !app.isPackaged && Boolean(env.L2T_DEV);
}

/** L2T_BACKEND_CMD: a different runtime command, for development and tests. */
function backendOverride(app, env = process.env, argv = process.argv) {
  if (!env.L2T_BACKEND_CMD) return undefined;
  return (!app.isPackaged || selftest(argv)) ? env.L2T_BACKEND_CMD : undefined;
}

module.exports = { SELFTEST_FLAG, selftest, hook, dev, backendOverride };
