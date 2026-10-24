# QA report: shell (Electron main process and packaged app)

Tester area: `desktop/electron/*.cjs`, `desktop/electron-builder.yml`, `desktop/scripts/*.mjs`,
`.github/workflows/desktop.yml` and `release.yml`, `lazy_to_text_server.spec`, `scripts/build_server.py`.

Method. Packaged app `desktop/release/mac-arm64/Lazy to Text.app` (built 11:17; its
`app.asar` differs from the working tree only by the `L2T_SELFTEST_DIALOG` hook; the runtime
inside is current: no `app/` commit since). Every launch used its own `HOME` and its own
`--user-data-dir` in the scratch directory, and the bundled vosk-ru-small model copied into
that scratch cache. The window and the capsule were driven with the real app: Chrome DevTools
protocol on a per-launch debugging port, macOS System Events for the close button, menus and
windows, `screencapture` for pixels, RPC calls to the runtime to start and stop recordings, a
Milena-synthesised phrase played through the speakers into the microphone. Runtime failures
were simulated with `L2T_BACKEND_CMD` pointing to small shell scripts. Only macOS arm64 was
available; everything about Windows and Linux below is code review and marked as such.

Two things the reader should know about how this was tested:

- By a mistake of mine a command line `... "Lazy to Text" --version` was run once without a
  scratch `HOME` (the app ignores `--version` and starts). It ran about two minutes against the
  real profile and I killed it. `config.yaml` in the real profile was not modified (mtime is
  still Oct 23 13:50); `app.log` and Electron's own profile directory
  `~/Library/Application Support/Lazy to Text` were written to.
- On macOS Electron resolves `userData` from the account, not from `$HOME`. A scratch `HOME`
  alone therefore still shares Electron's profile, and the single-instance lock, with the
  installed app. It is a testing caveat, not a product defect, but it means anyone who launches
  a build next to the installed one without `--user-data-dir` is forwarded into the installed
  copy (`second-instance`).

---

## Defects

### QA-SHELL-1  A dead runtime is not noticed: the window and the capsule keep saying RECORDING
Severity: S1
Where: `desktop/electron/windows.cjs:198-216` (`startOverlayFeed`), `desktop/electron/events.cjs:43-47`, `desktop/electron/main.cjs:58-63`, renderer `lib/rpc.js:51-60`, `lib/backend.js:30`
Steps:
1. Start the packaged app with a loaded model; start a recording (`recording.toggle`); the capsule shows RECORDING.
2. `kill -9` the runtime process (`Resources/backend/lazy-to-text-server`).
3. Wait. Look at the capsule and the main window.
Expected: spec 010 edge case "The runtime process dies while the window is open: the window says so, offers Restart"; FR-007 tray reflects the state; the capsule should not outlive the recording.
Actual: (reproduced 1 time) 70 seconds after the kill the capsule is still on screen, always on top, with its timer still counting (`RECORDING Speak now 01:09`), and the status strip of the main window still reads RECORDING. No banner, no error, no Restart. The user believes the app is listening; nothing is (hotkeys are dead too). The capsule is click-through, so only quitting the app removes it. Electron's main process learns of the exit (`backend.onExit` sends `l2t:backend-exit`) but the renderer never subscribes to `onBackendExit`; `events.cjs` retries forever and never tells `windows.cjs` that the stream is gone, so `runtimeState`/tray image are never reset; the renderer's `__disconnected` fires only when `EventSource` reaches `CLOSED`, which a refused reconnect never does.
Evidence: `evidence/shell-capsule-after-runtime-kill.png`; DevTools text of the capsule `"RECORDING\nSpeak now\n01:09"`.
Suspected cause: no disconnect path in the main process; `onBackendExit` has no consumer; no restart exists anywhere (`relaunch` is also unused, see QA-SHELL-7).
Status: FIXED - main supervises the runtime by the child process, by the event stream, and by a stream that goes quiet for 45 s followed by three failed `/health` probes; it tells every window (`l2t.backend.onExit({code, signal})`), hides the capsule, resets the tray to idle with an "engine stopped" tip and a Restart entry (`desktop/electron/main.cjs`, `windows.cjs`, `events.cjs`, `backend.cjs`, `preload.cjs`); verified by `desktop/tests/shell-main-flow.test.js`, `shell-windows.test.js`, `shell-backend.test.js` and by hand: packaged-style run with a stand-in runtime, `kill -9` took the capsule down within 1.5 s and the window got `{code: null, signal: 'SIGKILL'}`, a SIGSTOP-ed runtime was declared dead after about 60 s, `restart()` brought the capsule feed back. The in-window banner and Restart button are the renderer's (see NEEDS renderer in QA-JOURNEYS-4). (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): `kill -9` of the runtime: the window's `l2t.backend.onExit` got `{code: null, signal: 'SIGKILL'}` within 3 s, `connection()` then refused with 'The engine is not running.', `backend.restart()` brought a new port (57158 to 57309) and the main process's event stream reconnected (lsof: ESTABLISHED to the new port). The capsule was not on screen in this run (no recording; no model), so its hiding is covered by `shell-main-flow.test.js` only.

