# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

One native product, built for two operating systems: Windows and macOS. The
visual language is shared (one stylesheet with fifteen colour tokens, in a
light and a dark variant), but the native expectations differ and the design
has to respect them. On macOS, Cocoa turns the actions into the system app
menu under the Apple logo (`Cmd+,` / `Cmd+Q` / About), the default hotkeys
differ (`Ctrl+F8` / `F9` / `F10` against `Ctrl+F2` / `F3` / `F6`, because macOS
reserves `Ctrl+F1..F7` for system navigation), and closing the window hides
the app to the menu bar. On Windows the same actions live in an ordinary top
menu, and the way to the tray goes through the Win32 API. The theme follows
the system appearance, and Settings → Appearance can force either one.

## Users

A public open-source product. The primary audience is the independent
visitor to the landing page on GitHub Pages and the reader of the repository
on Windows and macOS, who wants to dictate text into any active window
without sending audio to a cloud.

The job they are doing: keep the focus on a task (a letter, code, a chat, a
document) without switching to an editor and without typing by hand. The
secondary case is a one-off transcription of an audio or video file that
already exists.

The model line bets on Russian: GigaAM v3, T-One and Vosk RU are the core,
and Whisper, Parakeet and Canary carry the multilingual coverage. The
conclusion about a Russian-speaking core audience was drawn from the set of
models in the repository, and the owner has not confirmed it.

## Product Purpose

The app records the microphone on a global hotkey, transcribes the recording
locally through ONNX Runtime, and pastes the result into the window that had
the focus. A second tab transcribes files: by drag and drop or through
Browse, with WAV, FLAC, OGG, OPUS and AIFF decoded by `soundfile` and the
other containers (MP3, M4A, MP4, MOV, MKV, WebM and the rest) decoded by the
static `ffmpeg` shipped as a Python wheel.

Success for the user: the text appears where they work, from one key
combination, with no wait for a cloud answer and no subscription. Success for
the product: a visitor reaches the clone and the first run, and the first run
ends with a working transcription, from nothing, with no model installed
ahead of time.

## Positioning

