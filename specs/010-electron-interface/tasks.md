# Tasks: Electron Interface on @monos/ui

Format: `[ID] [P?] [Story] Description`. `[P]` marks a task that can run in
parallel with others (different files). Status: `[x]` done, `[ ]` open.

## Phase 1: Foundation

- [x] T001 Move the Qt-free startup steps to `app/bootstrap.py`; update the tests that patched them
- [x] T002 Split `ResourceSampler` out of the Qt `ResourceMonitor`
- [x] T003 Runtime: registry, event bus, channel with token and Host check (`app/server/`)
- [x] T004 Core handlers: snapshot, recording, resources, logs, quit
- [x] T005 `desktop/` scaffold: Vite + Svelte + Tailwind + `@monos/ui`, three entry pages
- [x] T006 Electron main: runtime launcher, windows, tray, capsule rules, native dialogs, preload bridge
- [x] T007 Renderer core: rpc client, stores, i18n (ru from the Qt catalogue), theme
- [x] T008 Shell: sidebar navigation, status area, toasts
- [x] T009 Runtime tests (`tests/server/`): registry, bus, channel auth, core handlers
- [x] T010 Renderer tests (`desktop/tests/`): rpc client, stores, no-literal-colour contract

## Phase 2: Transcribe and History (spec 003, 004)  [P]

- [x] T020 [US3] Handlers `files.*` and `history.*` and their contract file
- [x] T021 [US3] Transcribe view: drop anywhere, open, progress, editable transcript, Edited, Copy, OS file-open
- [x] T022 [US4] History view: list, search, copy, delete with undo, export, clear
- [x] T023 Tests for both (runtime and renderer)

## Phase 3: Models and First run (spec 002)  [P]

- [x] T030 [US2] Handlers `models.*` (catalogue, cache state, select, download, delete, cancel, inference settings, storage, HF token)
- [x] T031 [US2] Models view: cards, filter and sort, per-model inference settings, loading and cancel
- [x] T032 [US2] First-run view and the gate in the shell
- [x] T033 Tests

## Phase 4: Settings and permissions (spec 006)  [P]

- [x] T040 [US6] Handlers `settings.*`, `devices.*`, `permissions.*` (hotkeys with validation applied live, recording mode, mic device and test, mute output, VAD, auto-paste, language, theme, text scale)
- [x] T041 [US6] Settings view with hotkey capture, grouped sections, macOS permission banners
- [x] T042 Tests

## Phase 5: Post-processing, Logs, capsule, status (spec 005, 007, 008)  [P]

- [x] T050 [US5] Handlers `presets.*` and `llm.*` (switch, presets CRUD, override, key reset)
- [x] T051 [US5] Post-processing view with the speed controls and the switch in the settings card
- [x] T052 [US6] Logs view
- [x] T053 [US1] Capsule renderer: recording, processing, delivery states; levels
- [x] T054 Status strip: state, model, engine, resources, loading progress with cancel
- [x] T055 Tests

## Phase 6: Packaging and CI (spec 009)

- [x] T060 PyInstaller spec for the runtime (`lazy-to-text-server`) on all three platforms; macOS carries the patched PortAudio
- [x] T061 electron-builder config: Windows (nsis + portable), macOS (dmg/zip, hardened runtime, entitlements, microphone usage text), Linux (AppImage, deb)
- [x] T062 CI: renderer and runtime tests on three OS; build artifacts; release workflow attaches them
- [x] T063 Tests that read the packaging config and pin the entitlements and the runtime inclusion
- [x] T064 Update README, CLAUDE.md, AGENTS.md, CHANGELOG

## Phase 7: Verification

- [x] T070 Screen-by-screen parity checklist against specs 001 to 008, recorded here
- [x] T071 Run every screen in all themes; screenshots reviewed (each slice reviewed its own screens in dark, light and Russian; the assembled shell was walked through once more)
- [x] T072 End-to-end on macOS: built and launched the packaged app; against the real runtime a real model (vosk-ru-small) was downloaded with progress, loaded on CPU and transcribed a synthesised Russian phrase. Dictation by hotkey and the microphone were not exercised
- [x] T073 Update `specs/README.md` status and the Known Gaps section of the plan
