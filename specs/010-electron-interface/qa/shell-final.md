# QA final round: shell (Electron main process and packaged app)

Tester: shell, final round. Date: 2026-10-24. Platform: macOS 26 arm64 only; Windows and Linux are code review.

Build under test: `desktop/release/mac-arm64/Lazy to Text.app`, rebuilt by `/private/tmp/claude-501/rebuild.sh`
(`rebuild.done` read `OK`, bundle written 16:48-16:49). `codesign --verify --deep --strict` passes; designated
requirement is certificate-anchored; hardened runtime flag set.

How it was run. Every launch used its own `HOME` and its own `--user-data-dir` under the scratch directory, with
`--l2t-selftest` where a hook was needed and a Chrome DevTools port (18564-18734) per launch. The model
`vosk-ru-small` was symlinked into each scratch cache. Auto-paste was switched off in the profile used for dictation, so
nothing was pasted into other windows. Keys were posted with Quartz from the project venv (`ctrl+f8`, `ctrl+f9`);
speech was `say -v Milena` into the real microphone. Windows were read with System Events, menus and the tray menu
likewise. `/Applications/Lazy to Text.app` and the real profile were not touched. Every process I started has been stopped.

Environment notes (not product defects):
- The disk filled up to 100 % (152 MB free) during the round, from several testers at once. One of my launches had a
  half-copied model and failed to load; I deleted my own scratch copies and symlinked the model instead.
- Other testers run the same packaged binary on this machine and take the focus, so "frontmost" checks were only
  reliable when the app was started with `open -n --env HOME=... "<app path>" --args --user-data-dir=...` (explicit
  bundle path, scratch profile).
- The microphone also hears whatever else plays on this Mac. Two dictations delivered other people's speech; I did not
  keep or quote it, and I removed the screenshots that showed it.

## Result table

