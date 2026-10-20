# Architecture

How lazy-to-text is put together.

The application is a PySide6 desktop program with three layers: the
interface in `app/gui/`, the inference in `app/backends/`, and the domain
logic in the modules at the root of `app/`. Only the first layer imports
Qt, and that rule is what makes the other two testable without a screen.

## The shape

| Module | What it is responsible for |
| --- | --- |
| `app/gui/app.py` | The entry point. `main()` and `main_cuda()`, the early start of the worker process, the Dock icon. |
| `app/gui/main_window.py` | The sidebar and the stacked views, the shortcuts, the window chrome. |
| `app/gui/controllers/app_controller.py` | The orchestrator: the model loading, the recording loop, the cancel path. 1,868 lines. |
| `app/gui/controllers/_storage_mixin.py` | The storage settings: the models directory, the history, the reset and the move. |
| `app/gui/controllers/_transcribe_mixin.py` | The Transcribe tab: the file drop, the decode, the transcript, the copy. |
| `app/gui/controllers/_tray_mixin.py` | The tray icon and the menu, and the state the tray shows. |
| `app/gui/controllers/_history_mixin.py` | The history view, the search and the export. |
| `app/gui/controllers/recording_controller.py` | A `QObject` wrapper over `StateManager`, so the signals reach the interface. |
| `app/gui/views/` | One widget per sidebar tab: models, transcribe, history, logs, presets, shortcuts, and the first-run view. |
| `app/gui/widgets/` | The building blocks: the model card, the sidebar, the top bar, the level meter, the recording capsule, the page header, the empty state, the dialogs. |
| `app/gui/theme.py` | The tokens. The dark set, the light set, the spacing scale, the radii and the type scale. |
| `app/gui/styles/base.qss` | The stylesheet. The colour tokens are substituted in at load time. |
| `app/gui/icons/` | The Heroicons set the sidebar uses, under `app/gui/styles/icons/`. |
| `app/backends/base.py` | The `TranscriptionBackend` Protocol. The contract every engine implements. |
| `app/backends/onnx_backend.py` | `OnnxAsrBackend`: the inference, the provider list, the chunking, the file decode. |
| `app/backends/registry_backend.py` | `RegistryBackend`: an alias to a canonical id, a family and a load id, and the rebuild when the family changes. |
| `app/backends/subprocess_backend.py` | The same backend in a worker process, started with `multiprocessing.get_context("spawn")`. |
| `app/backends/subprocess_worker.py` | The worker side of that process. |
| `app/state_manager.py` | The domain state machine: idle, recording, processing, and the model loading flag. |
| `app/audio_recorder.py` | The capture through `sounddevice`, and the resample to 16 kHz. |
| `app/clipboard_manager.py` | The text to the clipboard and the paste keystroke to the window that has the focus. |
| `app/config_manager.py` | The reading and the writing of `config.yaml`, and the defaults. |
| `app/history_manager.py` | The history file and the plain-text export. |
| `app/hotkey_listener.py` | The binding: `global-hotkeys` on Windows, a native AppKit monitor on macOS, `pynput` on Linux. |
| `app/macos_hotkeys.py` | The macOS event monitor and the push-to-talk spec. |
| `app/macos_permissions.py` | The Accessibility and the Microphone checks, and the banners that open the right System Settings pane. |
| `app/instance_manager.py` | The single-instance lock: a named mutex on Windows, a `filelock` elsewhere. |
| `app/model_mapping.py` | The registry of the sixteen models, and the one copy of the measurement. |
| `app/inference_settings.py` | The per-model settings dataclasses. |
| `app/llm/` | The optional post-processing client, the modes, the providers and the presets. |
| `app/resource_monitor.py` | The CPU, the RAM, the GPU and the VRAM sampler. |
| `app/i18n/` | The Russian catalogue, `app_ru.ts` and the compiled `app_ru.qm`. |
| `app/utils.py` | The cache and the path helpers, and the single answer to where the data lives. |
| `scripts/` | The build wrappers, the icon and the screenshot generators, the translation updater, the bundle pruner. |
| `tests/` | 71 test files: `tests/gui/` for the widgets, `tests/backends/` for the dispatch, `tests/utils/` for `app/utils.py`. |

## The data flow

```
hotkey -> recorder -> 16 kHz mono audio -> ONNX backend -> text -> clipboard -> paste
```

The recording is a float32 mono buffer at the microphone's own rate,
resampled to 16 kHz with `scipy.signal.resample_poly`. A dictation is capped
at 300 seconds, and the cap is a backstop rather than the mechanism.

