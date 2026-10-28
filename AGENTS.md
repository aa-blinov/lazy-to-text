# AGENTS.md — agent context for `lazy-to-text`

A local-first speech-to-text app: an Electron window over a headless Python
runtime, for Windows, macOS and Linux. It records from the microphone on a
global hotkey, transcribes on the machine through one ONNX inference path,
and pastes the text into the window that had the focus. The Qt interface and
the CUDA build are gone (spec 011).

This file is the re-entry surface: what to run, where things live, and the
traps that cost a rebuild to learn.

## Run / build / test

```bash
uv sync --frozen                  # bootstrap the venv from uv.lock
uv run lazy-to-text-server        # the Python runtime alone
cd desktop && npm install && npm run dev     # runtime + Vite + Electron

uv run --frozen python -m pytest tests/ -q -n auto -m "not timing"
uv run --frozen python -m pytest tests/ -q -m timing
cd desktop && npm test            # renderer and shell tests

uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py   # the runtime
cd desktop && npm run build && node scripts/dist.mjs --dir                 # unpacked app
cd desktop && npm run dist:mac | dist:win | dist:linux                     # installers
```

CI runs `tests/` on ubuntu, macOS and Windows runners (`tests.yml`); on
Linux the run is wrapped in `xvfb-run -a`, because `pynput` opens an X
connection at import time and the hotkey listener imports it there. The
Windows leg of the matrix is the point: a third of the platform-conditional
code has never executed anywhere but one developer's Mac. `desktop.yml`
builds and starts the packaged app on all three platforms, and `release.yml`
calls it and then publishes: one job creates the GitHub release for a `v*`
tag with the changelog section as the body and attaches every installer.

The skipped tests are platform conditionals (Windows-only, macOS-only), a
codesign identity, or a release tag to compare the version against; never a
missing model. The suite runs in a scratch `HOME` (and `USERPROFILE`,
`LOCALAPPDATA`, `APPDATA` on Windows), so it never touches a user's models.