| ID | Result | Evidence (this round) |
| --- | --- | --- |
| QA-SHELL-1 runtime death | PASS | Recording started (capsule `RECORDING`, 2 windows). `kill -9` of the runtime: page's `l2t.backend.onExit` got `{code:null, signal:'SIGKILL'}` within 3 s; capsule gone (windows 2 to 1); the window shows `ENGINE STOPPED`, the explanation, the log path, `Show log file` and `Restart`; no worker left. `Restart` button: `IDLE`, new runtime, event stream of the main process re-established (a recording after it showed the capsule again). Tray menu after the kill: `Show window, Restart engine, Quit`; its Restart item brought the engine back and the window recovered (1 run each). A `SIGSTOP`-ed runtime: banner after 61 s, runtime killed by the supervisor. |
| QA-SHELL-2 start failure, Retry | PASS | Stub exiting 3 on the first start and starting the real runtime on the second: error window `The engine did not start / The engine stopped while starting (exit code 3). / Details / Log file: <path> / Retry / Quit`; Retry opened the normal window, the error window closed, the model was ready (2 runs; the first run was my own mistake, the stub did not pass `--allow-origin`, which the real shell adds itself, and the window then said "engine not responding"). |
| QA-SHELL-3 loading window | PASS | Stub that prints noise and sleeps: window at 3 s reading `Starting Lazy to Text / Starting the speech engine. The first start can take a minute.`; closing it ended the app and killed the stub child. |
| QA-SHELL-4 no tray quits | PASS | `L2T_SELFTEST_NO_TRAY=1`, red button via System Events: process and runtime gone after 4 s. |
| QA-SHELL-5 capsule clipped | PASS | A long delivery text on the real capsule (dark and light): rounded corners on both sides, the second line ends with an ellipsis, nothing cut at the window edge. |
| QA-SHELL-6 delivery timing | PASS | Capsule text was present 3 samples at 1 s spacing after the stop and empty at the 5th (about 3.2 s). Code constant `DELIVERY_MS = 3200`. |
| QA-SHELL-7 relaunch | NOT RE-TESTED | Nothing in the renderer calls it; only `main-ipc.test.js`. |
| QA-SHELL-8 Window menu, Cmd+W | PASS | Menu bar `Apple, Lazy to Text, Edit, View, Window`; Window menu `Minimize, Zoom, Close, (Close All, added by macOS), screens 1-6, Bring all to front`; Cmd+W (key code 13) hid the window and the app stayed; the Window menu entry `Models` brought the window back on that screen. |
| QA-SHELL-9 geometry | PASS | Moved to (140,120), 1000 x 650, SIGTERM: `window-state.json` had the same values and the relaunch came back at (140,120) 1000 x 650. A state file with x=9000: window centred at (528,328), size kept. |
| QA-SHELL-10 menus ru/en | PASS with a leftover (F1) | `ui.language: ru`: `Apple, Lazy to Text, Правка, Вид, Окно`, Window menu in Russian. Default (en): `Edit, View, Window`. Tray menu `Show window / Quit` (en). Four macOS role labels stay English in Russian mode: see QA-SHELL-F1. |
| QA-SHELL-11 second launch dialog | PASS | Started with `open -n` and a scratch profile against a running copy with the same `HOME`: second process frontmost with one dialog window, no runtime child, exited after Return; the first copy kept running. Exec'd from a terminal the dialog is not activated (macOS does not activate such a process; the focus also went to another tester's app). |
| QA-SHELL-12 fuses | PASS | `@electron/fuses read --app`: RunAsNode, NodeOptions variable, inspect arguments, file-protocol privileges Disabled; asar integrity and OnlyLoadAppFromAsar Enabled. The tool (older than Electron 45) prints one fuse as `undefined is Enabled`; cookie encryption stays Disabled by decision. |
| QA-SHELL-13 CSP, navigation, IPC sender | PASS | CSP meta present on the page: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src http://127.0.0.1:*; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'`. Every screen opened, no console error, no `Network.loadingFailed` or CSP violation recorded across Transcribe, Models, History, Post-processing, Settings, Logs, Transcribe. Fonts: JetBrains Mono (latin and cyrillic), Inter and Source Serif 4 all load from `l2t-app://` (`document.fonts.load` returned 1 entry for each weight and style I asked). `location.href` to `file://` and `data:` in the main window and `file://` in the capsule: no navigation; `window.open` returned null; `openExternal` refused `ftp:`, `file:` and `l2t-app:`; a fetch of `l2t-app://app/../../../../etc/hosts` is blocked by the page policy. |
| QA-SHELL-14 hooks need the flag | PASS | Started without `--l2t-selftest` with `L2T_SCREENSHOT`, `L2T_BACKEND_CMD` (failing script), `L2T_SELFTEST_NO_TRAY`, `L2T_SELFTEST_DROP` and `L2T_DEV` in the environment: normal window, real runtime, tray present, no screenshot written; View menu has no Reload or DevTools. |
| QA-SHELL-15 AppImage PortAudio and sandbox | NOT RE-TESTED | Linux, code review only; unchanged. |
| QA-SHELL-16 release workflow | PASS (code review) | See "Workflows" below. |
| QA-SHELL-17 file associations, portable | PASS (code review, NSIS not compiled) | Unchanged from the earlier retest; the first Windows CI leg is the test. |
| QA-SHELL-18 Info.plist, notices | PASS | No camera, Bluetooth or audio-capture strings, no `NSAppTransportSecurity`; `NSMicrophoneUsageDescription` is the app's own. Framework locales limited to en and ru. `LICENSE` (identical to the repository's), `THIRD_PARTY_NOTICES.md` (153 lines), `licenses/GPL-2.0.txt` and three OFL texts are in `Resources`. |
| QA-SEC-R5 bridge and restart event reach any page | PASS | After a restart the connection event went to the app pages only (capsule and window both followed the new runtime). The forced-foreign-page case is covered by `shell-main-flow.test.js`; not repeated by hand. |
| QA-SEC-R6 token on `/events` (shell side) | PASS | The main process opens `/events?ticket=...` (one ticket per connect); a direct `GET /events?token=` is 401; a ticket works once (200, then 401). No launch token in the argv or environment of the Electron or runtime processes of my launches. |
| Real hotkey dictation | PASS | `ctrl+f8` posted with Quartz: state `RECORDING`, capsule window up; spoke; `ctrl+f9`: history line written (`сегодня хорошая погода ... в упакованном приложении`); capsule showed `ОБРАБОТКА` then `СКОПИРОВАНО — НАЖМИТЕ CMD+V` with the text, then went away; clipboard held the text. 2 runs. |
| 30 s dictation | PASS | 38.5 s of speech (74 words) by hotkey: whole text in history, first and last sentences intact, delivered to the clipboard and the capsule. |
| 67 s file through the drop hook | PASS | 78 s WAV dropped through `L2T_SELFTEST_DROP` (CDP drag and drop, `--l2t-selftest`): 155 words, 1126 characters, first and last sentences present, no cut at a chunk limit. |
| Drop of files, `webUtils` path | PASS | Dragged a WAV, and a WAV in `папка с пробелом/файл ё №1.wav`, through `Input.dispatchDragEvent` onto the page: both transcribed with the right names; `pathForFile` works under the custom scheme. |
| Native dialogs through the bridge | PASS | `openFile`, `saveFile`, `openDirectory` and `confirm` all opened native dialogs from the page (no `Not allowed.`) and returned `null` / `1` on Escape; the `L2T_SELFTEST_DIALOG=confirm` hook returned `{"kind":"confirm","result":0}` on Return. `clipboard.writeText`, `backend.logPath()` and `backend.restart()` also work from the page. |
| Second instance, file forwarding | PASS | Window hidden with Cmd+W, then a second launch with the same profile and a WAV argument: window shown, file transcribed (8 words), second process exited at once. |
| Cold start with a file argument | FAIL | See QA-SHELL-F2. |
| `l2t-app://` scheme | PASS | Reload keeps the page, fonts and assets load, no DevTools entry in the packaged menu, links go to the browser only for http(s) (not clicked, to keep the user's browser closed; the refusal paths were exercised). |
| Window background at first paint | PASS | Hid the page (`display:none` on the root) so the window's own background shows: light (`-NSRequiresAquaSystemAppearance YES`, `prefers-color-scheme` false) is the cream `#fbf1c7` (`evidence/shell-final/window-background-light-first-paint.png`); dark is `#282828` by pixel read. The start-up window's page follows the same palette in both modes. |
| Processes after quit / kill -9 | PASS | Cmd+Q: process gone in 1 s with no child. SIGTERM: everything gone within 4 s. `kill -9` of Electron (idle, after a restart): runtime and worker gone within 4 s. |
| THIRD_PARTY_NOTICES in the app | PASS | See QA-SHELL-18. |
| CI: `release.yml`, `desktop.yml` | PASS (review) | See "Workflows". |

## New defects

### QA-SHELL-F1  Four macOS role labels stay English in Russian mode
Severity: S4
Where: `desktop/electron/main.cjs` `menuTemplate` (`role: 'about'`, `'hide'`, `'hideOthers'`, `'unhide'`)
Steps: 1. `ui.language: ru`. 2. Start the packaged app. 3. Read the application menu with System Events.
Expected: the app menu is Russian like the rest (`Настройки…`, `Выйти из Lazy to Text` already are).
Actual: (reproduced 1 time) `About Lazy to Text, Settings… as Настройки…, Hide Lazy to Text, Hide Others, Show All, Выйти из Lazy to Text`: four items in English next to Russian ones, although the system language here is Russian. The claim in QA-SHELL-10's Status that these follow the OS language does not hold: the bundle declares no `CFBundleLocalizations`, and the labels come out English. The same menu in English mode shows a Russian `Закрыть все` in the Window menu (added by macOS for the Close item), so the mix goes both ways.
Evidence: System Events readout above.
Suspected cause: role labels are left to Electron; give them explicit `label` values from `strings.cjs`.
Status: FIXED - the four application-menu roles carry explicit labels from `strings.cjs` (`about`, `hideApp`, `hideOthers`, `showAll`), `electron/main.cjs`, `electron/strings.cjs`; verified by `main-ipc.test.js` 'labels the macOS application-menu roles itself'. Not re-read with System Events.

### QA-SHELL-F2  A file passed at a cold start is dropped, and the window then says "No model is loaded yet"
Severity: S2 (a regression: the earlier retest delivered the file 3 of 3 times)
Where: `desktop/electron/main.cjs` (`openMain` sends `l2t:file-open` at `did-finish-load`), renderer `lib/transcribe.js:181-187` (`not_ready` branch)
Steps: 1. Start the packaged app with a scratch profile and a WAV as the argument (`"Lazy to Text" --user-data-dir=... file.wav`, or Open With from Finder). 2. Wait 12 s.
Expected: the file is transcribed once the model is ready, as it was when the app is already running (second-instance path: 8 words in 49 ms).
Actual: (reproduced 3 of 3, once on a warm profile, twice on a fresh one; the same launch without the file argument is fine, 2 of 2) the Transcribe screen shows the amber line `No model is loaded yet. Download one or load the one you chose.` with an `Open models` action and no transcript. The status strip says `Current model: vosk-ru-small` and `IDLE`, the runtime log says the model was ready one second after the start, and the line never clears by itself. Dropping the same file again then works. The user's file is silently lost on every cold "Open with".
Evidence: DevTools text of the page after 12 s and after 22 s; `app.log` of the scratch profile (model ready at the start second).
Suspected cause: the main process hands the path over as soon as the page has loaded, while the runtime is still loading the model after its ready line. `files.transcribe` answers `not_ready`; at that instant the engine state is `idle` and `modelLoaded` is false, so the "nothing is loading and nothing will be" branch fires, and its sticky line is never cleared when the model arrives. Either queue the file until the model is ready (or until the first `model_loading` / `ready` state) or retry on `not_ready` while the runtime is starting; the sticky status needs clearing on `modelLoaded`.
Status: FIXED - main no longer sends the path once at did-finish-load. `electron/fileinbox.cjs` queues it and pushes `l2t:file-open` after each load, re-sending every 1 s (up to 60 times) until acknowledged; the preload acknowledges every path it hands to an `onFileOpen` callback and ignores a repeat of the same path within 2 s. API for the renderer (already wired in `lib/transcribe.js` by the renderer fixer, which also holds the file until the model is loaded):
  - `window.l2t.onFileOpen(cb)` - unchanged; cb(path); auto-acknowledged.
  - `window.l2t.ready()` - call after `onFileOpen` is subscribed; everything queued is pushed at once.
  - `window.l2t.pendingFiles()` - Promise<string[]>: queued paths not already pushed to a ready page; clears the queue.
  Verified by `shell-fileinbox.test.js` (7 cases), `test_the_preload_offers_the_file_handshake_and_the_pull_route`, and the repro on the rebuilt packaged app (scratch HOME, vosk linked, `--user-data-dir`, WAV argument): transcript shown with `4 words` 3 of 3, no warning line.

## Observations that are not defects (or not reproduced)

- Light mode, capsule: one of two light-mode delivery screenshots showed a dark capsule pill. The next two runs (and a read of the pill's colour at delivery time, `rgb(235, 219, 178)`, `data-mode=light`) showed the correct light pill. I could not reproduce it a second time, so it is not filed.
- `ps` showed an orphaned runtime (`ppid 1`) belonging to another tester's profile (`sec-final`). All my `kill -9` and SIGTERM cases left none, so I could not tie it to the app; it is the other tester's to explain.
- `ELECTRON_RUN_AS_NODE`, asar tamper and cookie encryption: covered by the security retest, not repeated.

## Workflows (read, not run)

- `release.yml`: top-level `contents: read`; `write` only in `desktop-release` and `publish-qt`; `desktop` calls `desktop.yml` with no extra permissions; `desktop-release` needs `[desktop, publish-qt]` with `!cancelled() && needs.desktop.result == 'success' && startsWith(github.ref, 'refs/tags/v')`, so it runs when the Qt job was skipped or failed and never on `workflow_dispatch`; `publish-qt` needs `build`, tag only. The release is created by the Qt job and attached to by the Electron job, so the two cannot race. Tag against `desktop/package.json` is checked. YAML parses; job names in `needs` exist. Concurrency groups differ (`release-<ref>` and `desktop-Release-<ref>`), so the called workflow cannot cancel its caller.
- `desktop.yml`: `contents: read`, three-platform matrix (`fail-fast: false`), `uv sync --frozen`, runtime tests then packaging tests then renderer tests, runtime built and smoke-run before packaging, Linux sandbox helper then `smoke.mjs` in mode `prefer`, artifacts per platform with `if-no-files-found: error`.
- Third-party actions are pinned by commit (`setup-uv`, `action-gh-release`). `action-gh-release`'s `v3` tag has since moved to another commit than the pinned one; that is normal for a pin, but nothing in the repository tracks it (Dependabot for `github-actions` would). `actions/setup-node@v6` while `v7.1.0` exists; harmless.
- Not verified: whether `generate_release_notes: true` in the second job leaves the first job's release body alone when it updates the existing release (action behaviour, only a real tag run shows it).
- Local check: `tests/test_desktop_packaging.py`: 43 passed.

## Covered, no defect (beyond the table)

Main window geometry on an off-screen saved position; menu bar in two languages; tray menu with and without a dead engine; no `--token` in the argv of my runtimes; Retry flow; loading window closes with the app; capsule follows a restarted runtime; hotkeys survive an engine restart (the restart rebuilt the stream; a recording started after it).

## Not tested, and why

- Windows and Linux in every respect (tray, transparent capsule without a compositor, sandbox, NSIS, AppImage, portable): no machine.
- `open-file` events from Finder (the `open` route would use the default profile); only the argv and second-instance routes were run.
- Capsule on a second display and over a full-screen app: one display; unchanged from the earlier retest.
- Accessibility/Microphone prompts for a fresh bundle id, notarization, `.dmg` and `.zip`, a real CI run.
- Opening a link in the user's browser from the page (kept the browser closed).

## Ranked new defects

1. QA-SHELL-F2 (S2) a file given at a cold start is lost and the window claims no model is loaded.
2. QA-SHELL-F1 (S4) four application-menu labels stay English in Russian mode.

Evidence: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/evidence/shell-final/`
