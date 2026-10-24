# Lazy to Text: state of the app

Last updated with the removal of the Qt interface (spec 011), after release
0.1.24. This is a working document for the team: what is done, what was
verified and how, and what is still open. User-facing docs are README.md and
docs/index.html.

## Done

- **One interface.** The Qt interface and the CUDA build are removed. The
  Electron interface (spec 010) is the only front end over the Python engine
  and its headless runtime (`app/server`).
- **Interface languages.** Russian and English, switched live in Settings. The
  Russian catalogue is `desktop/renderer/src/i18n/*.json`, the only source;
  `scripts/check_translations.py` fails when a string the renderer or the
  runtime marks has no Russian entry.
- **Post-processing, models, history, transcribe, logs.** Behaviour specs
  001 to 009 still describe the engine.
- **Packaging.** `scripts/build_server.py` builds the runtime, `desktop`
  wraps it with electron-builder for Windows, macOS and Linux. One release job
  creates the GitHub release for a `v*` tag, with the changelog section as
  its body.

## Verified

- Test suite, offscreen no longer needed: `uv run --frozen python -m pytest
  tests/ -n auto -m "not timing"`, plus the timing tests serially.
- `import app.server.runtime` works with PySide6 absent.
- The runtime builds and answers one snapshot in its own smoke run
  (`scripts/build_server.py`).

## Not verified

- A full dictation on a live Mac: hotkey, recording, transcription, paste.
- Model download and cancel with real downloads.
- Keyboard-only use and VoiceOver.
- The Windows and Linux installers beyond what `desktop.yml` starts on CI.
- Upgrade of a machine that has the classic Qt install: the application id is
  the same, settings, history and models are shared, and the Windows installer
  offers to remove an Inno-installed classic build. Not run end to end.

## Open decisions

- **Notarisation and Windows signing.** CI builds are ad hoc signed on macOS
  and unsigned on Windows; a Developer ID is a release decision.
- **The lock name.** The single-instance lock is still `LazyToTextQt`, kept so
  a classic copy and the new one exclude each other during the transition.
- **GPU inference.** Dropped with the CUDA build. The Windows status bar still
  reads GPU and VRAM through NVML, as monitoring only.
- **Hotkeys on macOS.** Defaults are ctrl+F8/F9/F10 in code; a user config may
  still hold ctrl+F2/F3/F6 from earlier builds.

## Known limits

- The model list is long: 16 cards. Sorting and filters help.
- Automatic update checks do not exist; users learn about a release by hand.