The inference path, with the worker process in the middle:

```
StateManager      idle -> recording -> processing -> idle
  |
  +-- AudioRecorder          the buffer, resampled to 16 kHz
  +-- SubprocessBackend      a spawned worker, up to 10 s to come up
        |
        +-- RegistryBackend   the alias to a canonical id and a family
              |
              +-- OnnxAsrBackend   25 s chunks, CUDA or CoreML, CPU on failure
                    |
                    +-- onnx-asr and onnxruntime
  |
  +-- the text: the clipboard, then the paste keystroke
  +-- the optional post-processing, through app/llm/
```

A file arrives by the other route. `OnnxAsrBackend.transcribe_file(path)`
decodes it through `soundfile` first, and falls back to the bundled static
`ffmpeg` from `imageio-ffmpeg` when that fails, with raw PCM through a
stdout pipe and a ten-minute cap on the decode. There are no temporary
files, and the source file is never modified or copied.

The post-processing path is optional and off by default. When it is on, the
text the recogniser produced goes to the model of the chosen preset, and the
result goes to the clipboard. When the model cannot answer, the raw
transcription is pasted and the reason goes to the log.

## Decisions worth knowing about

### Only `app/gui/` imports Qt

Everything else is plain Python with no UI dependencies. The domain modules
depend on each other through Protocols, and the dependency graph fans inward
toward `app/utils.py`.

### One inference path

Every model goes through `OnnxAsrBackend` and `onnx-asr`: Whisper, GigaAM,
Parakeet, Canary, T-One and Vosk under one API. PyTorch, NeMo and
CTranslate2 are not in the dependency tree, so a new model is a registry
entry rather than a new dependency, and the install size follows from that
decision.

### The inference runs in a worker process

`main()` starts a `SubprocessBackend` and waits up to 10 seconds for the
worker to answer, and falls back to the in-process `RegistryBackend` only if
the worker fails to come up. The reason is the GIL: ONNX Runtime's pybind11
bindings do not release it during session creation, which starves every
Python slot for about 0.3 seconds.

The worker uses `multiprocessing.get_context("spawn")`, and the fixture in
`tests/backends/test_subprocess_backend.py` patches `get_context`, so
patching the bare module attributes does not intercept the call.

### The measurement lives in the registry

`app/model_mapping.py` holds the WER and the real time factor of each of
the sixteen models, and a test asserts that every surface quoting them
quotes the same copy. The registry owns the number so that the cards, the
README and the test cannot drift apart.

### The recording capsule must not take the focus

`raise_()` on a background event steals the caret from the window the user
is typing in. The capsule uses `WA_ShowWithoutActivating`, and
`app/gui/mac_window.py` puts the window at `NSStatusWindowLevel` with the
`NonactivatingPanel` style mask, so it floats above a full-screen window in
another application without pulling that application's Space forward.

### The icon in the Dock is a runtime policy

`setup.py` ships no `LSUIElement`, so the application has a Dock icon and a
Cmd-Tab entry while the main window is up.
`app/gui/dock_presence.py` switches the activation policy to accessory while
the recording overlay is up. The policy is per process, so it cannot be
expressed as a plist key that varies per window.

### The data paths depend on how the application was started

`app/utils.py:_is_frozen()` and `app/config_manager.py:_resolve_base_dir()`
decide between the in-tree paths of a source checkout and the per-user
directories of a frozen bundle. Everything else asks those two functions
where the data lives.

## Boundaries

- **`app/gui/` is the only layer that imports Qt.** `app/backends/` and the
  domain modules know nothing about the interface, which is what lets the
  test suite run without a screen.
- **`app/backends/` depends on `app/utils.py` and `app/inference_settings.py`
  and on nothing else.** A change of engine goes through `RegistryBackend`,
  which resolves the alias from `app/model_mapping.py`.
- **The domain modules talk through Protocols.** There are no circular
  imports, and the graph fans inward toward `app/utils.py`.
- **`AppController` is mixin-composed.** Storage, Transcribe, Tray and
  History each live in their own `_*_mixin.py`, so the orchestrator stays on
  the model loading and the recording loop.
- **The theme tokens are the only source of colour.** `app/gui/theme.py`
  holds them, `base.qss` consumes them, and a widget that writes a hex
  literal breaks the light theme.
- **The tests never load a model and never touch the microphone.** Hardware
  and the libraries are replaced with fakes.
