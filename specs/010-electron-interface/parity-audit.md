# Parity audit: what the Qt application does that the Electron interface does not

Purpose: the team has decided to delete the Qt interface and ship only the
Electron interface. This audit asks one question: is ANYTHING the Qt
application does or ships not covered by the Electron interface?

Read first: `specs/001` to `009` (baseline), `specs/010-electron-interface/spec.md`,
`plan.md`, `tasks.md` and the six `parity-*.md` files. Then the Qt code
(`app/gui/**`, 63 tracked files, about 16.9k lines; `tests/gui/**`, 45 files,
about 20.5k lines) and the Electron code (`desktop/electron/*.cjs`,
`desktop/renderer/src/**`, `app/server/**`).

Method and evidence:

- Every string the Qt code passes to `bind`, `tr_text`, `tr_format`,
  `tr_count`, `translate` or `mark` (334 distinct sources, extracted with the
  same `ast` walk `scripts/update_translations.py` uses) was looked up in the
  Electron renderer, the Electron main process and the Python sources the
  runtime ships. The 39 that did not match literally were then read by hand;
  most are Qt-only accessibility strings or re-worded, and the real findings
  are below.
- Every `get_setting` / `update_user_setting` / `get_section` call under
  `app/gui` (about 100) was compared with `settings.get`, the `settings.set`
  table and the rest of `app/server/handlers`.
- Qt behaviours (shortcuts, menus, window, Dock, tray, capsule, file open,
  single instance, theme, forced colours) were read in `main_window.py`,
  `app.py`, `dock_presence.py`, `mac_window.py`, `placement.py`,
  `window_chrome.py`, `theme.py`, `recording_overlay.py`, `tray_icon.py` and
  matched to `desktop/electron/{main,windows,preload,fileinbox,geometry}.cjs`.
- The runtime was started with a scratch folder
  (`uv run --frozen python -m app.server --data-dir <scratch> --no-single-instance --no-stdin-watch --token devtoken --port 58713`)
  and asked `app.snapshot`, `settings.get`, `models.list` and `files.formats`
  over `/rpc`: the config sections it exposes (`whisper hotkey audio clipboard
  audio_feedback history storage llm ui onboarding window`), 16 catalogue
  models, `capabilities.mute_output = true` on this Mac, and a 24-extension
  format list. The process was stopped afterwards; the worktree was not touched
  (only this file was written).
- Not done: the Electron window was not driven by hand here, and Windows and
  Linux were not run. Items that need those are marked "unverified".

---

## 1. Summary counts

| Class | Count |
| --- | --- |
| PORTED (table in section 4) | 78 |
| DELIBERATELY OMITTED (section 3, with the file that says so) | 14 |
| MISSING (section 2) | 18 |

MISSING by severity:

| Severity | Meaning | Count |
| --- | --- | --- |
| S1 | A core flow (dictate, transcribe, models, history) is lost | 0 |
| S2 | A real group of users loses a capability they have today | 1 |
| S3 | A feature or platform behaviour is lost, or cannot be shown to work | 5 |
| S4 | Polish, convention, accessibility or documentation parity | 12 |

No S1. The Electron interface covers every screen, every setting the Qt
settings page wrote, every dialog, the tray, the capsule and the file-open
paths. What is not covered is at the edges: the GPU build, run-at-login, the
upgrade path for people who have the Qt app installed, Windows high-contrast
mode, and tests that hold the macOS artifact together.

Two documentation facts found on the way (not gaps in behaviour):

- `parity-settings.md` says the version footer "stays outside the scroll,
  always visible". In `views/Settings.svelte` the footer is the last element
  inside the scroll container (the comment there says so). The sentence in the
  parity file is stale.
- `renderer/src/Popup.svelte` and `popup.html` (a `popup` Vite entry, listed in
  `guard.cjs:20`) are a one-line placeholder that nothing opens. Qt has no
  result popup either (delivery is reported by the capsule). Delete them as
  part of the cleanup; they are not a missing feature.

---

## 2. MISSING (ranked)

Format: id, severity, what, Qt reference, Electron state, suggested work.

### S2

**M1. S2. Windows NVIDIA GPU (CUDA) build and enablement path.**
Formally "omitted on purpose" by `spec.md` Assumptions (line 226) because Qt
still existed and could ship it. Deleting Qt removes the only route, so it
becomes a loss.

- Qt: `lazy_to_text.spec:108-133` sweeps `site-packages/nvidia/*/bin` DLLs into
  the bundle; `scripts/build-windows-cuda.ps1` (syncs `--extra cuda`,
  force-installs `onnxruntime-gpu`, names the output `LazyToText-CUDA`);
  `scripts/setup-cuda-windows.ps1`; `app/cuda_bootstrap.py:194` `ensure_cuda`
  (interactive prompt to install about 1.3 GB on first run); console script
  `lazy-to-text-ui-cuda` = `app.gui.app:main_cuda` (`pyproject.toml:86`);
  optional extra `cuda` (`pyproject.toml`); spec 009 User Story 5, FR-041,
  FR-044, FR-090. The README still promises it (README lines 83, 111,
  280-285, 309).
- Electron: `lazy_to_text_server.spec` has no NVIDIA sweep, `build_server.py`
  has no CUDA variant, `desktop.yml` has no CUDA leg, electron-builder has no
  second artifact name. `app/server/__main__.py:118-120` still calls
  `ensure_cuda()`, but under Electron stdin is a pipe (`backend.cjs` spawns
  with `stdio: ['pipe', ...]`), so `ensure_cuda` only logs
  "Install with: uv pip install --extra cuda" (`cuda_bootstrap.py:~215`), which
  is advice an installed-app user cannot follow (no `uv`).
- Work: port the DLL sweep into `lazy_to_text_server.spec` behind an env switch
  (the runtime hook `scripts/pyi_runtime_hook.py:74-95` already prepends
  `nvidia/*/bin` to the search path, so only the spec sweep is missing); add
  `scripts/build_server.py --cuda` (sync `--extra cuda`, force-reinstall
  `onnxruntime-gpu`); add a `windows-x64-cuda` leg to `desktop.yml` and a
  `LazyToText-Desktop-<v>-win-x64-cuda` artifact; replace the `ensure_cuda`
  prompt with a visible Logs/Settings message or drop it. If the decision is
  to drop GPU on Windows, say so in README and the engine pill hint, because
  README currently advertises it.

**Status: DROPPED by decision.** The CUDA/GPU build is not ported. Recognition runs on the CPU, and on Apple silicon through CoreML. The About text no longer mentions CUDA or NVIDIA; README and the site belong to the Qt-deletion pass and must say the same.

### S3