### QA-SHELL-2  Runtime fails to start: raw IPC error, no retry, shell looks alive
Severity: S2
Where: `desktop/electron/main.cjs:65-89, 219-222`, `renderer/src/lib/rpc.js:18`
Steps: launch with a runtime that cannot start (a) missing binary (`L2T_BACKEND_CMD=/nonexistent/server`), (b) a runtime that prints a traceback and exits 1, (c) a runtime that never prints the ready line.
Expected: a useful message and a way to retry or find the log.
Actual: (reproduced once each) the window opens with the full sidebar (Transcribe, Models, History, Post-processing, Settings, Logs) and a single red line `Error invoking remote method 'l2t:connection': Error: The backend is missing: /nonexistent/server` (b: `...exited with code 1. Traceback ... ImportError ...`; c: `...did not start in time. starting`). The text is Electron's IPC wrapper, not a message. There is no Retry, no Restart, no path to `app.log`, and the other screens are reachable and dead. Nothing relaunches the runtime; the only way out is quitting from the tray and starting again.
Evidence: `evidence/shell-backend-missing-error.png`.
Status: FIXED - a start failure opens an error window ("The engine did not start", a readable message, the child's last lines under Details, the log path, Retry, Quit) and never the shell (`electron/splash.html`, `splash.js`, `splash-preload.cjs`, `main.cjs`); verified by `shell-main-flow.test.js` (exit 1, Retry, Russian) and by hand with a runtime that exits 1 (screenshot read: title, message, Details, log path, Retry/Quit) and a flaky runtime that succeeds on Retry. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): runtime replaced by a script exiting 1: the error window read 'The engine did not start / The engine stopped while starting (exit code 1). / Details / Log file: <scratch>/app.log / Retry / Quit'; the Quit button ended the process. Retry not clicked this time.

### QA-SHELL-3  No window for up to 60 s while the runtime starts
Severity: S2
Where: `desktop/electron/main.cjs:65-79` (the window is created after `await backend.start()`)
Steps: launch with a runtime that is slow or hangs (`L2T_BACKEND_CMD` to a script that prints noise and sleeps). Count windows with System Events at 30 s.
Expected: spec 010 edge case "The runtime is slow to start (a cold Windows spawn): the window opens with a loading state rather than staying blank".
Actual: (reproduced 1 time) the app is in the Dock with zero windows for the whole 60 s timeout, then the error window of QA-SHELL-2 appears. A user double-clicking a slow cold start sees nothing and double-clicks again (the second launch is silently swallowed by the single-instance lock). Normal start measured at about 1 s with a fresh profile, so this bites on slow machines (Windows cold spawn, antivirus scans of the 250 MB runtime), which is the case the spec names.
Status: FIXED - the loading window is created before the runtime is started and shows immediately; it closes when the main window is ready to show (`shell-main-flow.test.js` "shows the loading window at once"; by hand with a runtime that never prints the ready line: the window was up at 4 s). (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): not re-run by hand beyond the smoke start (window up, first-run text read); the 60 s case is covered by `shell-main-flow.test.js`.

### QA-SHELL-4  Closing the last window does not quit when there is no tray; the app is left invisible
Severity: S2 (reproduced in a patched copy; real-world trigger on Linux is by code review)
Where: `desktop/electron/windows.cjs:46-66, 105-126, 143-162`, `desktop/electron/main.cjs:212-215`
Steps (macOS, a copy of `desktop/electron` in scratch with `new Tray(...)` replaced by `throw`, so `hasTray()` is false): launch, click the red close button.
Expected: FR-007 and spec 007: "without a tray, closing the window MUST quit".
Actual: (reproduced 1 time) the window is destroyed, the process stays alive (4 processes, runtime and hotkeys included), zero windows, no tray, nothing in the Dock to restore (`activate` calls `showMain`, which has no window). `window-all-closed` never fires because the capsule `BrowserWindow` is created at start and always exists.
Linux by code review: Electron does not throw from `new Tray()` on a desktop without a StatusNotifier host (stock GNOME), so `hasTray()` is true, the close button hides the window, and the user has no way to get it back. The `try/catch` in `createTray` cannot detect a missing tray.
Status: FIXED - closing the main window with no tray now quits (`windows.cjs` `onMainClosed`; the capsule window no longer keeps `window-all-closed` from ever firing), and on Linux a tray is used only if a StatusNotifier host owns its name on the session bus, else the app behaves as tray-less. Verified on macOS with the `L2T_SELFTEST_NO_TRAY` hook (red button: process and runtime gone in 3 s). The Linux bus check is code review only. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): `L2T_SELFTEST_NO_TRAY=1 --l2t-selftest`, red button through System Events: the Electron process and the runtime were gone after 4 s.