**The macOS bundle ships a patched PortAudio, and that is not optional.**
The `sounddevice` wheel's own dylib deadlocks when a stream is stopped
([PortAudio/portaudio#1174](https://github.com/PortAudio/portaudio/issues/1174)):
the microphone stays held for the rest of the session, and the app
cannot quit either — `Pa_Terminate` deadlocks on the same lock, so the
process lingers holding the single-instance lock and every later launch
is refused. The patched library is built from `vendor/portaudio/` by
`scripts/build_patched_portaudio.py`, which `scripts/build_server.py` runs
on macOS before the runtime is signed. `scripts/stress_portaudio_stop.py` is the canary: it
deadlocks at cycle ~709 against the wheel's dylib and runs thousands of
cycles clean against the patched one. The long version is in
CLAUDE.md.

**Muting the system output while recording** is a Settings → Microphone
checkbox, macOS only (`app/system_audio.py`). The mute is CoreAudio's own
per-device property — and its scope is `outp`, not `out `: the wrong
constant makes CoreAudio answer `who?` and the mute does nothing, with
nothing in the log. It mutes *every* output device, not just the default
one — the default can be a device that is already muted at the device
level, which would make the feature a no-op exactly where it is needed. A
mute the user had already set is not undone at the end of the recording,
and a run that dies mid-recording is cleaned up on the next launch from a
state file next to `config.yaml`. The long version is in CLAUDE.md.

**The silero VAD** is the second checkbox in Settings → Microphone (*Skip
silence*): the recording is cut into its speech segments before the model
sees it. It is a global switch, not a per-model one — the segmentation does
not depend on the model. It is a second ONNX model, so the first use
downloads about 2 MB into the app's own hub cache; that happens on a
background thread when the checkbox is ticked, never inside a dictation.
The long version is in CLAUDE.md.

## Where things live

| Path | What it holds |
| --- | --- |
| `desktop/electron/` | The shell: windows, tray, capsule, menu, starting the runtime, file open, run at login. |
| `desktop/renderer/` | The Svelte interface on `@monos/ui`, and the Russian catalogue `src/i18n/*.json`. |
| `app/server/` | The runtime: `__main__.py` (entry, `lazy-to-text-server`), `runtime.py`, the loopback channel, `handlers/`. |
| `app/recording_factory.py` | Builds recorder, feedback, clipboard, state manager and hotkey listener from config. |
| `app/bootstrap.py` | Storage path, HF token, onnx-asr pre-import, persisted-model autoload, the log file. |
| `app/backends/base.py` | The `TranscriptionBackend` Protocol and `TranscriptionError`. |
| `app/backends/onnx_backend.py` | `OnnxAsrBackend`: the inference, the provider list, the chunking. |
| `app/backends/registry_backend.py` | `RegistryBackend`: alias to canonical id, family and load id. |
| `app/backends/subprocess_backend.py` | The same backend in a spawned worker process. |
| `app/state_manager.py` | The domain state machine: recording, processing, model loading. |
| `app/audio_recorder.py` | Capture through `sounddevice`, resampled to 16 kHz. |
| `app/clipboard_manager.py` | Copying the text and delivering the paste keystroke. |
| `app/config_manager.py` | Reading and writing `config.yaml`, and the defaults. |
| `app/history_manager.py` | The history file and the plain-text export. |
| `app/hotkey_listener.py`, `macos_hotkeys.py`, `hotkey_rules.py` | The binding per platform and the shared rules. |
| `app/macos_permissions.py`, `app/mic_check.py` | Accessibility and Microphone checks. |
| `app/instance_manager.py` | The single-instance lock: a named mutex on Windows, `filelock` elsewhere. |
| `app/model_mapping.py` | The registry of supported models, and the one copy of the measurement. |
| `app/inference_settings.py` | The per-model settings dataclasses. |
| `app/llm/` | The optional post-processing client, the modes, the providers and the presets. |
| `app/resource_sampler.py` | The CPU and RAM sampler. |
| `app/translation_mark.py` | `mark()`: flags a Python sentence for the translation check. |
| `app/utils.py` | Cache and path helpers. |
| `scripts/` | `build_server.py`, the patched PortAudio build, signing setup, icon and screenshot tools, `check_translations.py`. |
| `tests/` | `tests/server/` for the runtime, `tests/backends/` for dispatch, `tests/utils/` for `app/utils.py`, top-level files for the rest. |

The data paths differ between a source checkout and the packaged runtime.
`platformdirs.user_{config,log,cache}_dir("LazyToText", appauthor=False)` is
the single source of truth, gated by `app/utils.py:_is_frozen()` and
`app/config_manager.py:_resolve_base_dir()`; `L2T_DATA_DIR` overrides them
for a test.

| Data | Dev | macOS (packaged) | Windows (packaged) |
| --- | --- | --- | --- |
| `config.yaml` | `<project>/config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` and history | `<project>/logs/` | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights (HF hub) | `<project>/models/hub/` | `~/Library/Caches/LazyToText/models/hub/` | `%LOCALAPPDATA%\LazyToText\Cache\models\hub\` |
| Single-instance lock | filelock under cache | `~/Library/Caches/LazyToText/LazyToTextQt.lock` | named mutex |

The lock name `LazyToTextQt` is a Qt-era name kept so a still-installed classic
copy and the new app exclude each other.

## Traps

- **The macOS hotkey defaults are not the Windows ones.** macOS ships
  `ctrl+f8` / `ctrl+f9` / `ctrl+f10`; Windows and Linux ship `ctrl+f2` /
  `ctrl+f3` / `ctrl+f6`. macOS reserves `Ctrl+F1` through `Ctrl+F7` for
  system keyboard navigation (focus, menu bar, Dock, window, toolbar) and
  captures those keys before `pynput` sees them. Bind a low F-key on macOS
  and the app receives nothing at all, with no error anywhere.
- **Windows push-to-talk uses its own right-side key monitor.** The
  `global-hotkeys` package checks generic modifiers after reading the exact
  virtual key, so a held right Alt/Ctrl/Shift is rejected as an unrelated
  Alt/Ctrl/Shift. Keep the solo-key PTT path on `GetAsyncKeyState` and leave
  ordinary chords on `global-hotkeys`.
- **The inference runs in a spawned worker process.** The runtime starts a
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
  as prose inside the description, while size got a laid-out line.
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
- **`whisper.compute_type` in `config.yaml` is written by the runtime.** When a
  model card is chosen, the models handler writes that card's `compute_type`
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

- **The version has several places**, and nothing in the build fails when
  they disagree.

  | Place | What it drives |
  | --- | --- |
  | `pyproject.toml` `[project] version` | the runtime wheel, and the canonical value every other place is compared to |
  | `app/version.py` `_FALLBACK` | what the About dialog reports in the packaged runtime, which carries no distribution metadata |
  | `desktop/package.json` and the two `version` fields at the top of `desktop/package-lock.json` | the installers' file names and bundle version |

  The order is fixed: bump all of them, commit, tag, `uv sync --frozen`,
  build, verify, then push the tag. `tests/test_version.py` requires the
  newest `v*` tag to match `pyproject.toml` and holds the other places to the
  same string, and `release.yml` checks the tag again and refuses a tag with
  no `CHANGELOG.md` section.
- **`uv sync --frozen`, never a bare `uv sync`.** A bare `uv sync` re-resolves
  and rewrites `uv.lock`, which is a silent rebuild of the dependency set
  underneath a green run. Changing a dependency means `uv lock` and committing
  the new lock. After a version bump the venv still holds the old `dist-info`,
  so `importlib.metadata` answers with the previous version and
  `test_the_runtime_reports_the_version_the_tree_declares` fails until the venv
  is re-synced.
- **Releases are one job.** A `v*` tag builds the three platforms through
  `desktop.yml`, and the `release` job in `release.yml` creates the release
  with the changelog section as its body. The macOS installers are signed ad
  hoc in CI (no identity), so users are asked for Microphone and
  Accessibility again after an update; a build made with the local identity
  (`scripts/setup-signing.sh`) keeps its grants across rebuilds.
- **Accessibility trust on macOS is a hard dependency.** Without
  `AXIsProcessTrusted` there are no global hotkeys and no auto-paste. The
  Settings banner has to open the right System Settings pane, and the grant
  is picked up live, with no restart.
- **The runtime must stay free of any UI toolkit.**
  `tests/test_desktop_packaging.py` imports it under a guard that refuses
  `PySide6`. `mark()` lives in `app/translation_mark.py` for that reason.
- **Translations have one source**: `desktop/renderer/src/i18n/*.json`.
  `scripts/check_translations.py` (run by `tests/test_translations.py`) fails
  when a renderer `$t` string or a Python `mark()` sentence has no Russian
  entry.

## The Electron interface

`desktop/` (Electron main process, Svelte renderer on `@monos/ui`) talks over
loopback HTTP to the headless runtime in `app/server/`. Spec, plan and wire
contracts are in `specs/010-electron-interface/`.

- `lazy_to_text_server.spec` builds `dist/lazy-to-text-server/`;
  `scripts/build_server.py` wraps it (patched PortAudio on macOS, then a
  smoke run that reads the ready line and one `app.snapshot`).
- `desktop/electron-builder.yml` copies that folder to `resources/backend`.
  `desktop/scripts/dist.mjs` checks the runtime's architecture, signs the
  runtime's Mach-O files and picks the entitlements: `build/entitlements.mac*.plist`
  for a Developer ID, the `.local` pair (adds `disable-library-validation`)
  for the self-signed identity or ad hoc. A certificate Apple did not issue
  has no Team ID, and under the hardened runtime a library with a different
  Team ID than the process will not load: the runtime dies on its first
  instruction while the window keeps opening.
- The app id is `io.github.aa-blinov.lazytotext` (0.2.1; 0.2.0 still used the
  Qt app's `ai.eora.lazytotext`). A build signed with the same self-signed
  identity keeps the macOS grants (the CI build is ad hoc and does not). The
  runtime is shared with a classic copy, so they share one `config.yaml` and
  one single-instance lock.
- `app/translation_mark.py` exists so the runtime can mark sentences without a
  translator.

## Style / safety rails

- **No emoji**, in a document, in a comment or in a log line. The Logs view
  is monospaced and they render badly.
- **One inference path.** Every model goes through `OnnxAsrBackend` and
  `onnx-asr`. PyTorch, NeMo and CTranslate2 do not come back: the install
  size and the single provider scheme follow from that decision. There is no
  GPU build; CoreML on Apple silicon and the CPU elsewhere. The status strip
  reports CPU/RAM usage only; model cards do not estimate VRAM.
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

## Spec-driven development (Spec Kit)

Features are driven from `specs/`, with [Spec Kit](https://github.com/github/spec-kit).
`.specify/memory/constitution.md` holds the principles a change is checked
against, `specs/00x-*` describe what the application already does (baseline,
status `Implemented (baseline)`), and `specs/010-electron-interface/` is the
first feature run through the whole flow. The agent skills live in
`.claude/skills/speckit-*`.

```text
/speckit-specify  -> specs/NNN-name/spec.md     what and why, no how
/speckit-clarify  -> resolves [NEEDS CLARIFICATION] markers
/speckit-plan     -> plan.md, contracts/        how, with the constitution check
/speckit-tasks    -> tasks.md                   ordered, parallel-marked tasks
/speckit-implement
```

A change to behaviour a baseline spec describes changes that spec in the same
pull request. `specs/README.md` is the index.

