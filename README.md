# Lazy to Text

Press a hotkey, speak, paste.

Lazy to Text is a speech-to-text app for Windows, macOS and Linux. It records
from your microphone on a global hotkey, transcribes the recording on your
computer, and pastes the text into the window you were typing in. Audio never
leaves the machine. The network is used to download a model the first time you
pick it, and, only if you turn on post-processing with a cloud provider, to
send the transcribed text to that provider.

![The Transcribe screen of the Monos interface](docs/screenshots/transcribe.png)

[![Python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/UI-Electron-47848f)](https://www.electronjs.org/)
[![ONNX Runtime](https://img.shields.io/badge/inference-onnxruntime-005CED)](https://onnxruntime.ai/)
[![onnx-asr](https://img.shields.io/badge/loader-onnx--asr-blueviolet)](https://github.com/istupakov/onnx-asr)
[![Release](https://img.shields.io/github/v/release/aa-blinov/lazy-to-text)](https://github.com/aa-blinov/lazy-to-text/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

The window, tray and recording capsule are an Electron app drawn with the
[Monos](https://github.com/aa-blinov/monos-ui) kit. Transcription, hotkeys,
paste and sound run in a headless Python runtime that the app starts and keeps
alive. The earlier Qt window and the Windows CUDA build were retired; see
[Coming from the classic app](#coming-from-the-classic-app).

---

## Quick start

Download the installer for your system from
[the latest release](https://github.com/aa-blinov/lazy-to-text/releases/latest).

| Platform | Assets |
| --- | --- |
| Windows | an installer and a portable `.exe` (`LazyToText-Desktop-…-win-x64.exe`) |
| macOS | a `.dmg` and a `.zip`, Apple silicon |
| Linux | an `.AppImage` and a `.deb`, x64 |

The release page lists the exact names and sizes. Use the portable Windows
build where you cannot run an installer; it unpacks the whole app to a
temporary folder on every launch, so the installer starts faster.

**On macOS**, the first launch needs two permissions: Accessibility (for global
hotkeys and the paste keystroke) and Microphone (for recording). macOS does
not ask on its own, so Settings shows a banner that opens the right System
Settings pane.

Run it from source with Python 3.12, [uv](https://docs.astral.sh/uv/), Node
22 and a microphone:

```bash
git clone https://github.com/aa-blinov/lazy-to-text.git
cd lazy-to-text

uv sync --frozen             # creates the venv from uv.lock
cd desktop
npm install
npm run dev                  # starts the runtime, the renderer and Electron
```

The Python runtime also runs on its own, which is how the tests and the
packaging smoke run exercise it:

```bash
uv run lazy-to-text-server   # prints a ready line with a port and a token
```

The first launch loads no model. Pick one on the Models screen and click
**Download**. The weights go to `<project>/models/hub/` from source, or to the
per-user cache folder in an installed app. You can change the folder in
Settings → Storage.

To transcribe a file instead of speaking, open **Transcribe** and drop the file
anywhere on the window.

| Platform | What it needs |
| --- | --- |
| Windows 10 and 11 | A CPU. Vosk, GigaAM and T-One run comfortably on it; the larger models are slower. |
| macOS 12 and later on Apple silicon | CoreML sends inference to the Neural Engine and the GPU on its own. |
| Linux | X11 for the global hotkeys and the paste keystroke. Wayland does not let an application listen for keys it does not own. |

### Coming from the classic app

The classic Qt window and the CUDA build are gone. The Electron app has the
same application id, so macOS keeps its Microphone and Accessibility grants,
and it reads the same folders: your `config.yaml`, history and downloaded
models are kept. On Windows the installer offers to remove a classic install,
because both copies cannot run at once (they share one single-instance lock).
GPU inference is not part of the app any more: Windows runs on the CPU.

## What it does

- **Hotkey in, text out.** `Ctrl+F2` starts a recording, `Ctrl+F3` stops it
  and transcribes, and the text is pasted into the window that has focus. All
  three keys can be changed. The macOS defaults differ on purpose; see
  [Hotkeys](#hotkeys).
- **Sixteen models, one inference path.** Every model loads through the same
  `OnnxAsrBackend`, which runs on
  [`onnx-asr`](https://github.com/istupakov/onnx-asr) and ONNX Runtime. There
  is no PyTorch, NeMo or CTranslate2 in the dependency tree, so a new model
  is a registry entry, not a new dependency. Each card shows its measured
  accuracy and speed; see [Models](#models).
- **Transcribe files too.** Drop an audio or video file on the Transcribe screen.
  `soundfile` reads WAV, FLAC, OGG, OPUS and AIFF. A bundled static `ffmpeg`
  handles MP3, M4A, AAC, WMA, MP4, MOV, MKV, WebM, AVI, FLV and 3GP, so you
  do not install ffmpeg yourself. The transcript is editable before you copy
  it, and the identity line says *Edited* once the text differs from what the
  model returned.
- **Russian first.** Vosk RU Small weighs 30 MB and reaches 4.5% WER, close
  to the top of the table. The most accurate model overall is GigaAM v2 at
  3.5% WER (889 MB). All of the top five cover Russian. GigaAM v3 punctuates
  and capitalises its output, which makes it the default for text that goes
  into a document. Multilingual coverage comes from Parakeet TDT v3, Canary 1B
  v2 and Whisper, and GigaAM Multilingual adds Kazakh, Kyrgyz and Uzbek.
- **CoreML where it helps, CPU everywhere.** On Apple silicon the app uses
  CoreML. Everywhere else it runs on the CPU. If CoreML is missing, or a
  model fails on it, the app retries on the CPU. The status strip names the
  processor that is running, so a fallback is never silent.
- **Per-model settings, applied live.** Language, VAD, beam size, temperature
  and prompt for the Whisper cards, and a smaller panel for the rest.
  Settings are stored per model alias and applied to the running backend
  without a restart.
- **Diagnostics in the status strip.** CPU and RAM on every platform, with
  GPU and VRAM readouts on Windows machines with an NVIDIA driver. A level
  meter shows a muted microphone before you start speaking. Logs are
  colour-coded, and network lines are hidden by default. History is searchable
  and can be exported.
- **Tray and capsule.** The tray icon shows the current state, a small
  capsule at the bottom of the screen shows that the app is listening and then
  what happened to your words, and a single-instance guard stops a second
  copy from starting.
- **Light and dark, six palettes.** The app follows the system appearance.
  Settings can force either theme and pick a palette.
- **Narrow windows.** The window can shrink to 900 × 600.
- **Two interface languages.** English and Русский. Switch in Settings; the
  change applies at once.
- **Optional text clean-up, off by default.** A language model can rewrite
  the transcription before it is pasted: clean it up, make it concise, turn it
  into formal prose, or follow your own instruction. Speech is still
  recognised on your machine. A cloud provider receives the words the model
  produced. If the model cannot answer, the raw transcription is pasted and
  the reason is written to the log. See
  [Post-processing](#post-processing).
- **Small things.** Started a download by mistake? Cancel rolls it back at
  once, without waiting for it to finish. `Ctrl+1..6` switches screens.

## Screenshots

| Models | Transcribe |
| :---: | :---: |
| ![Models](docs/screenshots/models.png) | ![Transcribe](docs/screenshots/transcribe.png) |

| History | Logs |
| :---: | :---: |
| ![History](docs/screenshots/history.png) | ![Logs](docs/screenshots/logs.png) |

| Post-processing | Settings |
| :---: | :---: |
| ![Post-processing](docs/screenshots/presets.png) | ![Settings](docs/screenshots/shortcuts.png) |

| Narrow window | Russian interface |
| :---: | :---: |
| ![Models in Russian](docs/screenshots/ru/models.png) | ![History in Russian](docs/screenshots/ru/history.png) |

`scripts/generate_desktop_screenshots.py` takes these from the packaged Electron
app, so they show the current release. Add `--lang ru` for the Russian set.

## How it works

```
hotkey -> recorder -> 16 kHz mono audio -> ONNX backend -> text -> clipboard -> paste
```

The recording is a float32 mono buffer at the microphone's own rate, resampled
to 16 kHz with `scipy.signal.resample_poly`. A dictation is capped at 300
seconds. The backend cuts long audio into 25 s chunks, which is inside the
~30 s window the ONNX exports were trained on.

```
┌──────────────────────────────┐  loopback HTTP + events  ┌──────────────────────────────┐
│ Electron shell (desktop/)    │◀────────────────────────▶│ Python runtime (app/server)  │
│ window, tray, capsule, menu  │   started and watched    │ handlers, event bus          │
│ Svelte renderer on @monos/ui │   by the shell           └──────────────┬───────────────┘
└──────────────────────────────┘                                         │
                                                                         ▼
┌─────────────┐    callbacks    ┌──────────────────────────────┐
│ Hotkey      ├────────────────▶│  StateManager  (app/)        │
│ Listener    │                 │  recording / processing /    │
└─────────────┘                 │  model_loading state machine │
                                └─────┬───────────────┬────────┘
                                      │               │
                           audio_data │               │ transcribe(audio)
                                      ▼               ▼
                         ┌──────────────────┐  ┌──────────────────────┐
                         │ AudioRecorder    │  │ TranscriptionBackend │
                         │ sounddevice +    │  │   (Protocol)         │
                         │ daemon thread    │  └─────────┬────────────┘
                         └──────────────────┘            │
                                                         ▼
                                         ┌────────────────────────────┐
                                         │ SubprocessBackend          │
                                         │ a spawned worker process   │
                                         └────────────┬───────────────┘
                                                      │
                                                      ▼
                                         ┌────────────────────────────┐
                                         │ RegistryBackend  (façade)  │
                                         │ alias → canonical / family │
                                         │ / onnx_load_id             │
                                         └────────────┬───────────────┘
                                                      │
                                                      ▼
                                         ┌────────────────────────────┐
                                         │ OnnxAsrBackend             │
                                         │ family-aware (whisper /    │
                                         │ gigaam / parakeet);        │
                                         │ CoreML → CPU fallback;     │
                                         │ 25 s chunking              │
                                         └────────────┬───────────────┘
                                                      │
                                                      ▼
                                         ┌────────────────────────────┐
                                         │ onnx-asr + onnxruntime     │
                                         │ (CoreML on Apple silicon,  │
                                         │  CPU everywhere)           │
                                         └────────────────────────────┘
```

| Path | What it holds |
| --- | --- |
| `desktop/electron/` | The shell: windows, tray, capsule, menu, starting the runtime. |
| `desktop/renderer/` | The Svelte interface, and the Russian catalogue in `src/i18n/`. |
| `app/server/` | The runtime: the entry point `lazy-to-text-server`, the loopback channel and one handler module per area. |
| `app/recording_factory.py` | Builds recorder, feedback, clipboard, state manager and hotkey listener from the configuration. |
| `app/backends/base.py` | The `TranscriptionBackend` Protocol. |
| `app/backends/onnx_backend.py` | `OnnxAsrBackend`, the inference itself. |
| `app/backends/registry_backend.py` | `RegistryBackend`, which resolves an alias to a canonical id, a family and a load id. |
| `app/backends/subprocess_backend.py` | The same backend in a spawned worker process. |
| `app/state_manager.py` | The domain state machine: recording, processing, model loading. |
| `app/audio_recorder.py` | Capture through `sounddevice`, with the resample to 16 kHz. |
| `app/clipboard_manager.py` | Copying the text and delivering the paste keystroke. |
| `app/config_manager.py` | Reading and writing `config.yaml`. |
| `app/history_manager.py` | The transcription history, and the plain-text export. |
| `app/hotkey_listener.py` | The global hotkey binding: `global-hotkeys` on Windows, a native AppKit monitor on macOS, `pynput` on Linux. |
| `app/instance_manager.py` | The single-instance lock: a named mutex on Windows, `filelock` elsewhere. |
| `app/model_mapping.py` | The registry of supported models, and the one copy of the measurement. |
| `app/inference_settings.py` | The per-model settings dataclasses. |
| `app/llm/` | The optional post-processing client, the modes, the providers and the presets. |
| `app/resource_sampler.py` | The CPU, RAM, GPU and VRAM sampler. |
| `app/utils.py` | Cache and path helpers. |

The layering rules are strict:

- No Python module imports a UI toolkit. The runtime is plain Python, which
  is what makes it testable in isolation, and a test imports it with a hook
  that refuses `PySide6`.
- `app/backends/` depends on `app.utils` and `app.inference_settings` and
  knows nothing about the interface. Cross-engine swaps go through
  `RegistryBackend`, which resolves the alias from `app.model_mapping`.
- The domain modules depend on each other through Protocols. There are no
  circular imports, and the dependency graph fans inward toward `app.utils`.

For file transcription, `OnnxAsrBackend.transcribe_file(path)` decodes the
file through `soundfile` first; on failure it falls back to the bundled static
`ffmpeg` from `imageio-ffmpeg`, with raw PCM through a stdout pipe and a
10-minute cap on the decode. There are no temp files, and the source file is
never modified or copied.

### Hardware acceleration

`device: auto` is the default, and it is platform-aware:

- **macOS.** The backend stages `CoreMLExecutionProvider` ahead of CPU with
  `ModelFormat=MLProgram` and `MLComputeUnits=ALL`, so CoreML's dispatcher
  routes ops to the Neural Engine, the GPU or the CPU per op. Explicit
  overrides: `device: coreml` or `device: cpu`.
- **Windows and Linux.** The stock `onnxruntime` wheel runs on the CPU. There
  is no GPU build and no CUDA installer.

The app retries on CPU automatically if the CoreML session fails at
session-create time, which covers an op the provider does not support. The Logs
screen surfaces the retry as a warning.

CPU-only is fine for `vosk-ru-small`, `vosk-ru`, `t-one` and `gigaam-v3-ctc`.
The larger Whisper, Parakeet and Canary models (`whisper-large-v3-turbo`,
`parakeet-tdt-v3`, `canary-1b-v2`) are usable on CPU but noticeably slower;
CoreML on Apple silicon brings them down to a few seconds for a 1-minute clip.

## Tech stack

- Python 3.12 for the engine and the runtime.
- Electron and Svelte, with the [Monos](https://github.com/aa-blinov/monos-ui)
  kit, for the interface.
- [`onnx-asr`](https://github.com/istupakov/onnx-asr) and
  [ONNX Runtime](https://onnxruntime.ai/) as the single inference path:
  Whisper, GigaAM, Parakeet, Canary, T-One and Vosk under one API. The stock
  `onnxruntime` wheel everywhere, where `CoreMLExecutionProvider` serves Apple
  silicon.
- [`soundfile`](https://github.com/bastibe/python-soundfile) (libsndfile)
  for the native decoding of WAV, FLAC, OGG, OPUS and AIFF.
- [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg): a bundled
  static ffmpeg binary for the MP3, M4A, MP4, MKV and WebM file path.
- `sounddevice` for the capture, `pyperclip` for the clipboard text.
- Hotkeys and auto-paste: Windows uses `global-hotkeys` for the binding
  (the native `RegisterHotKey`) and `pywin32` for the paste keystroke
  (`keybd_event`); macOS uses a native AppKit keyboard monitor for the hotkeys
  and Accessibility-targeted key delivery for the auto-paste, with Quartz as
  a fallback; Linux uses [`pynput`](https://pynput.readthedocs.io/).
- Sound feedback: `winsound` on Windows and
  [`playsound3`](https://github.com/szmikler/playsound3) elsewhere (AppKit on
  macOS, GStreamer on Linux).
- The single-instance lock: a native named mutex on Windows, a `filelock`
  lockfile elsewhere.
- [`platformdirs`](https://platformdirs.readthedocs.io/) for the
  cross-platform user directories.
- `psutil` for the CPU and the RAM, `nvidia-ml-py` (Windows only) for the
  GPU readout in the status strip. Monitoring only: inference never uses the GPU.

## Hotkeys

| Action | Default: Windows / Linux | Default: macOS | Configurable |
| --- | --- | --- | --- |
| Start recording | `Ctrl+F2` | `Ctrl+F8` | yes, in Settings |
| Stop and transcribe | `Ctrl+F3` | `Ctrl+F9` | yes, in Settings |
| Cancel the current recording | `Ctrl+F6` | `Ctrl+F10` | yes, in Settings |
| Switch screen (Transcribe, Models, History, Post-processing, Settings, Logs) | `Ctrl+1..6` | `Ctrl+1..6` | no |
| Open Settings | none | `Cmd+,` | no, App menu |
| Quit | tray menu | `Cmd+Q` | no, App menu |
| Hide or show the window | close button or tray click | close button or menu-bar click | no |

macOS reserves `Ctrl+F1` through `Ctrl+F7` for system keyboard navigation:
menu bar, Dock, windows, toolbar and so on. The OS captures those keys before
`pynput` sees them, so the macOS defaults use the higher F-keys. Every
binding can be changed.

The Settings tab carries two more recording modes. `toggle` makes one key flip
between idle and recording, and `push_to_talk` records while a single key is
held. Push to talk binds right Cmd on macOS and right Alt on Windows and
Linux, and ignores a press shorter than 0.2 s so a stray tap cannot produce
an empty transcription.

Edits in Settings are saved as you make them, and there is no Save button.
The auto-paste toggle applies to the running clipboard manager at once.

## Models

Every model is an ONNX export downloaded from Hugging Face on first use. The
accuracy and speed columns are our own measurements, not vendor figures: 400
clips from the Golos test split (370 of them in the 1554-word speech bucket,
1312 s), CPU, spoken numbers counted separately because Golos spells digits
out and every model here writes them as digits. At that sample size the 95%
interval is roughly ±1.0 to 1.8 points, so read a gap under about 2 points as
a tie.

| Alias | HF repo | Size | WER | RTF | Languages |
| --- | --- | --- | --- | --- | --- |
| `gigaam-v2` | `istupakov/gigaam-v2-onnx` | 889 MB | 3.5% | 0.015 | RU only |
| `vosk-ru-small` | `alphacep/vosk-model-small-ru` | 30 MB | 4.5% | 0.006 | RU only |
| `gigaam-multilingual-large-ctc` | `istupakov/gigaam-multilingual-large-ctc-onnx` | 564 MB | 4.6% | 0.028 | ru/kk/ky/uz/en |
| `vosk-ru` | `alphacep/vosk-model-ru` | 50 MB | 4.7% | 0.007 | RU only |
| `fastconformer-ru` | `istupakov/stt_ru_fastconformer_hybrid_large_pc_onnx` | 137 MB | 4.9% | 0.009 | RU only |
| `parakeet-tdt-v3` | `istupakov/parakeet-tdt-0.6b-v3-onnx` | 1.2 GB | 5.0% | 0.020 | 25 langs |
| `gigaam-multilingual-ctc` | `istupakov/gigaam-multilingual-ctc-onnx` | 225 MB | 6.2% | 0.026 | ru/kk/ky/uz/en |
| `gigaam-v3-ctc` *(default)* | `istupakov/gigaam-v3-onnx` | 260 MB | 7.1% | 0.018 | RU only |
| `gigaam-v3-rnnt` | `istupakov/gigaam-v3-onnx` | 290 MB | 7.4% | 0.012 | RU only |
| `t-one` | `t-tech/T-one` | 290 MB | 10.8% | 0.030 | RU only |
| `canary-1b-v2` | `istupakov/canary-1b-v2-onnx` | 2.0 GB | 11.4% | 0.059 | 25 langs |
| `whisper-large-v3-turbo` | `onnx-community/whisper-large-v3-turbo` | 1.6 GB | 16.2% | 0.457 | multilingual |
| `whisper-base` | `istupakov/whisper-base-onnx` | 107 MB | 55.6% | 0.039 | multilingual |
| `parakeet-ctc-0.6b` | `istupakov/parakeet-ctc-0.6b-onnx` | 623 MB | 122.8% | 0.019 | EN only |
| `parakeet-tdt-v2` | `istupakov/parakeet-tdt-0.6b-v2-onnx` | 2.3 GB | 124.4% | 0.020 | EN only |
| `parakeet-rnnt-0.6b` | `istupakov/parakeet-rnnt-0.6b-onnx` | 631 MB | 126.3% | 0.022 | EN only |

Sorted by measured WER, so the ranking is the argument. Three things that
number does not say on its own:

- **Punctuation is the default's whole job.** GigaAM v3 is 7.1% while Vosk
  Small is 4.5%, and the default is still the right pick for text that gets
  pasted into a document: it capitalises and punctuates the output itself.
  The CTC cards above it in the table return plain lowercase.
- **Spoken numbers split the table.** FastConformer RU, Parakeet TDT and
  GigaAM Multilingual write them correctly (0% WER); the GigaAM v3 default
  and both Whisper cards garble them at 45 to 46%.
- **The Whisper card is the only reason to be multilingual, not a quality
  tier.** Whisper Large v3 Turbo is 16.2% on Russian, third worst of the
  cards that produce usable text, and thirty times worse than Vosk Small, for
  1.6 GB and half a second of real time per minute of audio. It earns its
  place by covering languages nothing else here does. The full Whisper Large
  v3 was measured and withdrawn: 15.5% at 0.72 RTF in a precision that does
  not load, and 15.6% at 1.43 RTF in the one that does, the same accuracy as
  the Turbo for twice the download and a third of the speed.

Golos is read speech with room tone: voice-assistant style commands, two
seconds each. Treat these as the floor of what the models handle rather than
the ceiling, and note that no test in this repository loads a model at all.
The numbers above come from a hand-run benchmark against the real
`OnnxAsrBackend`, not from the suite.

## Post-processing

Post-processing is optional and off by default. When it is on, the
transcription goes through a language model before it reaches the clipboard.
Turn it on, and choose the service, the model and the mode, on the
**Post-processing** tab.

**Modes.** *Clean up* fixes punctuation, capitals and paragraphs, and drops
filler words and false starts. *Make concise* keeps every fact, name, number
and commitment in fewer words. *Formal prose* rewrites the text as formal
written prose without adding anything the speaker did not say. A preset can
carry its own instruction in place of a mode.

**Rules every mode follows.** Numbers come out as digits, so "forty-two"
becomes 42, and the language never changes: nothing is translated.

**Where the words go.** Speech is always recognised on your machine. A
language model receives only the text the recogniser produced, and only when
post-processing is on. *Ollama* and *LM Studio*, when they run on your own
computer, keep that text there. The cloud providers in the list receive it:
OpenAI, OpenRouter, Groq, DeepSeek, Together AI, Mistral, xAI, Cerebras and
NVIDIA NIM. *Custom OpenAI-compatible server* covers anything else, including
a self-hosted vLLM.

**Presets.** A preset holds a provider, a server address, a model name, an
API key, a mode and an optional instruction. You can keep several presets
and switch between them. On the Transcribe tab you can use a different preset
for one recording without changing the default.

**API keys are stored in plain text.** Keys are kept in `config.yaml` without
encryption, like the rest of that file. Use a key that you can revoke.

**If the model fails.** When the model cannot answer, the raw transcription is
pasted and the reason is written to the log. The dictation still reaches the
window.

## Configuration

`config.yaml` lives in the project root when you run from source, resolved by
walking up from the working directory to the nearest `pyproject.toml`. In an
installed app it is in the per-user folder listed below. Most fields are
exposed in the UI, and the file has the last word.

```yaml
whisper:
  model: gigaam-v3-ctc        # any alias from app/model_mapping.py, or
                               # any HF repo path with an ONNX export
  device: auto                # auto | cpu | coreml
                               # auto = CoreML on Apple silicon, CPU otherwise
  compute_type: float16       # float16 | int8 | float32
  language: auto              # ISO code, or "auto" for auto-detect
                               # (only Whisper honours this)
  beam_size: 5                # legacy field, ignored by the ONNX path

# Per-model overrides, written by the inline Inference settings panel
# on the active card. Each entry is keyed by alias.
model_overrides:
  whisper-large-v3-turbo:
    language: ru
    vad_filter: true
    beam_size: 7
    temperature: 0.0
    initial_prompt: "Anthropic, Claude, onnxruntime, GigaAM."
  parakeet-tdt-v3:
    timestamps: false
  gigaam-v3-rnnt: {}          # GigaAM ignores all of these (end-to-end)

hotkey:
  mode: two_keys               # two_keys | toggle | push_to_talk
  # Defaults differ per platform. See the Hotkeys section above for why
  # macOS uses higher F-keys.
  #   Windows / Linux: ctrl+f2 / ctrl+f3 / ctrl+f6
  #   macOS:           ctrl+f8 / ctrl+f9 / ctrl+f10
  start_recording_hotkey: ctrl+f2
  stop_recording_hotkey: ctrl+f3
  cancel_recording_hotkey: ctrl+f6
  push_to_talk_key: right_alt  # right_cmd on macOS
  push_to_talk_min_hold_seconds: 0.2

clipboard:
  auto_paste: true
  preserve_clipboard: false
  key_simulation_delay: 0.05

audio:
  channels: 1
  dtype: float32
  max_duration: 300
  device: 31                   # input device index from sounddevice;
                               # the Settings tab dropdown writes this.
                               # Left out, the system default is used.

audio_feedback:
  enabled: true
  start_sound: assets/sounds/record_start.wav
  stop_sound: assets/sounds/record_stop.wav
  cancel_sound: assets/sounds/record_cancel.wav

storage:
  models_dir: ""               # empty = use default
                               #   dev:  <project>/models
                               #   macOS app: ~/Library/Caches/LazyToText/models
                               # both are created on first model download.

history:
  enabled: true
  max_entries: 1000

llm:
  enabled: false
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: ""
  api_key: ""
  mode: clean
  timeout_s: 20

ui:
  theme: system                # system | light | dark
  language: en                 # en | ru
```

To reset settings, delete `config.yaml` and relaunch. Defaults are written
back. Settings → Storage carries Reset / Move / Open-folder controls if you
only want to reset the storage path.

The history is bounded by entry count alone. The old `auto_cleanup_days` key
was removed, because nothing ever read it and a setting that promises to erase
your dictations without doing it is worse than no setting.

### Where the data lives

The packaged runtime switches to per-user directories through
[`platformdirs`](https://github.com/tox-dev/platformdirs), because an app
installed under `/Applications` or `Program Files` cannot write there. They
are the folders the classic app used, so an upgrade keeps your data.

| Data | macOS | Windows |
| --- | --- | --- |
| `config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` and history | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights | `~/Library/Caches/LazyToText/models/` | `%LOCALAPPDATA%\LazyToText\Cache\models\` |

Running from source keeps the in-tree paths (`<project>/config.yaml`,
`<project>/logs`, `<project>/models`), so iterating on the source does not
pollute the user directories. `L2T_DATA_DIR` (or `--data-dir` on the runtime)
moves config, logs and history to a folder of your choice, which is how tests
and testers run without touching real data. The Storage card in Settings can
still override `models/` to any path, and `HF_HOME` is updated live, so the
next download lands in the new directory without a restart.

## Building a release

The runtime is built first, because it ships inside the app and has to be
built on the platform and architecture it is for. Then the shell wraps it.

```bash
uv sync --frozen
uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py
cd desktop
npm install
npm run build
node scripts/dist.mjs --dir      # an unpacked app in desktop/release, to try
npm run dist:mac                 # dmg and zip (add --arm64 or --x64 after --)
npm run dist:win                 # installer and portable exe
npm run dist:linux               # AppImage and deb
```

`scripts/build_server.py` builds `dist/lazy-to-text-server/` from
`lazy_to_text_server.spec`, replaces the `sounddevice` wheel's PortAudio with a
patched one on macOS, and starts the result to read one snapshot from it: a
runtime that builds and does not start fails there, not in the installer.
`.github/workflows/desktop.yml` does all of it on the three platforms, and a
`v*` tag makes `release.yml` create the GitHub release with the changelog
section as its body and attach the installers.

### The patched PortAudio on macOS

The `sounddevice` wheel ships a PortAudio that **deadlocks on macOS when a
recording stream is stopped**
([PortAudio/portaudio#1174](https://github.com/PortAudio/portaudio/issues/1174)).
The stop path and CoreAudio's own notification thread end up waiting for each
other's lock, so the recording thread never returns: the microphone stays held
for the rest of the session and every later dictation fails with "the
microphone is still held by the previous recording". Quitting hangs too,
because `Pa_Terminate` waits on the same mutex, and the process stays alive
with no window while still holding the single-instance lock.

The upstream fix is not in a PortAudio release (the last one is V19.7.0, from
2021), so the runtime ships a library built here: `vendor/portaudio/` holds the
patch and `scripts/build_patched_portaudio.py` builds PortAudio at a pinned
commit and installs it where `sounddevice` loads it from. To measure whether
the deadlock is still there:

```bash
uv run python scripts/stress_portaudio_stop.py 800 --duplex
```

It deadlocks at cycle ~709 against the wheel's own dylib, and runs thousands of
cycles clean against the patched one.

### Signing on macOS

**A build from CI is signed ad hoc**, because CI has no signing identity. An
ad-hoc signature identifies the app by its own hash, so macOS treats every
release as a new app and asks for the Microphone and Accessibility permissions
again after each update. A build made on a machine with the `Lazy to Text
Signing` certificate (`scripts/setup-signing.sh`, see CLAUDE.md) keeps its
permissions across rebuilds, and `CSC_NAME` names a Developer ID for a build
Apple can notarize. The Windows installers are not signed.

#### Notarizing the Mac build

Apple will not notarize anything without a Developer ID Application
certificate, which comes with the $99 per year Apple Developer Program.
Nothing else in the pipeline costs money: `notarytool`, `stapler`, `ditto` and
`spctl` all ship with the Xcode command line tools, and the notary service
itself is free. A fee waiver is available to nonprofit organisations,
accredited educational institutions and government entities.

Build with the certificate (`CSC_NAME="Developer ID Application: …" npm run
dist:mac`, which makes `dist.mjs` use the strict entitlement files and a
secure timestamp), then, on the `.app` it produced:

```bash
ditto -c -k --keepParent "Lazy to Text.app" "LazyToText.zip"
xcrun notarytool submit "LazyToText.zip" --keychain-profile l2t-notary --wait
xcrun stapler staple "Lazy to Text.app"
xcrun stapler validate "Lazy to Text.app"
spctl --assess --type execute --verbose=4 "Lazy to Text.app"
```

The `--keychain-profile` is stored once with `xcrun notarytool
store-credentials l2t-notary --apple-id … --team-id … --password …`; the
password must be an app-specific password, because every App Store Connect
account has 2FA. A `.zip` cannot be stapled: staple the app, then zip it
again. The hardened runtime is already on and already tested here, so the only
thing a paid certificate buys is Apple's signature on it.

## macOS first-run permissions

Two system prompts appear the first time you exercise the relevant parts:

- **Microphone**: requested from the Settings banner via AVFoundation. Click
  *Allow*; recording starts working in the same app session, with no full
  restart needed.
- **Accessibility and keyboard access**: global hotkeys and macOS auto-paste
  both rely on Accessibility trust for the `.app` bundle. The Settings tab
  surfaces the relevant banners and can trigger the system request flow. If
  macOS refuses to prompt, open *System Settings → Privacy & Security →
  Accessibility* and add the binary you launch.

Add **`Lazy to Text.app`** to the Accessibility list, not a Python
interpreter from the venv. The app has its own identity, which is what lets
the permissions persist across sessions. A build signed ad hoc, as the CI
installers are, is a new identity to macOS after every update, so the two
prompts come back; a build signed with a stable certificate keeps them.

## The Electron interface

The test and screenshot hooks (`L2T_SCREENSHOT`, `L2T_SELFTEST_*`,
`L2T_BACKEND_CMD`) act only when the app is started with `--l2t-selftest` on
its command line, and `L2T_DEV` only in an unpackaged app. Third-party
licences, the GPL ffmpeg notice included, are in `THIRD_PARTY_NOTICES.md` and
ship inside the app. The spec and plan are in `specs/010-electron-interface/`;
the removal of the Qt window is `specs/011-remove-qt-interface/`.

## Development

```bash
uv sync --frozen                               # production deps and dev tools
uv run pytest -n auto                          # full test suite, in parallel
cd desktop && npm run dev                      # launch from source
cd desktop && npm test                         # renderer and shell tests
uv run python scripts/check_translations.py    # every string has a Russian entry
uv run python scripts/generate_desktop_screenshots.py --help  # regenerate docs/screenshots from the packaged app
```

Tests live in `tests/`. Hardware and libraries are replaced with fakes, so the
suite does not touch the microphone, the network or any model: no test loads a
model. Run it in parallel with `uv run pytest -n auto` (pytest-xdist is a dev
dependency). Tests marked `timing` assert wall-clock budgets, so CI runs them
in a separate serial pass.

CI runs the suite on ubuntu, macOS and Windows runners. On Linux the suite runs
under `xvfb-run -a`, because `pynput` opens an X connection at import time.

## What has not been verified

- A full dictation on a live Mac, from the hotkey through the recording and
  the transcription to the paste. The Accessibility permission was not
  available on the test host.
- Model download and cancel with real downloads.
- Keyboard-only use and VoiceOver.
- The Windows and Linux installers beyond the start-up smoke run CI does.
- An upgrade from a machine that has the classic Qt install, end to end.

Two limits are known and standing. The model list holds 16 cards, and
sorting and filtering are what make it usable. There are no update checks,
so a new release is found by hand.

## Acknowledgements

- [onnx-asr](https://github.com/istupakov/onnx-asr): the universal ONNX
  loader that made the single-engine refactor possible.
- [OpenAI Whisper](https://github.com/openai/whisper): the underlying
  multilingual model, with ONNX exports by
  [onnx-community](https://huggingface.co/onnx-community).
- [GigaAM](https://github.com/salute-developers/GigaAM) (Sber): the
  Russian-specialised acoustic model.
- [T-One](https://huggingface.co/t-tech/T-one) (T-Tech): the Russian
  Conformer-CTC trained on 80k hours of speech.
- [Vosk](https://alphacephei.com/vosk/) (alphacephei): the lightweight
  Zipformer Russian models.
- [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) and
  [Canary v2](https://huggingface.co/nvidia/canary-1b-v2) (NVIDIA): the
  multilingual European-language engines.
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg): the bundled
  static ffmpeg.
- [Heroicons](https://heroicons.com) (Tailwind Labs): the microphone glyph of the app icon.
- [Inter](https://rsms.me/inter/) (Rasmus Andersson): the bundled UI font.
- UI direction borrowed from [Spokenly](https://spokenly.app/) (macOS).

## License

MIT, © Alexander Blinov. See [LICENSE](LICENSE).