The mechanism a neighbouring product cannot honestly copy: sixteen models of
different families go through the same `OnnxAsrBackend` over
[`onnx-asr`](https://github.com/istupakov/onnx-asr) and one ONNX Runtime.
There is no PyTorch, NeMo or CTranslate2 in the dependency tree, and the
dependency install that followed the single-engine refactor came down from
roughly 4 GB to 700 MB. That size is the same for Whisper, GigaAM, Parakeet,
Canary, T-One and Vosk.

The second difference is the accelerator first, with the CPU as a quiet
fallback. Windows raises `onnxruntime-gpu` with the CUDA provider, and macOS
uses `CoreMLExecutionProvider` on Apple silicon (Neural Engine, GPU and CPU
per operator). When the driver or the hardware is missing, or an operator
turns up in a model that the provider cannot take, the app repeats the
request on the CPU and shows the provider that is running in the pill. A
laptop without a discrete GPU stays working rather than broken.

The third is privacy as a consequence of the architecture rather than a
promise: the audio physically never leaves the machine, and the network is
needed only to download the models and, when post-processing with a cloud
provider is on, to send the text.

## Operating Context

- **Dictation by hotkey.** Start, stop and cancel on global combinations;
  stop starts the transcription and the auto-paste. The combinations are
  reassigned in Settings and validated before they are saved.
- **The first run.** Its own screen in three steps: choose a model, download
  it, press the hotkey. The recommended card comes first, the one the app
  measures as the right start, with a short explanation instead of a
  comparison table. The catalogue of every model sits next to it, behind a
  separate link, and a choice from it counts as a full one: it also ends
  with a working transcription. The screen closes for good when a model has
  arrived and loaded; if it is not on disk, it comes back, because there is
  nothing to dictate with yet. The weights come from Hugging Face and land
  in the HF cache, and the path can be changed in Settings → Storage. A
  download of a large model can be cancelled with the red pill, and the
  rollback returns the card, the config and the top-bar pill to their
  previous state without waiting for the download to finish.
- **File transcription.** A separate Transcribe tab takes a file by drag and
  drop or through Browse, and the decoding runs in its own process.
- **The tray and the window close.** The window minimises to the tray, and
  the tray icon carries the state (Idle / Recording / Processing). The full
  exit is `Cmd+Q` on macOS and an explicit Quit item in the menu; the
  destructive actions in the history ask for a confirmation first.
- **History.** Stored locally, up to 1000 entries, exported as plain text,
  opened in a dialog with the full text and a one-click copy.
- **macOS permissions.** Two system checks at startup: Accessibility
  (`AXIsProcessTrusted`), for the global hotkeys and the auto-paste, and
  Microphone (`AVCaptureDevice.authorizationStatus`). macOS will not show the
  system prompt on its own: a banner in Settings opens the right section of
  the system settings, and the "granted but a restart is needed" case has a
  banner of its own with a restart button inside the app.
- **Hardware.** Windows: a discrete NVIDIA is recommended for the large
  models, and there is an automatic CUDA install. macOS 12 and later on Apple
  silicon: CoreML picks the Neural Engine and the GPU by itself, and Intel
  Macs run on the CPU. Vosk RU, Whisper Base, GigaAM CTC and T-One run
  comfortably on the CPU on both platforms.
- **Feedback.** A popup in the bottom-right corner with a preview of the last
  transcription; Logs shows coloured output by level and by source, with a
  switch for the network lines and a search over the buffer.

## Capabilities and Constraints

Confirmed constraints that future work has to preserve:

- **One ONNX path.** Every model loads through `OnnxAsrBackend`. PyTorch,
  NeMo and CTranslate2 do not come back to the dependency tree: the short
  install time and the single provider scheme follow from that decision
  rather than from a side effect of it.
- **Local-first.** The audio never leaves the machine. Cloud recognition
  services, telemetry and analytics are not added. There is not one
  analytics SDK in the repository.
- **Windows and macOS as equal platforms.** Neither one turns into the
  "primary with concessions for the other". The top bar on macOS shows CPU
  and RAM, and on Windows it shows GPU and VRAM as well, which is a
  deliberate difference and not an unfinished part.

Technical constraints recorded in the code:

- The maximum recording length is 300 seconds (`config.yaml`).
- The data paths in a frozen build are set by `platformdirs`: on macOS
  `~/Library/{Application Support,Logs,Caches}/LazyToText`, on Windows
  `%APPDATA%`, `%LOCALAPPDATA%\Log` and `%LOCALAPPDATA%\Cache`.
- There are two frozen targets: the py2app bundle on macOS and the
  PyInstaller folder on Windows. The backend is chosen by branch: a frozen
  macOS build starts a `SubprocessBackend` and falls back to the in-process
  `RegistryBackend` when the worker does not come up, while Windows and a
  dev-mode macOS run use `SubprocessBackend`.
- `Ctrl+F1..F7` are not available for global hotkeys on macOS: the OS
  intercepts them before `pynput` sees them. The difference between the
  defaults on the two platforms follows from that.

Unresolved product questions, not derived from the code, and the owner's to
answer:

- **The distribution model for a public release.** The repository carries an
  MIT licence (`LICENSE`) and the path "clone, `uv sync`, run", along with
  the portable build scripts for macOS and Windows. Which of those channels
  counts as the official one for a public audience has not been confirmed.
- **Signing and notarization.** The macOS build is signed with a certificate
  installed locally (`scripts/setup-signing.sh`), and always with the
  hardened runtime and the microphone entitlement, which is exactly what
  Apple accepts for a notarization submission. One thing is missing: a
  Developer ID Application certificate, which the Apple Developer Program
  gives for $99 a year (with a fee waiver for nonprofits, educational
  institutions and government bodies). The notarization itself is free, and
  `notarytool` and `stapler` are already on the machine. Without a Developer
  ID, other people's Macs still ask for the right-click and then Open. The
  full sequence is in the README, in the *Notarizing the Mac build* section.
- **The landing page `docs/index.html`.** It exists and is published through
  GitHub Actions Pages, and it carries the same download sizes and the same
  model aliases as the README, so the two surfaces have to move together.
  Whether it counts as part of the same product is still an open question.
- **The accessibility standard.** No requirement has been recorded. See the
  section below.

## Brand Commitments

- **Name:** Lazy to Text. **Slogan:** "Press a hotkey, speak, paste.", in
  English, like the whole interface of the app.
- **Tone:** direct, without hype, engineering. The README and the landing
  page talk about sizes, providers and dependencies rather than about a
  revolution, and the careful wording of "quietly repeats on the CPU" is
  part of that voice rather than a softening of it.
- **Assets:** a squircle as the app icon, generated at build time by
  `scripts/generate_icns.py` from the same shape the interface paints, a set
  of tray icons in the Idle / Recording / Processing states, the start, stop
  and cancel sounds, and the bundled Inter font.
- **The visual code is already set and working:** a stylesheet with tokens,
  a light and a dark variant from one file (`app/gui/styles/base.qss`,
  substituted at load time), the family colours of the model badges,
  Heroicons in the sidebar, soft card shadows, smooth scrolling at the
  refresh rate of the monitor. It is an incumbent world rather than an empty
  canvas.

## Evidence on Hand

The real materials to lean on:

- `README.md`: a detailed description of the capabilities, of both
  platforms, of the build and of the macOS permissions.
- `docs/index.html` and `docs/style.css`: the existing landing page.
- `docs/screenshots/`: eight real screenshots of the interface in English
  (`hero.png`, `models.png`, `transcribe.png`, `history.png`, `logs.png`,
  `presets.png`, `shortcuts.png`, `narrow.png`) and the same eight in Russian
  under `docs/screenshots/ru/`. They are rendered from the code by
  `scripts/generate_screenshots.py`, so they are the visual truth about the
  current state.
- `app/model_mapping.py`: the registry, and the one copy of the measurement:
  the WER and RTF of every card, on the Golos test split, with the sample
  size and the confidence interval written down next to it.
- `app/assets/`: the tray icons in three states and the three sounds.
- `app/config_manager.py`: the defaults that are written into `config.yaml` on
  the first run: the model `gigaam-v3-ctc`, automatic language detection, 300
  seconds at most, auto-paste on, the tray on, and GPU monitoring on Windows
  only.
- `LICENSE`: MIT, © 2025 Alexander Blinov.
- The full test suite, 1485 passing tests at release 0.1.18, as evidence
  that the build works and not as a testimonial about the product's quality.

What the repository does not have, and what future work has no right to
invent: user reviews, install and download counts, third-party measurements
of speed and of transcription quality, comparative benchmarks against cloud
services, usage data (there is no telemetry by design), and screenshots of
the macOS states in the frozen bundle taken on real hardware.

## Product Principles

1. **The keyboard is the main interface.** Recording, stopping and cancelling
   live on global hotkeys, because the user is in somebody else's window.
   Any function that cannot be reached from the keyboard loses part of the
   case.
2. **The first run has to end in a result.** No preinstalled model and no
   required setting: choose a model, download it, one combination, and the
   text is in the window. Everything that adds a step before the first
   transcription costs more than any amount of polish.
3. **Privacy is kept, not discussed.** No new network calls with the audio.
   If a feature needs the internet, it should be the weight and the HTTP
   ping of the HF hub, and not the sending of the user's speech.
4. **The accelerator is a superset of the CPU, not a replacement.** A GPU
   that fails must not change the result of the work, only its speed. Every
   new provider has to come with a working fallback.
5. **Two operating systems, two honest implementations.** The differences
   between the platforms are shown plainly (resources, permissions, the
   hotkey defaults) rather than hidden behind a small badge in the
   signature.
6. **A promise has to be checkable.** The install size, the set of
   dependencies and the offline behaviour are facts that can be named and
   checked. A marketing phrase that the code cannot support does not go into
   the product.

## Accessibility & Inclusion

- **Hotkeys as the main way of working.** The product assumes the user
  cannot switch to our window with the mouse. The combinations are
  reassigned in Settings and validated before they are saved, so a conflict
  does not block the recording silently.
- **macOS Accessibility is a hard dependency, not a recommendation.** Without
  `AXIsProcessTrusted` there are neither global hotkeys nor an auto-paste.
  While the permission is missing, the interface has to explain that in
  Settings and offer the path to the system settings, instead of simply not
  working. The "granted but a restart is needed" case is a state of its own.
- **The accessibility standard is not fixed.** It is an open question. The
  known requirements for contrast, for target size and for screen readers
  are not confirmed by the owner and must not be invented in design work.
