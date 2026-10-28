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
- Windows packaged runtime builds, answers `app.snapshot`, and passes an RPC
  that exercises startup of the spawned inference worker (`scripts/build_server.py`).
- Electron tests pass on Windows (`npm test`, 414 tests), and the renderer and
  Windows NSIS installer build successfully. The unpacked packaged app also
  starts, reaches the first-run screen and exits cleanly in the Windows smoke.
- The Windows Python suite ran 1,230 tests successfully. Symlink-dependent
  tests could not run to completion because this account lacks the Windows
  `Create symbolic links` privilege; this is an environment limitation, not a
  passing result for those tests.

## Not verified

- A full dictation on a live Mac: hotkey, recording, transcription, paste.
- Model download and cancel with real downloads.
- Keyboard-only use and VoiceOver.
- The Windows and Linux installers beyond what `desktop.yml` starts on CI.
- Upgrade of a machine that has the classic Qt install: the application id is
  the same (macOS grants carry over only for a build signed with the same
  identity; CI builds are ad hoc), settings, history and models are shared, and the Windows installer
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
