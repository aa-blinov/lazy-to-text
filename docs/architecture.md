# Architecture

How lazy-to-text is put together.

The application is an Electron window over a headless Python runtime. The
window, the tray and the recording capsule are Electron (`desktop/`); the
microphone, the hotkeys, the models, the clipboard, the configuration and the
history belong to Python. The Python side has three layers: the runtime
protocol in `app/server/`, the inference in `app/backends/`, and the domain
logic in the modules at the root of `app/`. None of them imports a UI
toolkit, which is what makes them testable without a screen.

## The shape

| Module | What it is responsible for |
| --- | --- |
| `desktop/electron/` | The shell: windows, tray, the capsule, the menu, starting and watching the runtime (`backend.cjs`), file open, run at login. |
| `desktop/renderer/` | The Svelte interface on `@monos/ui`: one view per sidebar item, the capsule, the first-run page. |
| `desktop/renderer/src/i18n/*.json` | The Russian catalogue, the only source of translation. |
| `app/server/__main__.py` | The runtime entry point (`lazy-to-text-server`): arguments, the single-instance lock, the ready line, the exit path. |
| `app/server/runtime.py` | `Runtime`: builds the recording stack, owns the log ring and the state events, answers `stuck()` on exit. |
| `app/server/httpd.py`, `rpc.py`, `events.py`, `tickets.py` | The loopback HTTP and event channel, the method registry, the event bus, one-time tickets. |
| `app/server/handlers/` | One module per area: settings, models, history, presets, files, devices, permissions, first run, core. |
| `app/recording_factory.py` | Builds recorder, feedback, clipboard, state manager and hotkey listener from the configuration. |
| `app/bootstrap.py` | Start-up helpers: storage path, Hugging Face token, onnx-asr pre-import, persisted-model autoload, the rotating log file and its filters. |
| `app/backends/base.py` | The `TranscriptionBackend` Protocol and `TranscriptionError`. |
| `app/backends/onnx_backend.py` | `OnnxAsrBackend`: the inference, the provider list, the chunking, the file decode, the post-load probe. |
| `app/backends/registry_backend.py` | `RegistryBackend`: an alias to a canonical id, a family and a load id. |
| `app/backends/subprocess_backend.py`, `subprocess_worker.py` | The same backend in a spawned worker process. |
| `app/state_manager.py` | The domain state machine: idle, recording, processing, and the model loading flag. |
| `app/audio_recorder.py` | The capture through `sounddevice`, the resample to 16 kHz, the stuck-thread abort. |
| `app/clipboard_manager.py` | The text to the clipboard and the paste keystroke; the three-way delivery result. |
| `app/config_manager.py` | Reading and writing `config.yaml`, and the defaults. |
| `app/history_manager.py` | The history file and the plain-text export. |
| `app/hotkey_listener.py`, `macos_hotkeys.py`, `hotkey_rules.py` | The binding per platform, and the rules shared with the interface. |
| `app/macos_permissions.py`, `mic_check.py` | The Accessibility and Microphone checks. |
| `app/instance_manager.py` | The single-instance lock: a named mutex on Windows, a `filelock` elsewhere. |
| `app/model_mapping.py` | The registry of sixteen models and the one copy of the measurement. |
| `app/inference_settings.py` | The per-model settings dataclasses. |
| `app/llm/` | The optional post-processing client, the modes, the providers and the presets. |
| `app/resource_sampler.py` | The CPU and RAM sampler. |
| `app/translation_mark.py` | `mark()`: flags an English sentence Python builds so the translation check sees it. |
| `app/ui_prefs.py` | Theme, palette, language and text-scale rules the runtime stores. |
| `app/utils.py` | Cache and path helpers, and the single answer to where the data lives. |
| `scripts/` | The runtime build (`build_server.py`), the patched PortAudio build, signing setup, icon and screenshot tools, the translation check. |
| `tests/` | Engine and runtime tests; `tests/server/` for the runtime protocol, `tests/backends/` for dispatch. |

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
              +-- OnnxAsrBackend   25 s chunks, CoreML or CPU, CPU on failure
                    |
                    +-- onnx-asr and onnxruntime
  |
  +-- the text: the clipboard, then the paste keystroke
  +-- the optional post-processing, through app/llm/
```

The interface does not touch any of it. The shell starts the runtime, reads
its ready line (a port and a token), and the renderer calls it over the
loopback channel; state changes come back as events, and the tray and the
capsule follow them.

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

### One front end over the engine

There was a second one, a Qt window, and it is gone (spec 011). Every
behavioural rule it enforced lives in the engine or the runtime, or in the
renderer that replaced it; the baseline specs 001 to 009 describe that
behaviour.

### One inference path, CPU and CoreML

Every model goes through `OnnxAsrBackend` and `onnx-asr`: Whisper, GigaAM,
Parakeet, Canary, T-One and Vosk under one API. PyTorch, NeMo and
CTranslate2 are not in the dependency tree, so a new model is a registry
entry rather than a new dependency. The stock `onnxruntime` wheel gives CoreML
on Apple silicon and the CPU everywhere else; there is no GPU build.

### The inference runs in a worker process

The runtime starts a `SubprocessBackend` and falls back to the in-process
`RegistryBackend` only if the worker fails to come up. The reason is the GIL:
ONNX Runtime's pybind11 bindings do not release it during session creation,
which starves every Python slot for about 0.3 seconds.

The worker uses `multiprocessing.get_context("spawn")`, and the fixture in
`tests/backends/test_subprocess_backend.py` patches `get_context`, so
patching the bare module attributes does not intercept the call.

### The measurement lives in the registry

`app/model_mapping.py` holds the WER and the real time factor of each of the
sixteen models, and a test asserts that every surface quoting them quotes the
same copy. The registry owns the number so that the cards, the README and the
test cannot drift apart.

### Translations have one source

The renderer looks a string up by its English text in
`desktop/renderer/src/i18n/*.json`. Sentences Python builds are marked with
`mark()` and translated by the renderer, whole or by `%1` template.
`scripts/check_translations.py` fails when one has no Russian entry.

### The data paths depend on how the runtime was started

`app/utils.py:_is_frozen()` and `app/config_manager.py:_resolve_base_dir()`
decide between the in-tree paths of a source checkout and the per-user
directories of the packaged runtime; `L2T_DATA_DIR` overrides both for a test
or a tester. Everything else asks those functions where the data lives.

## Boundaries

- **No Python module imports a UI toolkit.** The runtime is plain Python, and
  a test imports it with a hook that refuses `PySide6`.
- **`app/backends/` depends on `app/utils.py` and `app/inference_settings.py`
  and on nothing else.** A change of engine goes through `RegistryBackend`,
  which resolves the alias from `app/model_mapping.py`.
- **The domain modules talk through Protocols.** There are no circular
  imports, and the graph fans inward toward `app/utils.py`.
- **The renderer holds no rule the engine enforces.** Hotkey rules, model
  descriptions and settings validation come from Python.
- **The tests never load a model and never touch the microphone.** Hardware
  and the libraries are replaced with fakes.