### QA-SHELL-5  Delivery capsule is clipped at the window edge
Severity: S3
Where: `desktop/electron/windows.cjs:19` (`OVERLAY_SIZE` 360 x 96) against `renderer/src/Overlay.svelte` (`max-w-md`, 448 px)
Steps: dictate a long sentence with auto-paste off; screenshot the capsule one second after Stop.
Expected: spec 007 FR-003/edge case: width sized to its text within a cap, long text cut with an ellipsis.
Actual: (reproduced 1 time) the capsule is cut flat at the window edge: no rounded corner, no right border, body text `это довольно длинная диктовка в которой много слов` ends mid-box instead of an ellipsis. The capsule is allowed to grow wider than the window that holds it.
Evidence: `evidence/shell-capsule-delivery-clipped.png`.
Status: FIXED - the capsule window is 520 x 96 (the page's cap is 448 px plus gutter), placed inside the display's work area and narrowed on a narrow display (`windows.cjs`, `geometry.cjs`); verified by `shell-geometry.test.js` and by a screenshot of the capsule page with a 150-character delivery text: rounded corners, ellipsis, nothing cut at the edge. (shell fixer)

### QA-SHELL-6  Confirmation is shorter than the spec says, and the window hides before the page does
Severity: S4
Where: `windows.cjs:18` `DELIVERY_MS = 2600`; `renderer/src/components/capsule/copy.js:8` `DELIVERY_VISIBLE_MS = 3000`; Qt `recording_overlay.py:38` is 3000.
Actual: measured (1 run) the capsule window disappears 2.6 s after the delivery event; the page keeps the text for 3.0 s, so the last 0.4 s is never seen. Two constants for one fact.
Status: FIXED - the window outlives the page's 3 s confirmation (`DELIVERY_MS` 3200 in `windows.cjs`). (shell fixer)

### QA-SHELL-7  `l2t:relaunch` makes the app unquittable
Severity: S3 (latent: nothing in the renderer calls it yet)
Where: `desktop/electron/main.cjs:196-202, 290-294`
Steps: from the renderer call `window.l2t.window.relaunch()`, then `window.l2t.window.quit()` or the macOS menu Quit.
Actual: (reproduced 1 time) nothing happens: `relaunch` sets `quitting = true`, then `quit()` returns at its first line (`if (quitting) return;`). No relaunch, and afterwards the menu Quit and `l2t:quit` are no-ops, 4 s later the process count was unchanged. After `SIGTERM` the app did relaunch itself, because `app.relaunch()` had been registered. This is the function the "Restart" of QA-SHELL-1/2 would use.
Status: FIXED - `relaunch` flags a relaunch and runs the one quit, which relaunches; a later quit joins it (`main.cjs` `quit()`); verified by `main-ipc.test.js` "a relaunch restarts the app and a quit after it is not a no-op" (fails against the old `quitting` flag). Not run for real: nothing in the renderer calls it. (shell fixer)

### QA-SHELL-8  No Window menu, no Cmd+W, no Minimize shortcut on macOS
Severity: S3
Where: `desktop/electron/main.cjs:156-188` (`installMenu`)
Steps: read the menu bar with System Events; press Cmd+W with the window focused.
Expected: spec 007 US8: a Window menu with Minimize, Zoom and one entry per screen with its shortcut; Cmd+W closes (hides) the window on macOS.
Actual: (reproduced 1 time) menu bar is `Apple, Lazy to Text, Edit, View`; Cmd+W leaves the window open; no Minimize/Zoom/Cmd+M; no per-screen entries. On Windows and Linux (code review) the same three menus appear as a visible menu bar over the window (`autoHideMenuBar` is not set).
Status: FIXED - Window menu with Minimize (Cmd+M), Zoom, Close (Cmd+W on macOS), one entry per screen with Cmd/Ctrl+1..6 and Bring All to Front; the menu bar is hidden until Alt on Windows and Linux. Verified by `main-ipc.test.js` (menu template) and by hand with System Events: menu bar `Apple, Electron, Правка, Вид, Окно`, the Close item hid the window and kept the app. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): menu bar read with System Events, Russian: `Apple, Lazy to Text, Правка, Вид, Окно`; Window menu `Свернуть, Увеличить, Закрыть, Закрыть все, Расшифровка, Модели, История, Постобработка, Настройки, Журнал, Все окна на передний план`.

