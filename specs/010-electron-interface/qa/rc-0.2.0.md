# QA release candidate 0.2.0

Tester: RC QA. Date: 2026-10-24. Platform: macOS 26 arm64 only; Windows and Linux are code review.
Build under test: `desktop/release/mac-arm64/Lazy to Text.app` (rebuild.done `OK`), version 0.2.0, signed with
the local certificate, hardened runtime, designated requirement `identifier "ai.eora.lazytotext" and certificate root = H"b632..."`.

Every launch used a scratch `HOME`, its own `--user-data-dir`, a CDP port (19002), `--l2t-selftest`; model symlinked.

## Result table (written incrementally)

| Check | Result | Evidence |
| --- | --- | --- |
| Start-when-I-log-in: switch exists, default off | PASS | Settings > Startup, `aria-checked=false` on a fresh profile |
| ... turning it on applies live, persists | PASS | After the click: System Events login items gained `Lazy to Text` (path = the packaged .app), `start_at_login: true` in config.yaml, log line `Updated setting ui.start_at_login: False -> True`. After a restart the switch read true. |
| ... turning it off removes the item | PASS | Login item list back to the 12 baseline names; config false |
| ... cleanup | PASS | The only item I created was removed (list equals the baseline recorded before the test) |
| `--hidden` launch | PASS | System Events: 0 windows of the process, process alive, menu bar present; the page loaded and answered over CDP |
| About entry (macOS app menu) | PASS (partial) | `About Lazy to Text` opened the native panel: name, `Версия 0.2.0 (0.2.0)`. The credits text (description, licence, repository) is not exposed to System Events and I did not capture the screen, so it is checked in code (`aboutOptions`, main.cjs:463). Windows/Linux entry: code and tests only |
| Forced colours | PASS (emulated) | CDP `Emulation.setEmulatedMedia forced-colors: active` on the packaged window, Settings screenshot: system palette, framed buttons, visible focus rings, switch on/off distinguishable, current row marked. Not on Windows |
| Cmd+F on Logs | PASS | Synthetic Meta+F (CDP key event) with Logs open: focus moved to `input[type=search]` `Search logs`. 1 run, synthetic key |
| Hugging Face token link | PASS | In the Models > "Storage and access" drawer: `Get a token on huggingface.co`, href `https://huggingface.co/settings/tokens`, `_blank`, `noopener noreferrer`. Not clicked (would open the user's browser) |
| Tooltip on Clear logs | PASS | Mouse move over the button: a `role=tooltip` reading `Empty the log buffer. The log file on disk is not touched.` |
| Model card accessible description | PASS | `role=group`, `aria-labelledby` the title, `aria-describedby` = figures + description (both resolve to text), 16 cards |
| Capsule bottom right | PASS | While recording, the overlay window was at x=1528, y=1171, 520 x 96 on a 2056 x 1329 screen whose work area ends at y=1267 (Dock): right edge 2048 (8 px from the edge), bottom edge on the work area. The capsule showed `RECORDING / Speak now / 00:14` (timer read late, osascript calls were slow). No pixel screenshot: a full-screen capture shows the user's other windows, so none was kept |
| File associations vs `app/audio_formats.py` | PASS | Info.plist `CFBundleDocumentTypes`: 24 extensions, set-equal to `AUDIO_EXTS` (24), role Editor, rank Alternate. Not registered with Launch Services here |
| Cold start with a file argument | PASS | Fresh profile, `short.wav` (49 s, 109 words) on argv: transcribed after start-up, 109 words. Second instance with a file forwarded to the first and exited |
| First-run file hold | PARTIAL | With no model cached, the first-run page came up with `short.wav` on argv: nothing in app.log about a transcription while it was up, nothing on the Transcribe screen. After `Set up later` the shell showed the "No model is loaded yet" note; I could not tell a replay from a drop, because first-run only appears when no model exists, and without a model the replay has nothing to do. Only the unit test (`transcribe.test.js`) proves the replay |
| Real hotkey dictation (ctrl+alt+f11/f12, Quartz) | PASS | State RECORDING -> IDLE, history entry `сегодня хорошая погода я проверяю диктовку в рилис кандидате ноль два ноль`, delivery `copied` (auto_paste false). Side effect: the real clipboard now holds the last dictation |
| 30 s dictation | PASS | 29.4 s of Milena speech (about 55 words): 31.6 s recorded, whole text in history from the first sentence to `конец проверки` |
| File drop longer than 67 s (CDP drag, `--l2t-selftest`) | PASS | 49 s file: 109 words, all three markers; 118 s file: 263 words, all markers but one spelt differently, status IDLE, 0.4 s |
| Too-short double tap | PASS with a wording note | Two start/stop pairs inside 0.1 s: no crash, back to IDLE, log `Nothing was recorded: no audio came from the microphone` (see QA-RC-3) |
| Kill the inference worker, dictate again | PASS | `kill -9` of the worker: next dictation delivered normally, a new worker process appeared (2 runs of the first kill, 1 of the dictation) |
| Engine stopped after `kill -9` of the runtime | PASS | Page showed `ENGINE STOPPED / The engine is not running... Your history and settings are safe`, no runtime or worker left; `Restart` brought IDLE and a new runtime |
| Runtime with PySide6 blocked | PASS | meta-path blocker raising for PySide6/shiboken6/PyQt5/6, ran `app.server.__main__.main`: ready line, hotkeys active, recording stack built, no import attempt |
| `uv run --frozen lazy-to-text-server` | PASS | `--port 19001 --data-dir <scratch>`: `{"ready": true, "port": 19001, "token": ..., "pid": ...}`, config and logs created under the data dir, listening on 127.0.0.1 |
| Packaged runtime start | PASS | Every launch above; `build_server.py` smoke run `ready line printed, app.snapshot answered` in the build log |
| `scripts/check_translations.py` | PASS | `769 entries; 451 renderer and 45 runtime strings; 0 missing` |
| Relative links README / docs / md | PASS | script over `]( )`, `href`, `src`: 0 broken in 13 files, plus backticked repo paths in README, docs/*.md, AGENTS.md: only CLAUDE.md (see QA-RC-4) |
| Processes after quit | PASS | SIGTERM to the app: app, runtime, worker all gone in under 6 s (3 runs) |
| Settings persistence across restart | PASS | `start_at_login` true survived two restarts and read back on the Settings screen; config.yaml rewritten by the runtime. Hotkey and auto-paste values from the scratch config were honoured |
| History | PASS | Three dictations listed newest first with time, model, language, duration; Export and Clear history buttons present. Export itself (native save dialog) not driven; covered by `tests/server/test_safe_paths.py` |
| PySide6/Qt leftovers (grep) | PASS with leftovers | No import, dependency, lock entry or file in the packaged app (`Resources/backend` has no PySide/Qt/nvidia/cuda folder; `uv.lock` has only `nvidia-ml-py`, kept on purpose for the GPU readout and listed in the notices). Text leftovers are comments, docstrings and `.gitignore` lines: QA-RC-4 |
| README and docs links, site | PASS | Served `docs/` with `http.server` on 19001: `index.html` and `style.css` reference 8 local assets (fonts, 5 screenshots, favicon, site.js), all 200, none missing. Visual rendering of the site not checked in a browser (the shared Browser pane was being driven by another session) |
| Version places and suites | PASS | `uv lock --check` ok; pytest `1214 passed, 9 skipped` (12 s); vitest `393 passed` (29 files) |
| actionlint on all 6 workflows | PASS | actionlint 1.7.12 installed into a scratch venv (`actionlint-py`), exit 0, no findings |
| release.yml (single publisher) | PASS (review) | `desktop` reusable job (`workflow_call` present in desktop.yml), `release` job `needs: desktop`, only it has `contents: write`, tag/package.json/pyproject check, changelog section extraction (run locally for 0.2.0: 64 lines, not empty), `fail_on_unmatched_files`, prerelease when the tag has `-`. Manual dispatch builds only. The release does not wait for tests.yml (documented) |
| tests.yml, desktop.yml | PASS (review) | No Qt step or `QT_QPA_PLATFORM` left; `--frozen` everywhere; desktop.yml uploads the same artefact globs electron-builder.yml names |
| electron-builder.yml, NSIS, associations | PASS with notes | appId `ai.eora.lazytotext`; Inno GUID `{D7B4F3A2-...}` equals the one in the deleted `installer/lazy_to_text.iss` (`git show af6ec82^`); `OpenWithProgids` list and Info.plist both equal `audio_formats.py`; see QA-RC-1, QA-RC-2 and the NSIS risk below |
| macOS signing identity / TCC | PASS (local build) | Designated requirement `identifier "ai.eora.lazytotext" and certificate root = H"b6327a25..."`: the same certificate anchor and bundle id the classic build used (CLAUDE.md, Signing), so a grant made to the classic app should match. Not checked against a real classic grant. CI builds are ad hoc: QA-RC-1 |
| `build_server.py` checks | PASS | Log of the rebuild: `bundle checks passed`, `smoke run ... ready line printed, app.snapshot answered`; bundle 260 MB (`Resources/backend`), app 510 MB unpacked, `app.asar` 1.0 MB, Frameworks 243 MB. Installer artefacts (dmg/zip/exe) were not built here, so their sizes are not measured |
| THIRD_PARTY_NOTICES | PASS | No PySide6, Qt, shiboken or NVIDIA-wheel licence text; only `nvidia-ml-py` is named, matching `pyproject.toml` and the bundle |
| Russian completeness | PASS | See `check_translations.py` row; Electron-main strings (About, menus) have Russian entries (`strings.cjs`) and the new renderer strings (`Start when I log in`, `Get a token on huggingface.co`) are in `ru.*.json` |

## Defects

### QA-RC-1  Docs say macOS keeps its permissions, but the published macOS build is ad hoc
Severity: S3
Where: README.md "Coming from the classic app" (line 85 onwards) and "Signing on macOS" (line 602); CHANGELOG.md 0.2.0 "Changed, for people coming from the classic app" and "Upgrading from the classic app"; docs/index.html:248; .github/workflows/release.yml header
Steps: 1. Read the 0.2.0 changelog and README: "macOS keeps its Microphone and Accessibility grants", site: "The build is signed with a local certificate". 2. Read release.yml and README "Signing on macOS": the dmg and zip attached to the release are built on a CI runner with no identity, so they are signed ad hoc and macOS sees every release as a new app.
Expected: the user-facing text matches what the downloaded file does.
Actual: a classic user who installs the release dmg loses both grants (the grant was made to the certificate anchor, the new app is anchored to its own hash) and, on macOS, Accessibility is never prompted for. The site sentence about the local certificate is also wrong for that file. The statement is true only for a build made on a machine with the `Lazy to Text Signing` certificate.
Evidence: `codesign -dr-` of the local build (`certificate root`) against README.md:602 and release.yml lines 20-27; not reproduced end to end (needs a CI-built dmg).
Suspected cause: text written from the local build's behaviour.
Status: Fixed. README (Quick start, classic-app section), CHANGELOG 0.2.0, docs/index.html, AGENTS.md, CLAUDE.md, STATUS.md and the electron-builder.yml comment now say that the downloadable macOS build is ad hoc signed and not notarized (first launch: right-click, Open), that macOS asks for Microphone and Accessibility again after each install, and that only a locally built app signed with the `setup-signing.sh` identity keeps the grants. Not verified: a CI-built dmg end to end.

### QA-RC-2  New app id strands the 0.1.x Electron installs, and nothing says so
Severity: S3
Where: desktop/electron-builder.yml `appId`; CHANGELOG.md 0.2.0
Steps: 1. `git show af6ec82^:desktop/electron-builder.yml | grep appId` gives `ai.eora.lazytotext.desktop` (the id of 0.1.x). 2. 0.2.0 uses `ai.eora.lazytotext`.
Expected: the changelog covers people who run the Electron 0.1.x as well as classic Qt users; the Windows installer removes or replaces the 0.1.x install.
Actual: on macOS the Microphone and Accessibility grants of the 0.1.x app belong to the old id and are orphaned (a stale entry stays in Privacy & Security); on Windows the NSIS uninstall key is derived from the app id, so the old entry stays in Add or remove programs next to the new one (same default install folder, so files are overwritten). `installer.nsh` handles only the Inno key. The changelog speaks only about the classic app.
Evidence: git history above; static review, not installed.
Suspected cause: the id change was planned for Qt users only.
Status: Fixed, Windows part untested. CHANGELOG 0.2.0 has an "If you ran an Electron 0.1.x build" section. `installer.nsh` handled only the Inno key; it now also removes the old uninstall entry (electron-builder derives its key as a version 5 UUID of the app id, `bca6c7c7-4249-5a19-8a18-a14d3afba3fc` for `ai.eora.lazytotext.desktop`, not the literal id) and the old install key, but only when the old InstallLocation equals the folder the new install uses. A test pins the GUID against electron-builder's namespace. Never run on Windows (no makensis here).

### QA-RC-3  A too-short press says the microphone gave no audio
Severity: S4
Where: runtime log and the state message for `Nothing was recorded: no audio came from the microphone`; log line `No audio from the microphone. Restart the app if this keeps happening.`
Steps: 1. Packaged app, hotkeys ctrl+alt+f11 (start) and f12 (stop). 2. Post start then stop within 50 ms, twice.
Expected: a hint about the press being too short.
Actual: both runs: no crash, state back to IDLE, log blames the microphone and tells the user to restart the app (2 of 2).
Evidence: app.log of scratch profile hA, 22:55:36 to 22:55:37.
Status: Fixed. The recorder records why a stop returned nothing (`empty_reason`): a press that ended within 0.5 s with no frames at all is `too_short` and gets the "too short" outcome (kind `too_short`); the "No audio from the microphone. Restart the app" text remains for a stream that ran longer and delivered nothing. Regression tests in `tests/test_audio_recorder_stuck_stream.py` and `tests/test_state_manager_failure_outcomes.py`. Not re-run in the packaged app.

### QA-RC-4  Qt leftovers in text, comments and help
Severity: S4
Where: `.gitignore:122-130` (py2app backup and placeholder); `app/server/__main__.py` `--no-single-instance` help ("lock shared with the Qt application"); `app/config_manager.py` ui palette comment ("The Qt interface has its own two palettes"); `app/utils.py`, `app/config_manager.py` docstrings "py2app / PyInstaller"; `app/backends/subprocess_backend.py` `_is_py2app_bundle()` and `_child_spawn_env()` (dead code, CLAUDE.md:254 says so); README.md:36 names `LazyToText-Desktop-...-win-x64.exe` while the artefacts are `...-setup-x64.exe` and `...-portable-x64.exe` (electron-builder.yml `nsis.artifactName`, `portable.artifactName`); docs/index.html:235-236 `Lazy to Text Setup ... .exe`, `Lazy to Text-....dmg` do not match `LazyToText-Desktop-<v>-mac-arm64.dmg`; CLAUDE.md:847 `tests/services/test_clipboard.py` and :889 `scripts/dist.mjs` (real path `desktop/scripts/dist.mjs`).
Expected: after spec 011 only history mentions Qt and file names match the release assets.
Actual: as listed (grep and `ls`, every item seen once).
Status: Fixed, with a stated limit. Removed: `_child_spawn_env`, `_is_py2app_bundle`, the py2app spawn-executable branch and their 4 tests (the runtime is a PyInstaller build and `app/server/__main__.py` calls `multiprocessing.freeze_support()`; the QA run already started the worker with `_is_py2app_bundle()` False); the py2app lines of `.gitignore`; the `--no-single-instance` help; stale "Qt main thread", "py2app / PyInstaller" and "Qt-free" comments and docstrings in `app/`, `tests/`, the spec and the hook script; installer names in README and docs/index.html (setup-x64.exe, portable-x64.exe, mac-arm64.dmg/zip, linux-x86_64.AppImage, linux-amd64.deb, as the 0.1.24 release carries them); the two CLAUDE.md paths. Left on purpose: "as the Qt view did" parity notes in `app/server/handlers/*` and the renderer, the `LazyToTextQt` lock name, the PySide6 exclude guards, `scripts/make_icons.py` (still uses PySide6 as a drawing library), history in specs, `.impeccable/` and `.specify/` tool files.

### QA-RC-5  History says "every dictation and transcription", file transcriptions are not in it
Severity: S4 (possibly by design; the classic behaviour was not compared)
Where: History screen subtitle `Every dictation and transcription, newest first.`
Steps: 1. Packaged app, drop a 49 s and a 118 s WAV, transcribe. 2. Open History.
Expected: entries for the two files, or a subtitle that says dictations only.
Actual: History listed 3 entries, all dictations; the two file runs are absent (2 of 2).
Evidence: `transcription_history.jsonl` of profile hA has 3 lines.
Status: Fixed (by design). specs/004-history lists file transcriptions as never part of History (Assumptions), so the subtitle is now "Every dictation, newest first." with the Russian entry in `ru.json`; nothing records files. The spec's two mentions were updated.

## Covered, no defect

See the table. Beyond it: `--hidden` kept the window closed and the process alive; the login item was added and removed by the switch without a restart; a second launch with a file argument was forwarded; SIGTERM of the app left no runtime, worker or resource tracker behind.

## Not tested, and why

- Windows and Linux behaviour of the login switch (registry entry or XDG autostart), the About menu entry, forced-colours on real high contrast, the NSIS `customInit` (no Windows, no makensis). One risk read in the code: `ExecWait '$R0 /SILENT ... _?=$R1'` passes the Inno install folder unquoted, and `$R1` is under the user's profile, so a profile path with a space may reach the Inno uninstaller truncated. Not run.
- A real login with the item enabled (it needs a logout). macOS 13 and later ignore `openAsHidden` and arguments for login items (System Events reported `hidden: false`), so the hidden start at a real login relies on `wasOpenedAtLogin`, which I could not trigger.
- First-run hold with a replay that does work: first-run appears only when no model is cached, and then a replay has no model to run on, so only the held half was observed (table row PARTIAL).
- Clicking the Hugging Face link (it opens the user's browser), About panel credits text (not readable by System Events; a full-screen capture shows other windows), notarised builds, installers (dmg/zip/exe/AppImage/deb) and their sizes.

## Environment notes

- The login-item test added `Lazy to Text` to this user's login items for about a minute (path inside the worktree) and removed it; the list matched the 12 baseline names afterwards. macOS keeps a disabled record named `Lazy to Text` for that path in its background-items database (`sfltool dumpbtm`), which only the user can clear in System Settings, Login Items.
- Dictation put test sentences on the real clipboard; the last one is still there.
- One full-screen capture was taken by mistake while checking the About panel; it showed unrelated windows, was deleted at once and not read into this report.

## Ranked defects

1. QA-RC-1 (S3) permissions claim wrong for the CI-built macOS release.
2. QA-RC-2 (S3) app id change not handled for 0.1.x Electron installs.
3. QA-RC-5 (S4) History subtitle versus file transcriptions.
4. QA-RC-3 (S4) misleading message after a too-short press.
5. QA-RC-4 (S4) Qt leftovers and asset names in text.

No S1 or S2 found. Everything started for this report has been stopped (runtime 19001, app instances on 19002-19004, the static server).