**M2. S3. Run at login (start with the OS).**
- Qt: `installer/lazy_to_text.iss:87` task `startupicon` ("Start Lazy to Text
  when Windows starts", unchecked by default) and `:100` the `{userstartup}`
  shortcut; spec 009 FR-045, US2 scenario 2.
- Electron: nothing. No `setLoginItemSettings` anywhere in `desktop/electron`,
  no NSIS option in `desktop/build/installer.nsh`, no Settings control. This is
  an app whose value is global hotkeys while it lives in the tray, so after a
  reboot it is not running until the user starts it.
- Work: Settings switch "Start with the computer" using
  `app.setLoginItemSettings({openAtLogin, args: ['--hidden']})` (macOS and
  Windows) and an autostart `.desktop` on Linux; start hidden to the tray; and
  an unchecked NSIS custom page or the same switch for portable users. Store
  the choice in `config.yaml` (one new key) or read it back from the OS.

**Status: PORTED (macOS and Windows unverified on a real login).** `ui.start_at_login` (default off) in `DEFAULT_CONFIG`; Settings > Startup switch "Start when I log in" (Russian entry in `ru.settings.json`); `desktop/electron/login.cjs` applies it with `app.setLoginItemSettings` (macOS, Windows; the portable exe is named, not its temp folder) or an XDG autostart entry (Linux, AppImage-aware); applied at every start from the snapshot and live from the `settings` event; a launch with `--hidden` (or macOS `wasOpenedAtLogin`) stays in the tray and shows no start-up page unless the engine fails. Not applied in an unpackaged run. Tests: `shell-login.test.js`, `shell-main-flow.test.js` (start at login), `settings.test.js`, `tests/server/test_settings.py`.

**M3. S3. Upgrade and coexistence with an installed Qt build.**
- Qt: Inno `AppId={{D7B4F3A2-8C5E-4D9F-9A1B-3F2E1D8C7B6A}}` (`.iss:44`),
  install dir `%LOCALAPPDATA%\Programs\LazyToText`, mutex name
  `LazyToTextQt_SingleInstance` (`.iss:26`); macOS bundle id
  `ai.eora.lazytotext` (`setup.py`).
- Electron: `appId: ai.eora.lazytotext.desktop`
  (`desktop/electron-builder.yml`, pinned by
  `test_the_app_id_is_not_the_qt_applications`). So a user who updates gets a
  second app next to the Qt one, the old Inno startup shortcut (if they chose
  it) launches the Qt app at login and wins the shared single-instance lock
  (`LazyToTextQt`), so the new app opens with "Another copy is already
  running"; macOS Microphone and Accessibility grants do not carry over
  (different bundle id). Config, history and models do carry over (same
  `platformdirs` folders), which is the good half.
- Work: an NSIS `customInit` that finds the Inno uninstall key (`..._is1` of
  the GUID above) and offers to run it; a README migration note for macOS (drag
  the old `.app` to the Trash, re-grant two permissions); consider renaming the
  lock from `LazyToTextQt` (see deletion inventory) only after the old
  installer is gone from circulation.

**Status: PORTED, Windows uninstall step UNVERIFIED.** `appId: ai.eora.lazytotext` (same as the Qt app); lock name `LazyToTextQt` kept; `test_the_app_id_is_the_same_as_the_application_it_replaces`. `installer.nsh` `customInit` looks for the Inno key `{D7B4F3A2-8C5E-4D9F-9A1B-3F2E1D8C7B6A}_is1` (HKCU, then HKLM), asks (answers yes when silent) and runs the old uninstaller in place with `_?=`. Never run: no makensis or Windows here; a test pins the text only. The installer stays per-user.

**M4. S3. Windows high-contrast / forced-colours mode.**
- Qt: `app/gui/theme.py:374` detects it through
  `SystemParametersInfoW(SPI_GETHIGHCONTRAST)`, drops the stylesheet, polls
  once a second; `DESIGN.md` section "Forced colours" (lines 653-677) and "The
  Defer Rule".
- Electron: no `forced-colors` media query anywhere in `desktop/renderer` or in
  the `@monos/ui` sources (rg finds none). Chromium applies its own forced-colour
  overrides to ordinary elements, so much of the page will follow the OS
  palette by default, but nothing was designed or checked: status colours that
  carry meaning (level meter, badges, focus ring), the capsule dot, and
  `forced-color-adjust` are all unexamined. "Unverified" is the honest word.
- Work: a `@media (forced-colors: active)` pass (system colour keywords for
  borders, focus ring and the capsule dot; text labels where colour carries
  meaning); a Chromium `forced-colors` emulation test in `desktop/tests`; check
  the transparent capsule window.

**Status: PORTED, checked by emulation, not on Windows.** `@media (forced-colors: active)` block in `app.css` (system colours only; focus ring, framed buttons, current row, pressed chips, switches, progress, meter, dots, selected card, capsule). Checked in Electron with `Emulation.setEmulatedMedia forced-colors: active`: switch on/off, current screen, focus ring and framed buttons render in system colours. Known loss: the palette swatches in Settings turn into empty bars (the names remain). The capsule's transparent window was checked by rule and test, not by pixels. Test: `forced-colors.test.js`.

**M5. S3. Nothing pins the Electron macOS artifact's PortAudio patch or worker.**
- Qt: `tests/test_bundle_contents.py:480`
  `test_the_bundle_ships_the_patched_portaudio` (marker
  `.patched.json`), `:525` and `:1014`
  `test_the_built_inference_worker_actually_runs`, `:1091` every Mach-O signed.
  They read `dist/Lazy to Text.app` and skip when it is absent.
- Electron: `scripts/build_server.py:patch_portaudio` installs the patched
  library and `desktop.yml` smoke-starts the unpacked app, but no test asserts
  the marker, that the library is signed, or that
  `Contents/Resources/backend/lazy-to-text-server` runs under the hardened
  runtime. Spec 010 FR-015 and plan Constitution VI say "a test pins both"; the
  entitlements half is pinned (`tests/test_desktop_packaging.py:112-170`), the
  PortAudio half is not. After the py2app tests are deleted nothing holds it.
- Work: port tests 480, 1014 and 1091 to look at
  `desktop/release/mac-arm64/Lazy to Text.app/Contents/Resources/backend` (skip
  when absent, like today); add a `.patched.json` check to
  `scripts/build_server.py check_bundle` so CI fails on the macOS leg.

**Status: PORTED.** `tests/test_desktop_packaging.py`: hardened runtime and microphone entitlement (config, `dist.mjs` signing flags), patched PortAudio in `build_server.py` (patch step order, vendored patch, marker), worker entry point (`freeze_support` first, `_worker_main`), and a built-app check that skips when no app exists. `check_bundle` now refuses a macOS runtime folder without `libportaudio.dylib.patched.json`. Signing and the worker actually running are still not exercised by any test.

**M6. S3. No Python-only way to run or launch the app.**
- Qt: `uv run lazy-to-text-ui` (`pyproject.toml:85`, `lazy-to-text-ui.py`) is
  the README quick start (README line 71) and spec 009 FR-090.
- Electron: the only launches are the installers, `npm run dev` (Node 22.12 or
  newer, `desktop/package.json` engines) and `python -m app.server`, which has
  no window. `[project.scripts]` has no entry for the runtime.
- Work: README quick start rewritten around the installers and
  `cd desktop && npm ci && npm run dev`; add `lazy-to-text-server =
  "app.server.__main__:main"` to `[project.scripts]`; keep `lazy-to-text-ui`
  off the list (it would import deleted code).

### S4

**M7. S4. Dock icon rule on macOS.** Qt: `app/gui/dock_presence.py:26`
`apply_dock_presence`, called from `main_window.py:274`; spec 007 FR-037 (Dock
icon only while the window is visible and the capsule is not; Dock click
restores the window). Electron: `windows.cjs:249` only calls `app.dock.show()`;
no `app.dock.hide()` anywhere, so the Dock icon stays after the window is
hidden to the tray. The Dock click does restore (`main.cjs:477`
`app.on('activate')`). Work: `app.dock.hide()` when the main window hides and
no capsule is up, `app.dock.show()` on show (mind that hiding the Dock icon
must not stop the capsule from floating over full-screen apps).

**Status: DELIBERATE, not ported.** The Dock icon stays while the window is hidden to the tray. Hiding it risks the capsule not floating over full-screen apps and the Dock click remains the way back; the menu bar tray icon is the primary handle. Revisit only with a full-screen measurement.

**M8. S4. Capsule position.** Qt: `placement.py:44` `bottom_right_position`,
spec 007 FR-007 (bottom-right, fixed margin). Electron: bottom-centre
(`geometry.cjs:72` `capsuleBounds`). `parity-capsule.md` "Differences and gaps"
records it as "left as the foundation made it", not as a decision. Work: decide
and write it down; one-line change in `capsuleBounds` if right is wanted.

**Status: PORTED.** Bottom-right of the work area of the display under the pointer (`capsuleBounds`, `Overlay.svelte` right-aligned); tests in `shell-geometry.test.js` and `shell-windows.test.js`.

**M9. S4. Capsule window state in the log.** Qt: `mac_window.py:112` writes
hidden, policy, level, visible, on-active-space and screen to `app.log` on each
appearance (spec 007 FR-008), because the overlay failing on a hidden app or
another Space leaves no other trace (CLAUDE.md "The overlay disappears without
an error"). Electron: `syncOverlay` (`windows.cjs:435`) shows the window and
logs nothing. Work: a `log.info` line from the main process into the runtime's
log (or `console` into the runtime's stderr tail) per appearance.

**Status: DELIBERATE, not ported.** No capsule window-state log line. It was added in Qt after a field report on a hidden app and another Space; Electron's `showInactive` plus the unhide in `syncOverlay` cover both and have shown no such report. Add the line when one appears.

**M10. S4. About on Windows and Linux, and the About content.** Qt: About is in
the app menu on every platform (`main_window.py:478-484`, `_show_about_dialog`
`:711`) and shows the app icon, version, description and link. Electron: the
menu template (`main.cjs:385`) has About only on macOS, as `role: 'about'`
(Electron's default panel: name, version, icon; no description, no link, no
`setAboutPanelOptions` call); on Windows and Linux About is reachable only
through the Settings footer button, and `AboutDialog.svelte` omits the icon
(recorded in `parity-settings.md`). Work: `app.setAboutPanelOptions` with the
description and the repository link; an About item under the app menu on the
other platforms that opens the same Modal (navigate then open).

**Status: PORTED.** About in the application menu on Windows and Linux navigates to Settings and opens the dialog; the macOS panel (`setAboutPanelOptions`) carries description, licence and repository link, rebuilt with the language. The dialog gained the licence line. Tests: `main-ipc.test.js`, `settings.test.js`.

**M11. S4. Find shortcut on Logs.** Qt: three searchable views (Models, History,
Logs; `main_window.py:418-440`, spec 007 FR-035). Electron: Models
(`Models.svelte:117`) and History (`History.svelte:153`) only;
`parity-logs.md` says a global Find "is not added here" and nobody added it.
Work: the same 6-line keydown in `Logs.svelte` focusing the search field.

**Status: PORTED.** Cmd/Ctrl+F focuses the search on Logs (`logs.test.js`).

**M12. S4. Screen order, default screen, icons, compact rail.** Qt order is
Models, Transcribe, History, Logs, Post-processing, Settings, Models first
(`widgets/sidebar.py:27-28`; spec 007 FR-024, so Cmd+1 is Models). Electron:
Transcribe, Models, History, Post-processing, Settings, Logs
(`views/index.js`, `main.cjs:SCREEN_IDS`), Transcribe first, so Cmd+1..6 mean
different screens than they did. No row icons, no icons-only rail below a
width threshold (FR-025, FR-030); the window minimum is 900x600 against Qt's
1100x680 and the sidebar is `min(14rem, 30vw)`. The kit draws text rows by
design, so icons and the rail are a design decision to record; the order is an
undocumented behaviour change for users with muscle memory. Work: state the
order in spec 010 or restore it (two arrays).

**Status: DELIBERATE, not ported.** The Electron order is Transcribe, Models, History, Post-processing, Settings, Logs (Cmd/Ctrl+1..6), Transcribe first as the daily screen. No row icons or icon rail: the kit draws text rows. Window minimum 900x600. Recorded as the decision in place of an accident.

**M13. S4. Link to where a Hugging Face token comes from.** Qt:
`shortcuts_view.py:1133` renders `huggingface.co/settings/tokens` as a link in
the token card hint. Electron `HfTokenCard.svelte` says the token is optional
and only for gated repositories but offers no link. Work: one
`window.l2t.shell.openExternal` link, as `AboutDialog.svelte` does.

**Status: PORTED.** Link in `HfTokenCard.svelte`, opened through `shell.openExternal` (`models.test.js`).

**M14. S4. "Clear logs" tooltip.** Qt `logs_view.py:242`: "Empty the log buffer.
The log file on disk is not touched." Electron `Logs.svelte` has the confirm
dialog but not the sentence on the button. Work: `title` or `use:tooltip`.

**Status: PORTED.** Tooltip on Clear logs, on a wrapper because the button is disabled when empty (`logs.test.js`).

**M15. S4. Whole-card accessible description on model cards.** Qt
`model_card.py:720` sets one accessible sentence per card (family, WER, RTF,
size, description). Electron cards are plain regions whose visible
contents carry the same words but with no per-card name beyond the heading
(`parity-models.md` notes this as a trade-off against nested interactive
controls). Work: `role="group"` with `aria-labelledby` on the title and
`aria-describedby` on the metric line.

**Status: PORTED.** Cards are groups named by the heading and described by the figures and the description (`models.test.js`; also read back in the browser).

**M16. S4. Window position is a different store.** Qt keeps `window.geometry`
and `window.screen` in `config.yaml` (`config_manager.py:309`,
`app_controller.py:1360`). Electron keeps `window-state.json` under Electron's
`userData` (`windows.cjs:150-170`). Behaviour is equivalent (screen-gone case
tested in `geometry.cjs`), but a Qt user's saved position is not carried over,
and after deletion `DEFAULT_CONFIG["window"]` and `["system_tray"]`
(`config_manager.py:228`, never read by any interface) are dead keys. Work:
remove both from `DEFAULT_CONFIG` and say so in the changelog; no migration
needed.

**Status: PORTED.** `window` and `system_tray` removed from `DEFAULT_CONFIG`, and `window` from the `app.snapshot` sections; nothing under `app/` or `desktop/` read them (the Qt readers go with `app/gui`).

**M17. S4. File open while the first-run screen is up.** Spec 007 FR-034 and
FR-039: a launch with a path must not transcribe behind the first-run page.
Qt only guaranteed ordering (the open was posted after `set_first_run`).
Electron: `installFileInbox` (`lib/transcribe.js:371`) receives paths and drops
whatever the first-run state is; `App.svelte` sets `current = 'transcribe'`
while `firstRun` keeps the shell hidden, so the run starts invisibly (and with
no model, waits for one). Work: ignore or queue opens while `firstRun` is true
and replay after it ends.

**Status: PORTED.** `shellShown` (`lib/nav.js`) is true only once the shell is up; opens and drops before that are held, the latest replayed (`transcribe.test.js`). Not driven through a real first-run screen with a real OS open.

**M18. S4. "Open with" coverage.** Qt offers itself for the generic UTIs
`public.audio`, `public.movie`, `public.video`, `public.mp3`, WAV, AVI, MPEG-4
(`setup.py:226-241`). Electron's association list is 11 extensions
(`electron-builder.yml fileAssociations`, `installer.nsh`, Linux `mimeTypes`),
while the runtime accepts 24 (`files.formats`: also ogg/opus/oga, wma, amr, ac3,
alac, avi, flv, 3gp, m4v, wmv, ts, aif). Work: add the missing extensions to
the three lists (keep Alternate rank so no default changes).

**Status: PORTED.** The 24 runtime extensions in the macOS associations, the Windows `OpenWithProgids` list (one list, `l2tEachExtension`) and the Linux MIME types; `test_the_app_is_offered_for_audio_and_video_on_all_three_platforms` and `test_every_runtime_format_has_a_mime_type_in_the_desktop_entry` compare them with `app/audio_formats.py`. Not installed on any OS.

---

## 3. DELIBERATELY OMITTED (with the file that says so)

The 14 items below stay omitted by decision (no change in this pass). M7, M9 and M12 are decided the same way, see their Status lines in section 2. M1 is dropped by decision. M6 is outside this pass.

| # | Qt behaviour | Where it is recorded |
| --- | --- | --- |
| 1 | Storage card and Hugging Face token card on the Settings page (Electron: Models screen drawer; Settings keeps four cards) | `parity-settings.md` "Page structure"; `parity-models.md` "Storage and Hugging Face token" |
| 2 | "Restart to apply" flow (`_on_restart_requested`, wired to nothing in Qt) | `parity-settings.md` "Permissions"; `spec.md` Assumptions |
| 3 | Settings "Back" button on first run (never visible in Qt) | `parity-models.md` "First run" |
| 4 | History row selection model, Enter and platform-Copy shortcuts on the current row, fitted column widths | `parity-transcribe-history.md` "History" |
| 5 | Focus hand-off before the mic-test button disables | `parity-settings.md` "Audio input" |
| 6 | "Radii and spacing keep their size" hint (false here: spacing scales) | `parity-settings.md` "Appearance" |
| 7 | Application icon in the About dialog (a page, not a native sheet) | `parity-settings.md` "Version and About" (see M10 for the part that is not covered) |
| 8 | Drag cursor refused for unsupported types during a drag (a browser cannot read names mid-drag; refused on drop with a message) | `parity-transcribe-history.md` "Transcribe" |
| 9 | Typed hotkey text fields (replaced by key capture plus "Type it instead") | `parity-settings.md` "Hotkeys" |
| 10 | Qt's two hand-built palettes (replaced by the kit's six palettes; Gruvbox is the default) | `spec.md` FR-004; `parity-settings.md` "Appearance" |
| 11 | Nominal catalogue size in the delete dialog (replaced by measured size) | `parity-models.md` "Deliberate differences" 1 |
| 12 | Processing time that grows with every edit; empty result as an error (now a warning) | `parity-transcribe-history.md` "Transcribe" |
| 13 | Intel Macs (pinned onnxruntime has no wheel; the Qt app had the same limit) | `plan.md` Known Gaps |
| 14 | Qt-only mechanics with no Electron meaning: smooth-scroll wheel (`smooth_scroll.py`), refresh-rate polling (`refresh_rate.py`), QSS cocoa spacing workarounds, Qt focus-ring helpers (`focus.py`) | `spec.md` FR-004 (kit owns look), implicit; nothing to port |

Improvements the Electron interface made over Qt (not gaps, listed so the
deletion does not read as a loss): Set-up-later now works; Reset hotkeys
reaches the live listener; a refused model switch writes nothing; a cancelled
load reloads the previous model; deleting a preset asks first; history delete
with undo; HF token never returned to the renderer; second launch brings the
first window forward instead of a dialog; engine death is shown with Restart.

---

## 4. PORTED table

Every row was checked in code. "Verified" means I also saw it answer from the
running runtime; otherwise it is read from source and the parity file.

### 4.1 Screens and controls

| # | Qt (file) | Electron evidence |
| --- | --- | --- |
| 1 | Models: search, language filter, sort, family chip filter (`models_view.py`) | `views/Models.svelte`, `components/models/filter.js`; plus family Select, Fastest sort |
| 2 | Model card: family, name, Recommended, Active, alias, HF link, WER/RTF/size with tooltips, clamp + Show more (`model_card.py`) | `components/models/ModelCard.svelte` (facts, `use:tooltip`, `line-clamp-3`, Show more) |
| 3 | Select / Download / Delete with confirm naming siblings (`model_card.py`, `app_controller.py:499`) | `ModelCard.svelte` buttons, `models.select/download/delete_info/delete` (`handlers/models.py`) |
| 4 | Cancel load, restore previous model (`app_controller.py:1684`) | `models.cancel_load`; `StatusStrip.svelte:62-92`; banner on Models |
| 5 | Loading pill percent, bytes or seconds (`topbar.py`) | `StatusStrip.svelte`, `statusFormat.js` |
| 6 | Whisper inference panel: language (17), VAD, beam 1-20, temperature, prompt (`inference_settings_panel.py`) | `InferenceSettings.svelte` kind `whisper`; limits clamped in `handlers/models.py:608-626` |
| 7 | Parakeet timestamps checkbox (`parakeet_inference_settings_panel.py`) | `InferenceSettings.svelte` kind `parakeet` |
| 8 | Per-model overrides persisted under `model_overrides.<alias>` and pushed live for the active alias (`app_controller.py:1039-1111`) | `models.inference.get/set` |
| 9 | Storage: path, size, Change, Reset, Open, move/leave/cancel (`shortcuts_view.py:897-1040`, `_storage_mixin.py`) | `StorageCard.svelte`; `models.storage.get/plan/apply/reset/open` |
| 10 | HF token: masked, clear, mirrored to `HF_TOKEN` (`shortcuts_view.py:1047-1140`) | `HfTokenCard.svelte`; `models.hf_token.get/set/reset`; link missing (M13) |
| 11 | First-run: recommended card, download step with progress, hotkey caps, Set up later, Start dictating (`first_run_view.py`) | `views/FirstRun.svelte`; `firstrun.status/complete/defer` |
| 12 | Transcribe: drop zone, Browse, filters, busy/done/error status, editable transcript, Edited, Copy, Save .txt (`transcribe_view.py`) | `views/Transcribe.svelte`, `lib/transcribe.js`; `files.transcribe/save_text/formats` (formats Verified, 24 extensions) |
| 13 | Preset strip on Transcribe (pin a preset for one file) (`transcribe_view.py`, `app_controller.py:1626`) | `Transcribe.svelte` picker; `presets.set_override` |
| 14 | OS file open (Finder, argv, Windows Open with) (`main_window.py:560-665`) | `main.cjs:65-80`, `fileinbox.cjs`, `preload.cjs` `onFileOpen/ready/pendingFiles`, `installer.nsh` |
| 15 | History: list newest first, search, details, copy, export, clear with count (`history_view.py`) | `views/History.svelte`, `lib/history.js`; `history.list/export/clear` |
| 16 | History export dialog and default name (`history_view.py`) | `dialog.saveFile` + `history.export` |
| 17 | Logs: search, Show network logs, Clear with confirm, level colours, rank, empty state (`logs_view.py`, `log_bridge.py`) | `views/Logs.svelte`, `components/logs/*`; `logs.list` + `log` event ring (`runtime.py:49`) |
| 18 | Post-processing: switch in the language-model card, name, provider (12), server, model, key + Clear, mode, effort, max tokens, timeout, own wording, privacy line (`presets_view.py`) | `views/PostProcessing.svelte`, `components/presets/*`; `presets.update`, `llm.set_enabled`, `presets.privacy` |
| 19 | Preset picker, default, New, Duplicate, Delete, key reset (`presets_view.py`, `app_controller.py:1420-1626`) | `PresetPicker.svelte`; `presets.create/duplicate/delete/activate/reset_key` |
| 20 | Settings: microphone list, test microphone (3 s verdict), mute output (macOS), VAD, auto-paste (`shortcuts_view.py`) | `Settings.svelte`; `devices.list/select/test`, `settings.set` (`capabilities.mute_output` Verified true on this Mac) |
| 21 | Recording mode, Start/Stop/PTT/Cancel, validation, conflicts, Reset hotkeys (`shortcuts_view.py`, `_hotkey_validation.py`, `app_controller.py:1263`) | `HotkeysCard.svelte`, `HotkeyCapture.svelte`; `settings.validate_hotkeys/set_hotkeys/reset_hotkeys`; one rule set `app/hotkey_rules.py` |
| 22 | Text size (5 presets), theme (system/light/dark), language (`shortcuts_view.py:786-870`) | `Settings.svelte` Appearance; `lib/theme.js`, `ui_prefs.py`; `settings.set ui.*` |
| 23 | Permission banners: Accessibility, Microphone (two states), post-event (`shortcuts_view.py:1796-1930`, `_microphone_check.py`) | `PermissionBanner.svelte`; `permissions.status/refresh/request/open_settings` |
| 24 | Version footer and About dialog (`shortcuts_view.py:376`, `main_window.py:711`) | `Settings.svelte` footer, `AboutDialog.svelte` (menu entry and icon: M10) |

### 4.2 Shell, window and platform behaviour

| # | Qt behaviour | Electron evidence |
| --- | --- | --- |
| 25 | Recording capsule: copy per state, dot, delivery titles, never "Pasted", text never shown on failure (`recording_overlay.py`) | `Overlay.svelte`, `components/capsule/copy.js`; `parity-capsule.md` |
| 26 | Capsule: frameless, always on top, click-through, never takes focus (`recording_overlay.py`) | `windows.cjs:378-400` (`focusable: false`, `setIgnoreMouseEvents`, `type: 'panel'` on macOS) |
| 27 | Capsule anchored once per appearance, re-placed on display change, primary fallback (`placement.py`) | `windows.cjs:412-470` (`anchorDisplayId`, `display-removed/added/metrics-changed`) |
| 28 | Capsule floats over full-screen apps, wakes a hidden app without activating (`mac_window.py`) | `windows.cjs:386-405, 445` (`visibleOnFullScreen`, `app.show()` when hidden); full-screen case not exercised (`plan.md`) |
| 29 | Confirmation survives `idle` (`recording_overlay.py`) | `windows.cjs` `DELIVERY_MS`, `delivery` handler in `startEventFeed` |
| 30 | Tray icon: four states, tooltips, Show window and Quit, translated (`tray_icon.py`) | `windows.cjs:336-376`; `strings.cjs` `tip`; Restart engine added |
| 31 | Tray click shows the window on Windows and Linux, macOS opens only the menu (`_tray_mixin.py`) | `windows.cjs:349-352` |
| 32 | Close to tray; quit if no tray; save geometry first (`main_window.py:290`) | `windows.cjs:221-232`, `main.cjs:481` `window-all-closed`; Linux tray host probe `windows.cjs:306` |
| 33 | Window geometry and screen restore; clamp to work area; centre on primary if screen gone (`main_window.py:328-415`) | `geometry.cjs` `computeBounds`, `windows.cjs:150-190`; tests `shell-geometry.test.js` |
| 34 | Single instance, second copy tells the user and exits (`app.py:363,395`) | `main.cjs:58-70` (Electron lock, second launch focuses the first) plus runtime lock `LazyToTextQt` via `app/server/__main__.py:126`, dialog `main.cjs:alreadyRunning` |
| 35 | App menu: About, Settings Cmd+, , Quit Cmd+Q; Window menu with Minimize, Zoom, one entry per screen Ctrl+1..N; Edit menu (cut/copy/paste) (`main_window.py:460-560`) | `main.cjs:385-440` menu template; `App.svelte:41-58` keydown |
| 36 | Dock click restores the window (`app.py` `applicationStateChanged`) | `main.cjs:477` `app.on('activate')` (Dock hiding: M7) |
| 37 | Windows dark title bar to match the palette (`window_chrome.py`) | `main.cjs:615` `nativeTheme.themeSource` from `lib/theme.js:36`; unverified on Windows |
| 38 | Theme follows the OS without restart (`theme.py`) | `lib/theme.js` `watchSystemTheme` |
| 39 | Language switch re-renders everything (`language.py`, `shortcuts_view.py`) | `lib/i18n.js`; menu and tray re-built (`main.cjs:applyLanguage`) |
| 40 | Text scale and high-DPI | `applyTextScale` (root font size 0.85-1.75); Chromium owns DPI |
| 41 | Keyboard: Ctrl/Cmd+1..6, Cmd+, , Cmd+Q, Find on Models and History, Esc clears History search | `App.svelte:41-58`, `Models.svelte:117`, `History.svelte:153` (Logs: M11) |
| 42 | Accessible names, roles, live regions | `role="status"`, `role="meter"` named "Microphone level", `aria-*` throughout; skip link `App.svelte` |
| 43 | Tooltips on metrics, network-log toggle, engine pill | `ModelCard.svelte` `use:tooltip`, `StatusStrip.svelte`, `parity-logs.md` |
| 44 | Reduced motion respected | capsule dot, `Settings.svelte:jump` |
| 45 | Native dialogs: open, save, folder, confirm with default/cancel (`dialogs.py`, `QFileDialog`) | `main.cjs:635-690` handlers; preload `l2t.dialog.*` |
| 46 | Status strip: state, model pill, CPU/RAM and level meter (`topbar.py`, `sidebar.py`, `resource_widget.py`, `vu_meter.py`) | `StatusStrip.svelte`, `LevelMeter.svelte`; `resources.sample`, `level` event |

### 4.3 Runtime behaviours (shared code; Verified where noted)

| # | Behaviour | Electron / runtime evidence |
| --- | --- | --- |
| 47 | Global hotkeys: two keys, toggle, push-to-talk with minimum hold, cancel | `app/hotkey_listener.py` via `app/gui/recording_factory.py` (moved, see section 6); live apply `settings._push_listener` |
| 48 | Audio feedback sounds start/stop/cancel | `app/audio_feedback.py`; `app/assets/sounds/*` shipped by `lazy_to_text_server.spec` datas; switch `audio_feedback.enabled` |
| 49 | Output mute and crash recovery of a left-muted device | `SystemOutputMute.recover_if_left_muted` called in `recording_factory.py:~95` |
| 50 | Silero VAD switch, background load | `models.push_vad` (shared), `audio.vad_enabled` |
| 51 | Preserve clipboard, auto-paste, paste keystroke delay | `clipboard_manager.py`; `clipboard.*` |
| 52 | LLM post-processing with raw-text fallback and user-facing log line | `app/llm/*`, `state_manager`; unchanged |
| 53 | Post-load inference probe, CoreML to CPU fallback | `app/backends/onnx_backend.py`; unchanged |
| 54 | Inference worker subprocess, macOS spawn environment, in-process fallback | `app/server/runtime.py:156-190` (copied decision from `app/gui/app.py`) |
| 55 | Config load, migration, redaction in logs, flush at exit | `ConfigManager`; `Runtime.shutdown` flushes (`runtime.py:198`) |
| 56 | File logging, rotating, owner-only, sensitive records kept out of the file | `bootstrap._install_file_logging`; `_NoSensitive` in `server/__main__.py:26` |
| 57 | HF token and models folder applied before huggingface_hub import | `Runtime.start` (`runtime.py:107-122`) |
| 58 | Autoload of the persisted model, first-run decision from disk | `bootstrap._autoload_persisted_model`, `firstrun.status` (Verified: runtime logged "not cached ... skipping auto-load") |
| 59 | Exit without waiting for a stuck model load or recording thread (`os._exit`) | `app/server/__main__.py:176-190` |
| 60 | History capture, cap, legacy backup, export | `history_manager.py`; `history.*` |
| 61 | Single microphone / device list, stale device handling | `devices.list` (shows "(not connected)") |
| 62 | Resource sampling CPU and RAM | `app/resource_sampler.py` (Qt-free; `resource_monitor.py` is the Qt wrapper) |
| 63 | Version text from metadata with pinned fallback | `app/version.py`; `settings.get.version` |
| 64 | macOS Accessibility and post-event probes; listener restart on grant | `macos_permissions.py`; `permissions.py` restarts listener |
| 65 | Privacy: ORT telemetry off, token redaction | `privacy_env.py`; `backend.cjs` env `ORT_DISABLE_TELEMETRY` |
| 66 | Hardened runtime with microphone entitlement; disable-library-validation only for non-Developer-ID | `desktop/build/entitlements.mac*.plist`, `electron-builder.yml`; tests `test_desktop_packaging.py:112-170` |
| 67 | Patched PortAudio on macOS | `scripts/build_server.py:patch_portaudio`, `vendor/portaudio` (test gap: M5) |
| 68 | Linux PortAudio in the bundle, runtime hook for null streams and no console flashes | `lazy_to_text_server.spec`, `scripts/pyi_runtime_hook.py` |
| 69 | Windows per-user installer, uninstaller, Start Menu, install dir page, close running app | NSIS `oneClick: false`, `perMachine: false`, `allowToChangeInstallationDirectory` (`electron-builder.yml`); startup, shortcuts, languages: M2, section 5 |
| 70 | Windows portable | NSIS `portable` target (self-extracting; documented slower start, `plan.md`) |
| 71 | macOS dmg/zip, usage strings, file associations (Alternate rank) | `electron-builder.yml` mac block; narrower list: M18 |
| 72 | Local self-signed identity for stable TCC grants | `scripts/setup-signing.sh`, `desktop/scripts/dist.mjs:35` `LOCAL_IDENTITY` |
| 73 | Version, tag and release checks | `tests/test_desktop_packaging.py:231-252, 521` |
| 74 | Third-party notices with the installer | `electron-builder.yml` extraResources, `desktop/licenses/` |
| 75 | Screenshots for README and site | `scripts/generate_desktop_screenshots.py`; `docs/screenshots/*` are already Electron windows |
| 76 | CI tests on three OS | `tests.yml` (keeps working after Qt libs are dropped) and `desktop.yml` |
| 77 | GitHub Pages deploy | `pages.yml` (independent of Qt) |
| 78 | Dependabot, house-style check | `.github/dependabot.yml`, `house-style.yml` (independent of Qt) |

---

## 5. Distribution gaps

What the Qt build chain ships that the Electron one does not.

| # | Qt artifact or step | Electron state | Gap |
| --- | --- | --- | --- |
| D1 | Windows CUDA folder bundle `LazyToText-CUDA` (`build-windows-cuda.ps1`, `lazy_to_text.spec:108-133`, `setup-cuda-windows.ps1`) | CPU runtime only (`plan.md` Known Gaps) | M1 (S2) |
| D2 | `lazy-to-text-ui`, `lazy-to-text-ui-cuda`, `lazy-to-text-ui.py` | none; no server console script | M6 (S3) |
| D3 | Inno Setup installer (`installer/lazy_to_text.iss`): English plus Russian wizard, licence page (`LicenseFile=..\LICENSE`), optional Desktop icon, optional run at login, "launch at end" | NSIS: per-user, directory page, uninstaller; no language choice (English wizard), no licence page, no startup task, no optional desktop shortcut choice | M2 (S3); wizard language, licence page and desktop-icon choice are S4 and belong in the same pass (`nsis.language`/`multiLanguageInstaller`, `nsis.license`, `createDesktopShortcut`) |
| D4 | Upgrade replaces the previous install (stable GUID) | new `appId`, new install dir; old Qt install stays | M3 (S3) |
| D5 | Windows portable zip (`LazyToText-<v>-windows-x64.zip`, folder, no extraction) | NSIS `portable` self-extracting exe that unpacks 250 MB on every start | Not a regression of function; start time and disk traffic differ. S4: ship an unpacked zip as well if the portable audience matters |
| D6 | macOS py2app `.app`, alias dev builds, release build, `prune_bundle.py` size cut, `build-macos.sh` | electron-builder dmg and zip, arm64 | Equivalent function. No alias/dev-loop `.app` (dev is `npm run dev`); not a user gap |
| D7 | macOS notarization docs (README "Notarizing the Mac build", CLAUDE.md "What a Developer ID would actually buy") | CI macOS installers are ad hoc signed; local identity via `setup-signing.sh`; no notarization, no Windows signing | Same state as Qt (neither notarized). Keep the docs; rewrite the commands for `dist.mjs` |
| D8 | Patched PortAudio on macOS, hardened runtime with entitlements, `disable-library-validation` only for local identity | carried (build_server, entitlements.mac*.plist) | Tests that hold it are py2app-only: M5 |
| D9 | `config.yaml` / logs / models locations (`platformdirs`) | shared: the runtime resolves the same folders (`L2T_DATA_DIR` for tests) | No gap. Users keep config, history and weights |
| D10 | Single-instance lock `LazyToTextQt` (mutex and `LazyToTextQt.lock`) | the runtime takes the same lock (`app/server/__main__.py:126`) | No gap; name is stale (inventory) |
| D11 | File associations (Info.plist types, UTIs, Inno none) | 11 extensions, Alternate rank | M18 (S4) |
| D12 | Windows `mutex` AppMutex so the installer detects a running app | NSIS checks for the running executable name | Equivalent; verify on Windows |
| D13 | Linux | Qt was never shipped for Linux; Electron adds AppImage and deb | Electron-only improvement |
| D14 | Release workflow: `build` (Windows PyInstaller + Inno) and `publish-qt` create the GitHub release; `desktop-release` waits for it (`release.yml`, `needs: [desktop, publish-qt]`) | Electron jobs attach installers | After deletion `desktop-release` must create the release itself (softprops creates it when missing); `test_the_two_release_jobs_cannot_race_for_the_same_release` and `test_only_the_jobs_that_publish_hold_a_write_token` need rewriting |

---

## 6. Deletion inventory

Reason in one line each. Verify the "used by" claims with the greps in
section 7 before deleting.

### 6.1 Delete outright (exists only for Qt)

Source and assets:

- `app/gui/` (63 tracked files): `app.py` (entry, Dock icon painter, duplicate-instance dialog), `main_window.py`, `theme.py` (palettes, QSS loader, forced colours), `window_chrome.py` (Windows title bar), `mac_window.py`, `dock_presence.py`, `placement.py`, `focus.py`, `smooth_scroll.py`, `refresh_rate.py`, `log_bridge.py` (Qt logging bridge), `controllers/{app_controller,recording_controller,_history_mixin,_storage_mixin,_transcribe_mixin,_tray_mixin}.py`, `views/{first_run,history,logs,models,presets,shortcuts,transcribe}_view.py`, `views/{placeholder,_section_card,_accessibility_check,_hotkey_validation}.py`, `widgets/*` (dialogs, elided_label, empty_state, flow_layout, inference panels, model_card, page_header, recording_overlay, recording_status_widget, resource_widget, sidebar, topbar, tray_icon, vu_meter), `styles/base.qss`, `styles/check.svg`, `styles/fonts/InterVariable.ttf`, `styles/icons/*.svg` (except the one in 6.3).
- `app/language.py` (QTranslator and `bind`, nothing outside `app/gui` imports it; the Qt-free parts already live in `app/ui_prefs.py` and `app/translation_mark.py`).
- `app/resource_monitor.py` (QTimer wrapper; `app/resource_sampler.py` is the Qt-free part and stays).
- `app/i18n/app_ru.qm` (compiled Qt catalogue). `app/i18n/app_ru.ts` only after the migration in section 7 item 1.
- `app/assets/tray_*.png`, `tray_*.ico` (Qt tray and the Inno setup icon), `app/assets/lazy_to_text.icns` (git-ignored, generated for py2app). Narrow `lazy_to_text_server.spec` datas to `assets/sounds/`.
- `setup.py` (py2app), `lazy-to-text-ui.py`, `lazy_to_text.spec`, `.py2app-zlib-built-in-placeholder`, `lazy_to_text.egg-info/` (ignored), `build/` and `dist/Lazy to Text.app` (ignored).
- `installer/lazy_to_text.iss` (Inno Setup; the NSIS installer replaces it. Keep it until M2 and M3 are done so the features can be copied).
- `scripts/`: `build-macos.sh`, `prune_bundle.py`, `build-windows.ps1`, `generate_screenshots.py` (Qt screenshots), `generate_icns.py` (imports `app.gui.app._render_dock_icon_at`), `generate_tray_icons.py` (PySide6). Hold `build-windows-cuda.ps1` and `setup-cuda-windows.ps1` until the CUDA decision (M1), then delete.
- `scripts/entitlements.plist` and `scripts/entitlements-local.plist` (used by `build-macos.sh` and `tests/test_bundle_contents.py`; Electron has its own in `desktop/build/`). Their comments are the best write-up of the two-entitlement rule: move the prose into `desktop/build/entitlements.mac*.plist` first.

Tests:

- `tests/gui/` (45 files, about 20.5k lines), after the Qt-free tests in 6.3 are moved out.
- `tests/test_resource_monitor.py` (tests the Qt wrapper).
- `tests/test_bundle_contents.py`: the py2app and prune tests (lines 124-480, 525-575) and the size-agreement test (576); keep and port 480, 645-720, 803-1090 (section 7 item 5).
- `tests/test_state_manager_overlay_anchor.py`: the last test (`qtbot`, `RecordingOverlay`, line 90) goes; the first two assert the state machine never dips through `idle` and stay.
- In `tests/test_desktop_packaging.py`: `test_the_app_id_is_not_the_qt_applications` becomes moot (keep the id test, drop the Qt framing).
- `tests/conftest.py:7` (`QT_QPA_PLATFORM`); keep the scratch-HOME fixture.

Config and dependencies:

- `pyproject.toml`: dependency `pyside6>=6.11.0`; dev group `pytest-qt`, `py2app`; `[project.scripts] lazy-to-text-ui` and `lazy-to-text-ui-cuda`; `[tool.setuptools.package-data] "gui/styles/*.qss"`; `[tool.pytest.ini_options] qt_api = "pyside6"`; the description text "Windows + macOS". Keep `pyinstaller` (Windows dev marker; CI uses `--with`), `cmake`, `scipy`, `pyobjc-framework-avfoundation`. Regenerate `uv.lock` (drops pyside6, shiboken6, pyside6-addons/essentials, py2app, macholib, altgraph, modulegraph, pytest-qt).
- `DEFAULT_CONFIG["window"]` and `["system_tray"]` (`config_manager.py:228, 309`): no interface reads them. `ui.palette` comment says Qt does not read it.

CI:

- `release.yml`: jobs `build` and `publish-qt`, the header comment, the `needs: [desktop, publish-qt]` ordering, the "Build is heavy (~5 GB ... torch)" note.
- `tests.yml` and `desktop.yml`: `QT_QPA_PLATFORM`, `QT_LOGGING_RULES`, and the apt packages `libegl1 libgl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libxkbcommon-x11-0` (keep `libportaudio2 xvfb`: pynput and sounddevice still need them).
- `.github/workflows/ci.yml` is a placeholder that echoes "Replace with the test command"; unrelated, but it is dead and could go in the same pass.

Documentation (sections that only make sense with Qt):

- `README.md`: Qt badge (line 15); the paragraph about Qt bloat in the macOS archive (41-50); quick start `uv run lazy-to-text-ui` (71); "Feels like the platform" trackpad note (124); the architecture diagram and layer table naming Qt (168-260, 229, 254); tech stack bullet PySide6 (304); "Building a release" macOS py2app and Windows PyInstaller (565-745); development section using `pytest-qt` and the offscreen platform (811-830). Keep "macOS first-run permissions", "Electron interface", "Where the data lives".
- `docs/architecture.md`: "PySide6 desktop program", "Only `app/gui/` imports Qt", "The icon in the Dock is a runtime policy", boundaries list. `docs/index.html:103` (the "original Qt window" blurb). `docs/STATUS.md` line about `scripts/update_translations.py`.
- `CLAUDE.md` (1,422 lines) and `AGENTS.md` (353): the Qt-only sections: Run/build/test commands, both themes and the Qt colour work (241-480), cocoa checkbox and icon notes, py2app signing and hardened-runtime sections (730-936, partly reusable for `dist.mjs`), App menu (976), version-lie section (keep, retarget), permissions UX (keep), Dialogs (1208), Transcribe view and Delivery confirmation contracts (1240-1316, their lessons are now in `lib/transcribe.js` and `Overlay.svelte`), the History view `KeyError` (1317). The portable PortAudio deadlock section (646-729), backend topology, scipy, model-probe and the VAD sections are runtime facts: keep.
- `DESIGN.md` (1,057 lines): written for Qt/QSS (Qt appears 15 times: icon modes, QSS shadows, cocoa spacing, forced colours via Win32). Rewrite against `@monos/ui` tokens; the Do's and Don'ts and the Page identity and Empty states rules are product-level and carry over. `PRODUCT.md` needs two small edits.
- `specs/001` to `009`: each ends with a "Where it lives" and "Tests" list of `app/gui/*` files, and `007`, `009` (US1, US2, US4, US5, FR-001 to FR-046, FR-090) are Qt requirements. Re-home them under 010 (or mark them superseded); `010/spec.md` Summary ("keeps working"), Assumptions line 225, SC-004 ("the Qt suite is unchanged"), `tasks.md` and `plan.md` need the same edit.
- `THIRD_PARTY_NOTICES.md:68` "The Qt interface's sidebar icons are Heroicons": keep the notice if the microphone glyph in `make_icons.py` stays, reword it.

### 6.2 Look Qt-only but are used (do NOT delete as they stand)

Every import of `app.gui.*` from outside `app/gui` and `tests/gui` (grep in
section 7): exactly these, and nothing else.

| Importer | What it imports | Why it matters |
| --- | --- | --- |
| `app/server/runtime.py:158` | `app.gui.recording_factory.build_recording_stack` | The runtime builds its whole stack with it. The module has no Qt import (only `app.audio_*`, `backends`, `clipboard_manager`, `config_manager`, `hotkey_listener`, `state_manager`, `system_audio`). Move to `app/recording_factory.py`. |
| `tests/test_desktop_packaging.py:209` | `app.gui.recording_factory` in the "runtime imports no Qt" guard list | Update the name. |
| `tests/gui/test_recording_factory.py` | same | Move to `tests/`. |
| `app/server/handlers/permissions.py:36,161,185` | `app.gui.views._microphone_check` (pyobjc AVFoundation wrapper, Qt-free) | Microphone banner and request. Move into `app/macos_permissions.py` or a new `app/mic_permission.py`. |
| `tests/server/test_settings.py:691` | the same, inside the "handlers import without Qt" subprocess test | Update the import. |
| `tests/server/test_settings.py:122` | `app.gui.views._hotkey_validation.validate_hotkey` (the Qt sentence wrapper) | Delete that test; the rules are covered by `tests/test_hotkey_rules.py` and `settings.validate_hotkeys`. |
| `tests/server/test_files.py:73` | `app.gui.views.transcribe_view._AUDIO_EXTS` | Compare with `app/audio_formats.py` directly. |
| `tests/test_llm_pipeline.py:218`, `tests/gui/test_file_logging.py` | `app.gui.app._NoSensitiveToFile` (re-export, `app/gui/app.py:35-36`) | The class lives in `app/bootstrap.py:346`; import it from there. Comment at `app/state_manager.py:658` names the old path. |
| `tests/test_state_manager_overlay_anchor.py:97` | `RecordingOverlay` (Qt) | See 6.1: split the file. |
| `scripts/generate_icns.py:69` | `app.gui.app._render_dock_icon_at` | Dev tool; the icons are already generated and committed in `desktop/build/`. Delete the script or rewrite. |
| `scripts/make_icons.py` (PySide6, `QSvgRenderer`) and `scripts/generate_tray_icons.py` | PySide6 and `app/gui/styles/icons/microphone-solid.svg` | `make_icons.py` is how the Electron icons and tray images are drawn (`windows.cjs` comment). Move the SVG to `desktop/assets/` or `docs/`, and either rewrite the script without Qt (Pillow or `sharp`) or retire it and keep the generated PNG/ICNS/ICO. |
| `lazy-to-text-ui.py`, `pyproject.toml:85-86`, `installer/lazy_to_text.iss:24` (comment/mutex name), `setup.py:119` | the Qt entry | Go with the Qt chain. |
| `app/cuda_bootstrap.py` | docstring and `ensure_cuda` claim Qt (`:194`); called by `app/server/__main__.py:118` | Keep the module for M1; fix the docstrings and the pip hint. |

Other modules that look Qt-adjacent and stay:

- `app/translation_mark.py` (`mark`, imported by `app/hotkey_rules.py:20` and `app/model_mapping.py:29`): 45 `mark()` calls outside `app/gui` define the English source for the strings the renderer translates (hotkey refusals, model descriptions). Keep.
- `app/ui_prefs.py` (theme, palette, language, text scale rules): imported by `app/server/handlers/settings.py:24`. Keep. `app/language.py` re-exports from it, which is the only reason `language.py` seemed shared.
- `app/hotkey_rules.py`, `app/mic_test.py`, `app/audio_formats.py`, `app/inference_settings.py`: shared Qt-free rules extracted for 010; keep.
- `app/instance_manager.py`: used by `app/server/__main__.py:126`. The lock name `LazyToTextQt` (also `tests/test_instance_manager.py`, the Inno `AppMutex`, the cache file `LazyToTextQt.lock`, CLAUDE.md) is a Qt-era name; rename only together with M3.
- `app/state_manager.py`: its `system_tray` collaborator (`OptionalComponent`, `update_state` calls at lines 258, 359, 374, 667, 781-845) is Qt-era plumbing; the runtime passes `None` and the Electron tray follows SSE events. Safe to remove later; not a blocker.
- `app/bootstrap.py`, `app/resource_sampler.py`, `app/macos_permissions.py`, `app/macos_hotkeys.py`, `app/system_audio.py`, `app/clipboard_manager.py`, `app/audio_feedback.py`: runtime code.
- `app/assets/sounds/*.wav`: runtime (cues), shipped by `lazy_to_text_server.spec`.
- `scripts/build_server.py`, `build_patched_portaudio.py`, `stress_portaudio_stop.py`, `pyi_runtime_hook.py`, `setup-signing.sh` (identity name pinned in `desktop/scripts/dist.mjs:35`), `export_translations.py`, `generate_desktop_screenshots.py`, `linux_container_*`: Electron chain; keep.
- `vendor/portaudio/`: patch for the runtime bundle; keep.
- `desktop/renderer/src/Popup.svelte`, `popup.js`, `popup.html`, `guard.cjs:20` `popup.html` entry, `vite.config.js` `popup` input: dead stub; remove.

---

## 7. Must-migrate-first list

Ordered; each blocks deleting `app/gui`.

1. **The Russian catalogue.** `desktop/renderer/src/i18n/ru.json` (420 entries) is
   generated by `scripts/export_translations.py` from `app/i18n/app_ru.ts`
   (442 messages, 419 unique sources, no source has two different translations,
   so flattening loses nothing; no entry is unfinished). The renderer's own
   additions are 345 entries in `ru.<area>.json` (merged over it in
   `lib/i18n.js`). About 321 of the 420 sources appear literally in
   renderer or runtime source; about 99 do not (Qt-only strings, and templates
   the runtime fills in, such as `%1 is reserved by the operating system...`).
   Before deleting: (a) decide the source of truth: either keep `app_ru.ts` as
   a plain XML catalogue (the export only uses `ElementTree`; no Qt needed) or
   make `ru.json` the authored file and delete the `.ts`; (b) rewrite
   `scripts/update_translations.py`, which today scans `app/gui` for `bind` and
   `tr_text` calls and runs `pyside6-lrelease` (line 151), to scan `$t('...')`
   in the renderer plus `mark()` in Python and to list what has no Russian;
   (c) prune the Qt-only entries only after checking each against
   `translateRuntime` templates (runtime messages are matched by template, so a
   source that never appears literally may still be live); (d) delete the
   `.qm` and `app/language.py`. The runtime also returns English sentences
   built in Python (`app/server/handlers/*`, `hotkey_rules.Issue`), which is why
   `translation_mark.mark` stays.
2. **Move `app/gui/recording_factory.py` to `app/recording_factory.py`** and
   update `app/server/runtime.py:158`, `tests/test_desktop_packaging.py:209`
   and the moved test. The runtime cannot start without it.
3. **Move `app/gui/views/_microphone_check.py`** (and, for symmetry,
   `_accessibility_check.py`, which only wraps `app/macos_permissions.py`) into
   `app/`, and update `app/server/handlers/permissions.py:36,161,185`,
   `tests/server/test_settings.py:691`.
4. **Re-home the Qt-free tests that live in `tests/gui/`.** They cover
   `app/bootstrap.py`, `app/recording_factory.py` and the log filters, which the
   runtime runs:
   - `test_file_logging.py` (10 tests: configured file name, rotation caps,
     level, sensitive records kept out of the file),
   - `test_app_entry.py` autoload group (lines 185-288), `_apply_storage_path`
     (297-326), `_preload_onnx_asr_*` (344-477), `_install_file_logging`
     (553-612), `test_main_spawns_subprocess_backend_before...` (438, rewrite
     against `app/server/__main__.py`), `test_a_refused_second_instance_says...`
     (614, now the runtime's `already_running` line),
   - `test_first_run.py` bootstrap tests (line 131 onward: `_autoload_persisted_model`,
     `_should_show_first_run`),
   - `test_recording_factory.py`,
   - `test_app_exit_stuck_recorder.py` (7 tests) against `Runtime.stuck()`,
   - `test_language.py` ui_prefs cases (already duplicated in `tests/server/test_settings.py:134-140`; check),
   - anything in `test_presets_controller.py` that pins `_sync_flat_keys_to_active`
     semantics: `tests/server/test_presets.py` should hold the same cases.
5. **Port the signing and bundle tests to the Electron artifact**
   (`tests/test_bundle_contents.py:480, 645-720, 803-1090`): patched PortAudio
   marker, "build refuses ad hoc when an identity was chosen" (now `dist.mjs`),
   `setup-signing.sh` keychain-password test (the script stays),
   Developer-ID versus local entitlements (duplicated by
   `test_desktop_packaging.py:112-170`; keep one copy), every Mach-O signed, the
   worker runs. This closes M5.
6. **Icons.** Move `app/gui/styles/icons/microphone-solid.svg` and rewrite or
   retire `scripts/make_icons.py` and `scripts/generate_tray_icons.py` (both
   import PySide6). The generated PNG/ICNS/ICO in `desktop/build` and
   `desktop/assets` are committed, so nothing breaks at build time; only the
   ability to regenerate them does.
7. **Version test.** `tests/test_version.py:48-83` reads `setup.py`
   (`CFBundleVersion`, `CFBundleShortVersionString`, `setup(version=)`); with
   `setup.py` gone it must compare `pyproject.toml`, `app/version.py`
   `_FALLBACK` and `desktop/package.json`. In the frozen runtime the
   `lazy-to-text` distribution metadata is not bundled (only `onnx-asr` and
   `imageio-ffmpeg`, `lazy_to_text_server.spec`), so the About text and footer
   show `_FALLBACK`: it must be bumped with every release, or the spec should
   `copy_metadata("lazy-to-text")`.
8. **Release workflow.** `release.yml`: `desktop-release` must create the release
   (drop `needs: publish-qt`, keep `generate_release_notes`); update
   `tests/test_desktop_packaging.py:493-520`; remove the Qt apt packages and
   env from `tests.yml` and `desktop.yml`.
9. **Dependencies.** Remove `pyside6`, `pytest-qt`, `py2app`, the Qt scripts
   and package-data from `pyproject.toml`, drop `qt_api` from pytest config,
   regenerate `uv.lock` with `uv lock`, run the full suite and the three
   desktop legs (the runtime spec already excludes PySide6, so the bundle does
   not change; `tests/test_desktop_packaging.py:188` should keep guarding that
   Qt does not creep back).
10. **Decisions the team has to make before the delete lands** (each is a
    MISSING item): CUDA on Windows (M1), run at login (M2), Qt-to-Electron
    upgrade path and the lock name (M3), forced colours (M4), the PortAudio
    and worker tests (M5), the Python-only launch and README quick start (M6),
    screen order and default screen (M12).
11. **Docs and specs** (6.1): README, CLAUDE.md, AGENTS.md, DESIGN.md,
    `docs/architecture.md`, `docs/index.html:103`, specs 001-009 and the 010
    statements that Qt "stays". Do this in the same change, because
    `tests/test_desktop_packaging.py` and the house-style check read some of
    these files.

Verification to run after the move (not done in this audit, which changed no
code): `uv sync --frozen`, `uv run --frozen python -m pytest tests -q -n auto
-m "not timing"`, the runtime import guard in `tests/test_desktop_packaging.py`,
`cd desktop && npm test`, and a start of each of the three `desktop.yml` legs'
smoke tests.

### Appendix: greps that back section 6.2

```
rg -n "app\.gui|from app import gui" -g '!app/gui/**' -g '!tests/gui/**' -g '!node_modules' -g '!dist' -g '!build' -g '!.claude' -g '!*.lock' -g '!specs/**' -g '!docs/**'
rg -l "PySide6|shiboken|qtbot" -g '*.py' -g '!app/gui/**' -g '!tests/gui/**'
rg -n "get_setting|update_user_setting|get_section" app/gui
```