### QA-SHELL-9  Window position and size are not remembered
Severity: S3
Where: `desktop/electron/windows.cjs:46-60`
Steps: move to (50,80) and resize to 1000 x 650, quit with SIGTERM, relaunch.
Expected: spec 007 US7 #3/#4 (Qt restores geometry, centres when the screen is gone).
Actual: (reproduced 1 time) it reopens at 468,221 size 1120 x 760. Also, fixed minimum 900 x 600 with a default height of 760 is taller than the work area of a 1366 x 768 laptop (by code review; Electron does not clamp the initial size on Windows).
Status: FIXED - size, position and maximised state are written to `window-state.json` in `userData` (debounced on move and resize, and on close) and restored only if the window still shows on a display; otherwise the size is kept and the window is centred on the primary display, clamped to its work area (`geometry.cjs`); default height is clamped to the work area. Verified by `shell-geometry.test.js` and by hand: moved to (120,110), 1000 x 650, quit with SIGTERM, relaunched: same place and size. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): moved to (120,110), 1000 x 650 through System Events, SIGTERM, relaunch: `window-state.json` held the same values and the window came back at (120,110) 1000 x 650.

### QA-SHELL-10  Tray menu, tooltips and app menu are English only
Severity: S3
Where: `windows.cjs:112-117, 128-133`, `main.cjs:156-188`
Actual: tray menu read through System Events: `Show window`, `Quit`; app menu `Settings…`, `Quit Lazy to Text`, `Edit`, `View`; tray tooltips `Lazy to text` (different capitalisation from the product name `Lazy to Text`). FR-009 says the interface follows `ui.language`; the main process does not read it.
Status: FIXED - tray menu, tooltips (now "Lazy to Text: idle / recording / transcribing / loading model", as FR-013), application and Window menus follow `ui.language` read from the runtime's snapshot (refreshed on start, restart and window focus), the system locale until then (`strings.cjs`); verified by `shell-guard.test.js`, `shell-windows.test.js`, `main-ipc.test.js` and by hand (menu bar in Russian). Labels of macOS system roles (About, Hide) follow the OS language, not the app's. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): `ui.language: en` in the scratch config: menu bar `Apple, Lazy to Text, Edit, View, Window`; `ru`: as above.

### QA-SHELL-11  Second-launch "already running" dialog opens behind the foreground app
Severity: S3
Where: `desktop/electron/main.cjs:68-75`
Steps: start one copy (own `userData`, same `HOME`), start a second copy (this is the Qt-or-Electron holds-the-lock case of FR-011).
Actual: (reproduced 2 times, once with a stub runtime that answers `already_running`, once with the real runtime) the second process stays alive showing a modal `dialog.showErrorBox`, but System Events reports it not frontmost and the dialog is only partly visible behind other windows (screenshot taken). A user who double-clicks the app sees a Dock bounce and nothing else. FR-011 itself holds: no second engine is started.
Status: FIXED - the dialog is a message box after `app.focus({steal: true})` (`main.cjs` `alreadyRunning`); verified by hand with a second copy started through `open -n`, which is how a user starts it: the second process was frontmost with an AXDialog window and exited after it. A copy exec'd from a terminal is not activated by macOS, which is how this was first seen. (shell fixer)

