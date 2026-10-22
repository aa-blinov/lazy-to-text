# AGENTS.md — agent context for `lazy-to-text`

A local-first speech-to-text app with a PySide6 interface, packaged for
Windows and macOS. It records from the microphone on a global hotkey,
transcribes on the machine through one ONNX inference path, and pastes the
text into the window that had the focus.

This file is the re-entry surface: what to run, where things live, and the
traps that cost a rebuild to learn.

## Run / build / test

```bash
uv sync                          # bootstrap the venv from uv.lock
uv run lazy-to-text-ui           # launch the app in dev mode
uv run lazy-to-text-ui-cuda      # launch with the GPU bootstrap (Windows + NVIDIA)

uv run --frozen python -m pytest tests/ -q -n auto -m "not timing"
uv run --frozen python -m pytest tests/ -q -m timing

./scripts/build-macos.sh             # py2app alias .app, 5 to 10 s (Mac)
./scripts/build-macos.sh --release   # py2app full .app, 5 to 10 min (Mac)
.\scripts\build-windows.ps1          # PyInstaller folder bundle, CPU only, dist\LazyToText\ (~400 MB)
.\scripts\build-windows-cuda.ps1     # PyInstaller folder bundle, GPU and CUDA, dist\LazyToText-CUDA\ (~3.0 GB)
.\scripts\build-windows.ps1 -OneFile # PyInstaller single .exe, CPU only
```

The suite is 1496 passed and 10 skipped on the main run at release 0.1.19,
plus 8 timing tests that run serially (`docs/STATUS.md`). The skipped tests
are the ones that need a built bundle in `dist/`, a macOS codesign identity,
or a release tag to compare the version against.

CI runs `tests/` on ubuntu, macOS and Windows runners with
`QT_QPA_PLATFORM=offscreen` in the environment. On Linux the run is wrapped in
`xvfb-run -a`, because `pynput` opens an X connection at import time and the
hotkey listener imports it there. The Windows leg of the matrix is the point:
a third of the platform-conditional code has never executed anywhere but one
developer's Mac.

Some of the pixel-based and config-file tests are sensitive to parallel runs
and fail occasionally under `-n auto`. They pass on a rerun, and they are not
a regression.