### QA-SHELL-12  Fuses are all at their defaults: the signed binary is a Node interpreter and a debugger host
Severity: S3 (security)
Where: electron-builder config has no fuse step; `@electron/fuses read` on the packaged app.
Actual: `RunAsNode` enabled, `EnableNodeCliInspectArguments` enabled, `EnableEmbeddedAsarIntegrityValidation` disabled, `OnlyLoadAppFromAsar` disabled, `EnableCookieEncryption` disabled. Reproduced: `ELECTRON_RUN_AS_NODE=1 "Lazy to Text" -e '...'` runs arbitrary JavaScript (printed Node 24.22 / Electron 45 and the user name) inside the app's signed identity. This app holds the `device.audio-input` entitlement and the user's Microphone grant, so any local process can use the grant to record without a prompt, and `disable-library-validation` (local build) removes the second barrier. `Info.plist` carries `ElectronAsarIntegrity` but the fuse that enforces it is off, so a modified `app.asar` is not detected at launch.
Status: FIXED - `electronFuses` in `electron-builder.yml`: RunAsNode, NodeOptionsEnvironmentVariable and NodeCliInspectArguments off, EmbeddedAsarIntegrityValidation and OnlyLoadAppFromAsar on, GrantFileProtocolExtraPrivileges off (the window is served from `l2t-app://app/` so nothing needs file://); `npx @electron/fuses read --app` on the rebuilt app shows exactly that, `codesign --verify --deep --strict` passes, the app starts and shows the first-run screen from the runtime. Cookie encryption is left alone (the app stores no cookies; enabling it makes macOS ask for a keychain item). Tests: `tests/test_desktop_packaging.py::test_the_electron_fuses_are_flipped_for_the_signed_binary`. (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): `@electron/fuses read --app`: RunAsNode, NodeOptions variable, inspect arguments and file-protocol privileges Disabled; asar integrity and OnlyLoadAppFromAsar Enabled; `codesign --verify --deep --strict` passes.

### QA-SHELL-13  No Content-Security-Policy; navigation guard is a prefix check
Severity: S3 (security hardening)
Where: `desktop/renderer/index.html`, `overlay.html`, `popup.html`; `windows.cjs:68-70`
Actual: none of the three pages has a CSP (the `meta` query returned none). `will-navigate` allows any `file://` URL and anything starting with `http://127.0.0.1:5173`; the overlay window has no `will-navigate` or `setWindowOpenHandler` at all. A navigated `file://` page in the main window would still get the preload bridge and with it `l2t.connection()` (the full-control token). Not reachable today (the drop handler calls `preventDefault`), so hardening, not an exploit. Also the preload exposes `popup.onShow/close` for channels that no main-process handler serves (dead surface).
Status: FIXED - strict CSP meta in all three pages (pinned by `test_every_renderer_page_carries_the_strict_policy`), Vite dev adds only a `ws://` allowance; navigation is allowed only to the app's own pages on every window, the capsule included (`guard.cjs`, `windows.cjs` `lockdown`), and every IPC handler checks the sender's frame URL and arguments (`main.cjs`; `main-ipc.test.js` "who may call"); permission prompts are denied; the dead `popup` and `overlay.onShow` bridge entries are removed. The renderer has to run under the policy: that was checked on the rebuilt app only as far as the first-run screen and the shell load without a CSP violation. (shell fixer)

### QA-SHELL-14  Production builds honour developer environment hooks
Severity: S4
Where: `main.cjs:13, 83-85`, `backend.cjs:16`
Actual: the packaged app obeys `L2T_BACKEND_CMD` (starts any command; split on spaces), `L2T_DEV=1` (loads the renderer and the bridge from whatever listens on 127.0.0.1:5173), `L2T_SCREENSHOT` (writes a PNG of the window plus `document.body.innerText`, i.e. on-screen transcripts, to a path and quits), `L2T_SELFTEST_DROP` (reproduced: drove the packaged app) and `L2T_SELFTEST_DIALOG`. They need the attacker to control the app's environment, which already is code execution as the user, so the risk is small, but QA-SHELL-12 widens it and none of them is needed in a shipped build. A `View` menu with Reload and Toggle DevTools also ships.
Status: FIXED - the hooks (`L2T_SCREENSHOT*`, `L2T_SELFTEST_*`, `L2T_SCREEN`) need `--l2t-selftest` on the command line, `L2T_BACKEND_CMD` needs it in a packaged app, `L2T_DEV` works only in an unpackaged app; `scripts/smoke.mjs`, `scripts/generate_desktop_screenshots.py` and `scripts/linux_container_electron.sh` pass the flag; the View menu has no Reload or DevTools in a packaged app (`env.cjs`; `shell-guard.test.js`, `test_test_hooks_need_the_command_line_flag_and_the_scripts_pass_it`). (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): launched WITHOUT `--l2t-selftest` with `L2T_SCREENSHOT`, `L2T_BACKEND_CMD` (a failing script) and `L2T_SELFTEST_NO_TRAY` in the environment: the normal first-run window opened, the real runtime started, no screenshot file was written, the failing command was not run. With the flag, `node scripts/smoke.mjs desktop/release/mac-arm64` printed the first-run window text and `smoke: ok` (the custom scheme and the CSP do not blank the window).

### QA-SHELL-15  Linux AppImage does not carry PortAudio, and its start-up is never tested with a sandbox
Severity: S2 (code review, not reproduced; Linux not available)
Where: `electron-builder.yml:102-126`, `scripts/smoke.mjs:58-61`
Actual by code: the deb declares `libportaudio2` and the comment says the runtime fails at import without it, but the AppImage is the other Linux target and has no dependency mechanism: on a machine without `libportaudio2` the runtime dies at start and the user lands in QA-SHELL-2. Separately, `smoke.mjs` passes `--no-sandbox --disable-gpu` on Linux, so CI never checks that the packaged app starts with Chromium's sandbox; on Ubuntu 23.10+/24.04, where unprivileged user namespaces are restricted, an AppImage normally refuses to start without that flag.
Status: FIXED (code review, not run on Linux) - the runtime spec bundles the build machine's libportaudio and the runtime hook points `ctypes.util.find_library('portaudio')` at it, which is the only lookup sounddevice makes on Linux; `scripts/build_server.py` fails if the bundle has none; the deb keeps its dependency. The hook's lookup is tested (`test_the_hook_answers_the_portaudio_lookup_with_the_bundled_library`). CI smoke now runs with Chromium's sandbox: the workflow gives `chrome-sandbox` its setuid owner and `scripts/smoke.mjs` runs in mode `prefer` (sandbox first, `--no-sandbox` only with a warning annotation if the runner refuses). Whether the helper is honoured on `ubuntu-latest` is not known until the first run. (shell fixer)

### QA-SHELL-16  Release workflow: two jobs publish to the same GitHub release; signing leaves every Mac update without its permission grants
Severity: S3 (code review, not run)
Where: `.github/workflows/release.yml:34-54` and `245-261`, `desktop.yml:12-16`, `scripts/dist.mjs:94-103`
Actual by code: `desktop-release` and the Qt `build` job both call `softprops/action-gh-release` for the same tag at the same time (`generate_release_notes: true` in both). Whoever loses the create race depends on the action's retry; not verified. Then the macOS asset built in CI has no identity, so `dist.mjs` signs it ad hoc and the designated requirement is a cdhash: the Microphone and Accessibility grants of this bundle id are orphaned by every release (CLAUDE.md measured this for the Qt build and fixed it with a stable certificate; the Electron CI path does not have one). The release is also not notarized, and the Windows installers are unsigned. The workflow is still named "Build Windows release" while it now publishes Linux and macOS assets, and it does not check that the tag equals `desktop/package.json` (`tests/test_version.py` does that only in the test suite).
Status: FIXED (workflow not run; YAML parses, `actionlint` is not installed) - the Qt build no longer publishes: a separate `publish-qt` job (the only Qt job with `contents: write`) creates the release, and `desktop-release` waits for it (`needs`) and attaches to it, so the two cannot race; the workflow default is `contents: read`; third-party actions are pinned by commit (`setup-uv`, `action-gh-release`); `desktop-release` checks the tag against `desktop/package.json`; the workflow is renamed Release. The ad-hoc signing of CI Mac builds is documented in `release.yml`, README and plan.md (permissions are asked again after each release; a local build with the self-signed certificate keeps them); notarization and Windows signing remain unset. Tests: `test_only_the_jobs_that_publish_hold_a_write_token`, `test_the_two_release_jobs_cannot_race_for_the_same_release`, `test_third_party_actions_are_pinned_by_commit`. (shell fixer)

### QA-SHELL-17  No file associations on Windows and Linux; Windows portable unpacks 250 MB on every start
Severity: S3 (code review)
Where: `electron-builder.yml:46-62, 92-96, 102-111`
Actual by code: `fileAssociations` sits under `mac:` only, so the NSIS installer and the deb register no handler for audio or video and "Open with Lazy to Text" is not offered (spec 007 US7 #2 is only reachable by command line there). The `portable` target is electron-builder's self-extracting wrapper, which unpacks the whole app, runtime included, to a temp folder at every launch; start time and disk traffic follow the size of `resources/backend`.
Status: FIXED for file types, documented for portable - macOS CFBundleDocumentTypes already existed (rank Alternate); Linux gets `mimeTypes` in the desktop entry; Windows gets `desktop/build/installer.nsh`, which adds the app to OpenWithProgids for the eleven extensions without becoming the default (electron-builder's `fileAssociations` writes the extension's default class, which would take over a user's .mp3). The NSIS script could not be compiled on the development machine. The portable build still unpacks to a temporary folder on every launch: that is how electron-builder's portable target works, and it is stated in `electron-builder.yml`, the README and plan.md (WON'T FIX the unpacking). (shell fixer)
Re-verified 2026-10-24 on the rebuilt packaged app (scratch HOME and --user-data-dir, `--l2t-selftest`): the portable note is in `electron-builder.yml` (portable section), README.md ('The Windows portable build unpacks...') and plan.md; nothing more to do. The NSIS script is still not compiled anywhere: the first Windows CI leg is the test.

### QA-SHELL-18  Info.plist ships Electron's boilerplate
Severity: S4
Where: packaged `Info.plist`
Actual: `NSCameraUsageDescription` (`This app needs access to the camera`), `NSBluetooth*`, `NSAudioCaptureUsageDescription` (`This app needs access to audio capture`) and `NSAppTransportSecurity` with `NSAllowsArbitraryLoads = true` are the Electron defaults; the app uses none of them. 55 Chromium `*.lproj` locale folders are shipped; the repository's own `LICENSE` is not included in the bundle (only `LICENSE.electron.txt`).
Status: FIXED - `desktop/build/after-pack.cjs` removes the camera, Bluetooth, audio-capture usage strings and `NSAppTransportSecurity` from `Info.plist` (checked on the rebuilt app), Chromium locales are limited to en-US and ru (`electronLanguages`), and the repository `LICENSE` and `THIRD_PARTY_NOTICES.md` ship in Resources. (shell fixer)

---

## Covered, no defect

- Close button hides the window and the app stays (System Events, 2 runs); second launch with no arguments and with a file argument shows and focuses the window and forwards the file (macOS, `second-instance`); the forwarded wav was transcribed ("5 words"). Cold start with a file argument delivered the file 3 of 3 times (no lost `file-open` race).
- Single-instance lock across two Electron copies with different `userData` and one `HOME` (real runtime): second copy refuses and starts no second engine (FR-011), apart from QA-SHELL-11.
- Orphans: `kill -9` of Electron while idle (1 run) and while recording (1 run) leaves no runtime, resource tracker or worker process after 2 s; `SIGTERM` of Electron stops everything within 1 s; `kill -9` of the runtime takes its worker with it; quit through `l2t:quit` while recording took 1.3 s, runtime and children gone. Stdout noise before the ready line (a script printing text and `{"progress": 1}`) is ignored; the 60 s timeout fires on schedule and the hung child is killed.
- Capsule: appears on recording, shows with the main window closed, takes no keyboard focus (frontmost stayed the foreground app), hides on cancel and on idle after the delivery period, no state dip between recording and processing; delivery text and outcome (`copied`, `Cmd+V`) shown. Placement is bottom-centre (already recorded as a Known Gap).
- Tray exists and offers `Show window` and `Quit` (System Events).
- Packaging: `codesign --verify --deep --strict` valid; designated requirement certificate-anchored (local identity), hardened runtime flag on the app and on the runtime binary; app and runtime carry `device.audio-input`; patched PortAudio with `.patched.json` marker is inside the runtime; `app.asar` holds only `electron/`, `dist-renderer/`, `assets/`, `package.json` (no source maps, no config, no secrets; `grep` of the runtime for the user name found nothing); bundle id `ai.eora.lazytotext.desktop`, version 0.1.23 equal to `pyproject.toml` and `package-lock.json`; `NSMicrophoneUsageDescription` is the app's own text; app 512 MB of which runtime 254 MB; runtime start about 1 s with a fresh profile.
- Renderer isolation: `contextIsolation`, `sandbox`, no `nodeIntegration`; `require` and `process` are undefined in the page; the bridge exposes named capabilities only; `open-external` accepts only `http(s)`; `show-item` only absolute paths; `will-navigate`/`window.open` handled on the main window (see QA-SHELL-13 for the gaps).
- Workflows (read): `uv sync --frozen`, Node 22 against `engines >=22.12`, runtime built and smoke-run before packaging, the packaged unpacked app started once per platform, `fail_on_unmatched_files: true` for the Electron assets, artifact names do not collide with the Qt ones, `tests.yml`-style separate steps.

## Not tested, and why

- Windows and Linux in every respect: tray click behaviour, transparent capsule without a compositor (`transparent: true` gives an opaque black rectangle on X11 without one), `setAlwaysOnTop('screen-saver')` and `setVisibleOnAllWorkspaces` on Windows (no-ops) and Wayland, NSIS defaults (per-user, shortcuts: a Desktop shortcut is created by default, the Qt installer left it unchecked), deb desktop file and categories, Windows `child.kill('SIGTERM')` being `TerminateProcess` on the runtime only (worker survives if the runtime does not exit in 2.5 s).
- Capsule over a full-screen app and across Spaces on macOS: my attempt to put TextEdit in full screen was blocked by an automation prompt and I stopped; it is not evidence either way. Code uses `visibleOnFullScreen` with `skipTransformProcessType`, so the app stays a regular Dock app, unlike Qt's accessory mode.
- Multiple displays and display removal: no second display; by code, the capsule is placed once per appearance and no `display-removed` or `display-metrics-changed` handler exists (spec 007 US2 #3).
- Tray glyphs and per-state icons: the status item sits under the notch on this machine (System Events reports x=989, nothing is drawn at that position), so the image could not be judged.
- Microphone and Accessibility prompts for a fresh bundle id, `.dmg`/`.zip`/installer artifacts (only the unpacked app exists), notarization, `spctl` (the local build answers `rejected`, as documented), a real Windows or Linux CI run, the release job race.
- Quit while a transcription is processing, and Cmd+Q with a very long load, were not timed separately; quit while recording simply discards the recording (no confirmation; the Qt behaviour was not compared).

## Ranked summary

1. QA-SHELL-1 (S1) a dead runtime is invisible: stuck RECORDING capsule, no message, no restart.
2. QA-SHELL-2 (S2) runtime start failure shows a raw IPC error with no retry or log path.
3. QA-SHELL-3 (S2) no window for up to 60 s during a slow start.
4. QA-SHELL-4 (S2) no tray means a live invisible app (and Linux tray-less desktops hide the window forever).
5. QA-SHELL-15 (S2, code) AppImage lacks PortAudio; CI never starts the app with the sandbox on.
6. QA-SHELL-5 (S3) delivery capsule clipped.
7. QA-SHELL-12 (S3) default fuses: `ELECTRON_RUN_AS_NODE` reuses the app's microphone grant.
8. QA-SHELL-16, 17, 7, 8, 9, 10, 11, 13 (S3) release race and ad hoc Mac signing, associations and portable unpack, relaunch bug, missing Window menu, no geometry, English-only shell strings, dialog behind other windows, no CSP.
9. QA-SHELL-6, 14, 18 (S4).

File: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/shell.md`
Evidence: `.../qa/evidence/shell-capsule-after-runtime-kill.png`, `shell-backend-missing-error.png`, `shell-capsule-delivery-clipped.png`.