**The macOS bundle ships a patched PortAudio, and that is not optional.**
The `sounddevice` wheel's own dylib deadlocks when a stream is stopped
([PortAudio/portaudio#1174](https://github.com/PortAudio/portaudio/issues/1174)):
the microphone stays held for the rest of the session, and the app
cannot quit either — `Pa_Terminate` deadlocks on the same lock, so the
process lingers holding the single-instance lock and every later launch
is refused. The patched library is built from `vendor/portaudio/` by
`scripts/build_patched_portaudio.py`, which `build-macos.sh` runs before
the signing step. `scripts/stress_portaudio_stop.py` is the canary: it
deadlocks at cycle ~709 against the wheel's dylib and runs thousands of
cycles clean against the patched one. The long version is in
CLAUDE.md.

## Where things live

| Path | What it holds |
| --- | --- |
| `app/gui/app.py` | The entry point. `main()` and `main_cuda()`, the early backend spawn, the Dock icon. |
| `app/gui/main_window.py` | The sidebar and the stacked views, the shortcuts, the window chrome. |
| `app/gui/controllers/app_controller.py` | The orchestrator: model loading, the recording loop, the cancel path. 1868 lines. |
| `app/gui/controllers/recording_controller.py` | A `QObject` wrapper over `StateManager`. |
| `app/gui/controllers/_*_mixin.py` | Storage, Transcribe, Tray and History, one mixin each. |
| `app/gui/views/` | One widget per sidebar tab: Models, Transcribe, History, Logs, Post-processing, Settings. |
| `app/gui/widgets/` | The building blocks: model cards, sidebar, top bar, level meter, recording capsule, dialogs. |
| `app/gui/styles/base.qss` | The stylesheet. The fifteen colour tokens are substituted in at load time. |
| `app/backends/base.py` | The `TranscriptionBackend` Protocol. |
| `app/backends/onnx_backend.py` | `OnnxAsrBackend`: the inference, the provider list, the chunking. |
| `app/backends/registry_backend.py` | `RegistryBackend`: alias to canonical id, family and load id. |
| `app/backends/subprocess_backend.py` | The same backend in a spawned worker process. |
| `app/state_manager.py` | The domain state machine: recording, processing, model loading. |
| `app/audio_recorder.py` | Capture through `sounddevice`, resampled to 16 kHz. |
| `app/clipboard_manager.py` | Copying the text and delivering the paste keystroke. |
| `app/config_manager.py` | Reading and writing `config.yaml`, and the defaults. |
| `app/history_manager.py` | The history file and the plain-text export. |
| `app/hotkey_listener.py` | The binding: `global-hotkeys` on Windows, a native AppKit monitor on macOS, `pynput` on Linux. |
| `app/macos_hotkeys.py` | The macOS event monitor and the push-to-talk spec. |
| `app/instance_manager.py` | The single-instance lock: a named mutex on Windows, `filelock` elsewhere. |
| `app/model_mapping.py` | The registry of supported models, and the one copy of the measurement. |
| `app/inference_settings.py` | The per-model settings dataclasses. |
| `app/llm/` | The optional post-processing client, the modes, the providers and the presets. |
| `app/resource_monitor.py` | The CPU, RAM, GPU and VRAM sampler. |
| `app/utils.py` | Cache and path helpers. |
| `scripts/` | The build wrappers, the icon and screenshot generators, the translation updater. |
| `tests/` | 71 test files. `tests/gui/` for widgets, `tests/backends/` for dispatch, `tests/utils/` for `app/utils.py`. |

The data paths differ between a source checkout and a frozen bundle.
`platformdirs.user_{config,log,cache}_dir("LazyToText", appauthor=False)` is
the single source of truth, gated by `app/utils.py:_is_frozen()` and
`app/config_manager.py:_resolve_base_dir()`.

| Data | Dev (`uv run`) | macOS `.app` (frozen) | Windows portable (frozen) |
| --- | --- | --- | --- |
| `config.yaml` | `<project>/config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` and history | `<project>/logs/` | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights (HF hub) | `<project>/models/hub/` | `~/Library/Caches/LazyToText/models/hub/` | `%LOCALAPPDATA%\LazyToText\Cache\models\hub\` |
| Single-instance lock | filelock under cache | `~/Library/Caches/LazyToText/LazyToTextQt.lock` | named mutex |

There are two frozen targets: the py2app `.app` on macOS and the
PyInstaller folder bundle on Windows.

## Traps

- **The macOS hotkey defaults are not the Windows ones.** macOS ships
  `ctrl+f8` / `ctrl+f9` / `ctrl+f10`; Windows and Linux ship `ctrl+f2` /
  `ctrl+f3` / `ctrl+f6`. macOS reserves `Ctrl+F1` through `Ctrl+F7` for
  system keyboard navigation (focus, menu bar, Dock, window, toolbar) and
  captures those keys before `pynput` sees them. Bind a low F-key on macOS
  and the app receives nothing at all, with no error anywhere.
- **The inference runs in a spawned worker process.** `main()` starts a
  `SubprocessBackend` and waits up to 10 s for the worker to answer. Only if
  the worker fails to come up does it fall back to the in-process
  `RegistryBackend`, so a dictation app with no engine never ships. The
  reason for the worker is the GIL: ONNX Runtime's pybind11 bindings do not
  release it during session creation, which starves every Python slot for
  about 0.3 s, against roughly 8 ms for ordinary thread contention.
- **`subprocess_backend.py` uses `multiprocessing.get_context("spawn")`**,
  not the bare `multiprocessing.Pipe()` and `Process()`. The fixture in
  `tests/backends/test_subprocess_backend.py` patches `get_context` to return
  a fake context, so patching the bare module attributes alone does not
  intercept the calls.
- **The measurement lives in `app/model_mapping.py`, and the test enforces
  it.** It used to live in `tests/test_model_mapping.py`, so that every
  public surface quoting the figures was held to one copy. That arrangement
  made the app unable to reach its own numbers: the cards carried WER and RTF
  as prose inside the description, while size and VRAM got a laid-out line.
  The registry owns the number now; the test still asserts that each surface
  quotes it.
- **`prefer_cpu_provider` on a card is a measured preference, not a
  workaround.** For GigaAM v3 on an M4 Pro, CoreML takes 1304 of 1608 nodes
  and is still slower than the CPU: 147 ms against 124 ms for 11.4 s of
  Russian. Clear the flag and the card gets slower. The same flag keeps the
  CoreML session from dying after about 15 s on an unbounded dimension.
- **The CoreML provider options are pinned on purpose.** ONNX Runtime gets
  `("CoreMLExecutionProvider", {"ModelFormat": "MLProgram",
  "MLComputeUnits": "ALL", "RequireStaticInputShapes": "0",
  "EnableOnSubgraphs": "0"})` on macOS, and every option in that tuple is
  pinned so a future ONNX Runtime release cannot change the behaviour
  silently. `MLComputeUnits=ALL` lets CoreML route the operators between the
  Neural Engine, the GPU and the CPU one by one.
  `_detect_active_provider` probes the live session and falls back to the CPU
  on an accelerator failure, and it unwraps model adapters (GigaAM's
  `TextResultsAsrAdapter`, for one) to find the inner session.
- **`onnx-asr` matches its registry against the lowercase identifier.**
  `t-tech/T-one` has to be loaded as `t-tech/t-one`, while the canonical
  case is kept for the cache directory and the URL.
- **The source language rides on the card, not on the family label.** The
  backend used to gate the language keyword on `family == "whisper"`, so
  Canary, an AED model, never saw a language and translated the Russian
  instead of transcribing it: 131.0% WER. `auto_language` on the card fixes
  it, and the language now reaches only the cards that declare one.
- **`whisper.compute_type` in `config.yaml` is written by the UI.** When a
  model card is chosen, the controller writes that card's `compute_type`
  into the config. Edit it by hand and the next card selection overwrites
  it.
- **Credentials in the config are scrubbed from the log by two mechanisms.**
  `_REDACTED_SETTINGS` covers a credential that sits directly in its section,
  and `_scrub_secrets` covers a credential nested in a new structure. A
  Hugging Face token was copied into `app.log` in both directions before the
  scrubber existed, because `update_user_setting` logs the old and the new
  value of everything it writes.
- **The history is bounded by entry count alone.** The old
  `auto_cleanup_days` key was removed, because nothing in `app/` read it and
  there was no control for it in the UI. A setting that promises to erase
  dictations without doing it is worse than no setting.
- **The version lives in six places**, and nothing in the build fails when
  they disagree.

  | Place | What it drives |
  | --- | --- |
  | `pyproject.toml` `[project] version` | the wheel, and the canonical value every other place is compared to |
  | `setup.py` `CFBundleVersion` | what Finder shows |
  | `setup.py` `CFBundleShortVersionString` | what the macOS privacy pane shows |
  | `setup.py` `version=` in `setup()` | the py2app bundle metadata |
  | `app/version.py` `_FALLBACK` | what the UI reports when the distribution metadata is unreadable |
  | `README.md` notarization examples | illustrative only |

  The order is fixed: bump all six, commit, tag, `uv sync --frozen`, build,
  verify, then push the tag. `tests/test_version.py` requires the newest
  `v*` tag to match `pyproject.toml`.
- **`uv sync --frozen`, never a bare `uv sync`.** A bare `uv sync` re-resolves
  and rewrites `uv.lock`, which is a silent rebuild of the dependency set
  underneath a green run. It also fails on a missing lockfile only when the
  flag was left off. Step 4 of the release order is not housekeeping: after a
  version bump the venv still holds the old `dist-info`, so
  `importlib.metadata` answers with the previous version and
  `test_the_runtime_reports_the_version_the_tree_declares` fails until the
  venv is re-synced.
- **The macOS artefact is a manual step.** `release.yml` builds Windows only
  (`runs-on: windows-latest`, no `macos` in the file). The `.app` is built
  locally, zipped and uploaded by hand:

  ```bash
  ditto -c -k --keepParent "dist/Lazy to Text.app" "dist/Lazy-To-Text-<v>-macos-arm64.zip"
  gh release upload v0.1.5 "dist/Lazy-To-Text-<v>-macos-arm64.zip"
  ```

  Verify the archive after zipping, not just the bundle: `ditto` round-trips
  symlinks and the execute bit, and a `.pyc` removed from under an existing
  signature turns the seal invalid with nothing saying so.
- **The download sizes in `README.md` and `docs/index.html` go stale every
  release, and nothing catches it.** Both quote the byte count of the
  attached file, so they are only true for the release they were written for.
  After v0.1.4 the README still claimed 159,349,810 B while the actual
  v0.1.5 asset is 155,353,854 B.
  `test_the_documented_download_size_agrees_across_surfaces` checks that the
  two surfaces agree with each other, which cannot catch both being wrong at
  once. Read the sizes from the release and move both surfaces together.
- **Every modal dialog goes through `app/gui/widgets/dialogs.py`.** The three
  helpers are stamped with the live `QApplication.windowIcon()`, which
  replaces the macOS template glyph, and `tests/gui/conftest.py` mocks all
  three at every callsite so headless tests do not hang on `exec()`. A direct
  `QMessageBox.question` shows the system glyph on macOS and bypasses the
  mock.
- **The recording capsule must not take the focus.** `raise_()` on a
  background event steals the caret from the window the user is typing in.
  The capsule uses `WA_ShowWithoutActivating`, and `app/gui/mac_window.py`
  puts the window at `NSStatusWindowLevel` (above a full-screen app, below
  the Notch and the menu bar) with `CanJoinAllSpaces | FullScreenAuxiliary |
  IgnoresCycle | Stationary` and the `NonactivatingPanel` style mask, so it
  stays above a full-screen window in another application without pulling
  that application's Space forward.
- **The Dock icon is a runtime policy, not a plist key.** `setup.py` ships no
  `LSUIElement` on purpose, so the app has a Dock icon and a Cmd-Tab entry
  while the main window is up. `app/gui/dock_presence.py` switches the
  activation policy to accessory while the recording overlay is up, because
  that is what lets the overlay float over another app's full-screen Space.
  The policy is per process, so it cannot be expressed as a plist key that
  varies per window.
- **The App menu is one `QMenuBar` with three actions.**
  `main_window.py:_install_app_menu` builds *About Lazy to Text*, *Settings…*
  (`Ctrl+,`, which Qt turns into `Cmd+,` on macOS) and *Quit Lazy to Text*
  (`Ctrl+Q`). The `AboutRole`, `PreferencesRole` and `QuitRole` menu roles
  make Cocoa promote them into the global App menu under the Apple logo,
  whichever submenu they hang from. On Windows and Linux the same actions
  appear in an ordinary top menu. Quit goes through `request_quit()`, which
  flips `_quitting` so the close-to-tray override does not kick in, and then
  `QApplication.quit()`, because `setQuitOnLastWindowClosed(False)` is set
  while the tray is alive.
- **Accessibility trust on macOS is a hard dependency.** Without
  `AXIsProcessTrusted` there are no global hotkeys and no auto-paste. The
  Settings banner has to open the right System Settings pane, and the
  "granted but needs a restart" case is a separate banner with a relaunch
  button inside the app.
- **Whitelist `Lazy to Text.app` in the Accessibility list, not
  `python3.12`.** The bundle has its own identity, which is what keeps the
  permissions across rebuilds.

## Style / safety rails

- **No emoji**, in a document, in a comment or in a log line. The Logs view
  is monospaced and the dark QSS theme renders them badly.
- **One inference path.** Every model goes through `OnnxAsrBackend` and
  `onnx-asr`. PyTorch, NeMo and CTranslate2 do not come back: the install
  size and the single provider scheme follow from that decision.
- **Comments explain why, never what.** The comments in this codebase are
  unusually good on this point, and they carry the measurements that the
  next person needs. Keep them that way.
- **Do not add a dependency without justifying it against the bundle size
  and the Apple Silicon wheel.** Some machine-learning libraries ship x86_64
  wheels only.
- **A new model is a registry entry, not a new dependency**, and it needs a
  measurement before it ships: `test_every_card_states_its_own_measured_wer`
  fails when an alias is missing from `MEASURED`.

## Where the product truth lives

`PRODUCT.md` holds it. Read it before changing the behaviour of the app, and
write the change there when the behaviour changes. `DESIGN.md` holds the
visual system, and `docs/STATUS.md` holds what was verified and what was
not.
