# Changelog

All notable changes to Lazy to Text. Versions are ordered newest first.

Entries describe what changed and why something was worth changing — the
traps that cost a rebuild are recorded in [AGENTS.md](AGENTS.md), not here.
Release assets and their exact sizes are on the
[release page](https://github.com/aa-blinov/lazy-to-text/releases).

## Unreleased

### Fixed

- Transcribe screen: a "Speakers" field next to the box fixes the number of voices
  when you know it (empty means automatic), which corrects a voice split in two
  or two merged into one; changing it on a finished file offers "Transcribe again".
  The Copy and Save buttons sit at the right edge.
- Transcribe screen: the "Split by speakers" box can be ticked before a file is
  chosen and while one is running (it then applies to the next file, and the
  screen says so), and it is remembered between launches.
- A finished file can be cleared (asks first if the text was edited; clearing a
  running file cancels it), so the next one can be loaded.
- Ticking or unticking the box on a finished file offers "Transcribe again" with
  the new setting instead of doing nothing; the file line names the mode the
  text was made in.
- When the speaker model is not downloaded, the greyed box has a "Get the model"
  button to Models.

## 0.2.15 — 2026-10-29

### Fixed

- The microphone recorded silence when the saved microphone was only an index.
  Settings saved before 0.2.8 hold a position in the audio system's list, and a
  phone or headset that connects (an iPhone's Continuity microphone) takes a
  place in it, so position 0 could now be the phone. With several microphones
  and no saved name the app now uses the system default and says so, and
  choosing a microphone in Settings pins it by name. A silent recording now
  names the microphone it came from.
- The recording capsule was missing over full-screen apps that were already
  open. macOS forgot that the capsule window belonged to every Space once a
  full-screen Space it had been shown in was closed, and setting the same flags
  again did not bring that back. The window is now replaced by a fresh one after
  each appearance on macOS, which always starts on every Space.

## 0.2.14 — 2026-10-28

### Changed

- Microphone checks can be repeated without limit. Their result clears when leaving Settings and does not return when Settings is reopened.


## 0.2.13 — 2026-10-28

### Fixed

- Clean CI installs now accept the Svelte 4 peer range still published by the current Monos UI package while building this Svelte 5 application.

## 0.2.12 — 2026-10-28

### Fixed

- The entire top band can now drag the window on Windows and macOS, instead of only the strip above the sidebar.

### Changed

- Updated the Electron interface, model management and resource reporting; removed GPU and VRAM details from the interface.


### Added

- Every release carries `SHA256SUMS.txt` and a build attestation for each
  installer, so a download can be checked: `gh attestation verify <file> --repo
  aa-blinov/lazy-to-text` proves it was built from that tag by this repository's
  workflow. The release page now links an install guide.
- `docs/INSTALL.md` and `docs/INSTALL.ru.md`: why macOS (Gatekeeper), Windows
  (SmartScreen) and Linux (AppImage, `.deb`) show the messages they do, how to
  open the app on each, how to check a download, and why the installers are not
  signed with a paid certificate.

### Changed

- The README and the site no longer tell macOS users to right-click and choose
  Open: macOS 15 removed that, and the way is now System Settings, Privacy &
  Security, Open Anyway.

## 0.2.11 — 2026-10-28

### Fixed

- Windows push-to-talk now listens for the configured right-side key directly.
  The global-hotkey library treated the same right Alt/Ctrl/Shift key as an
  unrelated generic modifier and filtered out its press event.

## 0.2.10 — 2026-10-28

### Fixed

- Audio resampling no longer loads SciPy's native BLAS DLL during dictation.
  The shared NumPy polyphase filter preserves anti-aliasing and processes long
  recordings in bounded-memory chunks.

## 0.2.9 — 2026-10-28

### Fixed

- Audio preparation now logs its stages and emits the blocked worker's Python
  stack when it makes no progress for 30 seconds. A stalled preparation can be
  located in the next report instead of leaving no clue after microphone stop.
- Captured microphone chunks are detached under a lock before conversion, so a
  completed dictation releases the previous recording buffer while the app is
  idle. The callback uses the same lock to keep a stop at the duration limit
  from losing its last audio block.

## 0.2.8 — 2026-10-28

### Fixed

- "Could not start recording: Error opening InputStream: Internal PortAudio error
  [PaErrorCode -9986]" after a phone or headset microphone came or went. The
  audio system freezes its list of microphones when the app starts, so the saved
  index pointed at a device that was gone or had moved. The app now remembers the
  microphone by name, rebuilds the list and tries once more when an open fails,
  and uses the system default until the chosen microphone is back. Refresh in
  Settings, and opening Settings, rebuild the list too, so a microphone connected
  since the app started appears in it.

### Added

- Settings, Audio input: the start and end sounds are chosen as one pair. Seven
  sets, each made as a start and its counterpart of one family (a rising note and
  a falling one, two knocks up and two down, a drop that glides up and one that
  glides down), so the two never sound like they come from different places.
  Each cue also takes a WAV file of its own, on its own: only the start, only the
  end, or both. A play button for each, and a file that is replaced is deleted.

### Changed

- The default start and stop sounds are lower and lighter: a short rising and a
  short falling note around A4 and E5. The previous bells are the "Glass" set.

## 0.2.7 — 2026-10-28

### Fixed

- Stopping a long dictation no longer closes and resamples the microphone on
  the global hotkey callback. Shutdown and audio preparation run in a worker,
  keeping the app responsive while transcription begins.
- The Windows splash and main window title bars follow the app theme, including
  the native minimize, maximize and close buttons.
- The packaged Python runtime now includes `base_library.zip`; without it,
  PyInstaller's early `inspect` hook could fail to import `zipfile` before the
  runtime started.
- Runtime build smoke now checks that the spawned inference worker answers,
  not only that the parent server responds.
- A stalled RPC response body now reaches the same timeout as a stalled
  connection, so a partial response cannot leave the interface waiting forever.

## 0.2.6 — 2026-10-27

### Fixed

- On macOS the window could be taken only by the top of the sidebar. The strip
  at the top is now draggable across the whole width.
- After post-processing the capsule fell back to "Transcribing" for an instant
  before it said what was delivered.
- In Settings the rule under the section tabs ran from edge to edge while the
  one under the title was inset; both now sit in the same gutters.

### Changed

- The microphone level bar reads in decibels instead of raw amplitude. Ordinary
  speech used to light one segment of twelve; it now fills about half the bar,
  amber when loud and red close to clipping, and the empty segments are drawn
  as a visible track.
- The dictation always stays on the clipboard after an auto-paste, so it can be
  pasted again and survives a field that ignored the keystroke. The "Keep my
  clipboard" setting is gone: it put the previous text back, which is what made
  the clipboard look unused.
- The capsule sits one level above the screen-saver level, so a window another
  app keeps at that level cannot cover it.
- Separators in status text are commas instead of middle dots, and the
  runtime's messages use full stops and colons instead of em dashes.

## 0.2.5 — 2026-10-27

### Fixed

- On macOS a dictation could paste the previous clipboard text, or leave it for
  your own Cmd+V. With "Keep my clipboard" on, the old content was put back
  0.15 s after the paste keystroke, before a browser or Electron app had read
  the new text. It is now put back after 1.5 s, only when a paste was sent, and
  only if you have not copied something else meanwhile.
- The start sound was cut off when "Mute sounds while recording" was on: the
  output was muted before the cue had played. The mute now waits for the cue to
  end, and a stop that comes first cancels it.

### Changed

- Files, and the speaker diarization in front of them, run in a second worker
  process that starts at the first file, runs a little behind everything else
  and keeps to half of the cores. A dictation no longer waits for a file, and
  the window stays movable. The worker leaves after 90 s without work. If it
  cannot start, the file runs in the main worker as before.
- Processing shows its two waits: the capsule and the status strip say
  "Transcribing" and then "Post-processing", with both steps drawn when
  post-processing is on.
- New, softer start, stop and cancel sounds, drawn by `scripts/make_sounds.py`.

### Added

- A Cancel button for a file being transcribed. It ends the worker process,
  which is the only way to stop inference in native code.

## 0.2.4 — 2026-10-27

### Fixed

- Recording on macOS failed with `PaErrorCode -9986` after a rebuild under a new
  signing identity. The Microphone probe (AVFoundation) sat in an optional extra
  that no sync installed, so the runtime shipped without it: the permission
  status read unknown, the Settings banner never showed and the system prompt
  was never requested. It is now an ordinary macOS dependency.

### Added

- Speaker diarization for files. A "Split by speakers" box on Transcribe makes
  the transcript read Speaker 1, Speaker 2 and so on. The 34 MB ONNX model
  (pyannote segmentation and CAM++) is a card on Models, downloaded like the
  others; until then the box is greyed out and says why.

## 0.2.3 — 2026-10-26

### Changed

- Auto-paste is off by default. With it on, a fresh install on macOS had no
  Accessibility grant, the paste keystroke was dropped and nothing said why.
  Dictations now go to the clipboard, and turning auto-paste on asks for the
  grant at that moment (or opens the Accessibility pane when the system will
  not ask). A config that already stores `auto_paste: true` keeps it.

## 0.2.2 — 2026-10-25

### Fixed

- Auto-paste on macOS no longer reports "Paste sent" when the system will not
  deliver the keystrokes. After the application id changed in 0.2.1 the
  Accessibility grant was gone, both key paths still answered "sent", and the
  dictation vanished without a word. Now the keys are not posted, the text
  stays on the clipboard, the log names the missing grant, and the delivery
  says "copied". The Settings banner for the missing grant was already there.

## 0.2.1 — 2026-10-25

### Changed

- The application id is now `io.github.aa-blinov.lazytotext`. The earlier
  `ai.eora.lazytotext` came from a work domain and this is a personal project.
  Settings, history and models are not affected (they live under `LazyToText`).
  On macOS the Microphone and Accessibility grants belong to the id, so they are
  asked for once more, and a copy of 0.2.0 or of the classic app stays where it
  is until you delete it. The Windows installer removes the uninstall entry that
  0.2.0 left, when it sits in the folder the new install uses.

### Fixed

- The recording capsule could stay off the screen, most often over a
  full-screen app, leaving only the sound. While the capsule is wanted it is now
  brought back to the front every second, with the settings that let it float
  over full-screen apps applied again each time, instead of once when the window
  was made. This was not reproduced in a full-screen app here, so it is a
  defensive fix: the capsule did appear over a full-screen window in a stripped
  down test, and the cause in the real app is not confirmed.

### Added

- More providers for post-processing: Alibaba Cloud (Qwen), Anthropic (Claude),
  Cohere, DeepInfra, Fireworks AI, GitHub Models, Google Gemini, Hyperbolic,
  Moonshot (Kimi), Perplexity, SambaNova and Z.ai (GLM), and three local servers:
  Jan, llama.cpp and vLLM. The addresses are the services' published
  OpenAI-compatible bases and are editable.
- The provider picker is alphabetical, with the custom server last.

## 0.2.0 — 2026-10-24

The Qt interface is removed and the Electron interface is the only one. The
Windows CUDA build goes with it. The engine, the runtime and every
behaviour in baseline specs 001 to 009 are unchanged; the work is in
`specs/011-remove-qt-interface/`.

### Added

- A "Start when I log in" switch in Settings (off by default): the app starts
  hidden in the tray at login on macOS, Windows and Linux.
- Forced-colours (Windows high contrast) rules, an About entry on Windows and
  Linux, Cmd/Ctrl+F on the Logs screen, a link to the Hugging Face token page,
  and file associations for every format the engine reads (24 extensions).
- A file opened or dropped while the first-run screen is up now waits for the
  main window instead of transcribing behind it.

### Changed, for people coming from the classic app

- The Electron app now has the classic app's id (`ai.eora.lazytotext`), so a
  Windows install upgrades a classic one in place and the installer offers to
  remove an old classic install. Settings, history and models are the same
  files and carry over. The macOS Microphone and Accessibility grants do not
  reliably carry over: the dmg and zip on the release page are signed ad hoc
  by CI, which makes macOS treat every release as a new app and ask again.
  Only a build made on a machine with the self-signed identity from
  `scripts/setup-signing.sh` keeps its grants from one build to the next.
- The recording capsule sits at the bottom right of the screen, as it did in
  the classic app.

### Removed

- The Qt interface (`app/gui`), its translation catalogue, its entry point
  and the console scripts `lazy-to-text-ui` and `lazy-to-text-ui-cuda`.
- The Qt packaging chain: py2app, the Qt PyInstaller spec, the Inno Setup
  installer, the macOS and Windows build scripts and the bundle pruner.
- The CUDA build: the NVIDIA wheel installer at start-up, the `[cuda]` extra,
  the `LazyToText-CUDA` bundle. Inference runs on the CPU, and on CoreML on
  Apple silicon, through the stock `onnxruntime`. The GPU and VRAM readout in
  the status strip stays: it is monitoring only.
- `pyside6`, `pytest-qt` and `py2app` from the dependencies, and the Qt jobs
  from the release workflow.

### Changed

- `lazy-to-text-server` is a console script of the project: it starts the
  Python runtime on its own.
- The Russian catalogue is `desktop/renderer/src/i18n/*.json` and nothing
  else. `scripts/check_translations.py` fails when a renderer string or a
  Python `mark()` sentence has no Russian entry.
- `app/recording_factory.py` and `app/mic_check.py` moved out of `app/gui`;
  the Qt-free tests that lived under `tests/gui` are top-level files in
  `tests/`.
- One release job creates the GitHub release for a `v*` tag, with the
  changelog section as its body, and attaches the installers of all three
  platforms.
- `uv.lock` is regenerated without the Qt, py2app and NVIDIA packages.
- The version lives in `pyproject.toml`, `app/version.py`,
  `desktop/package.json` and its lock; there is no `setup.py`.

### Upgrading from the classic app

The Electron app has the same application id as the classic one. On Windows
the installer offers to remove a classic install. On macOS the downloadable
build is signed ad hoc and is not notarized, so the first launch needs a
right-click and **Open**, and macOS asks for Microphone and Accessibility
again after each install (a locally built, self-signed app keeps them). Settings, history and downloaded models
are shared and kept: the runtime reads the same folders. The two cannot run
at once, because they share one single-instance lock. Windows no longer has a
GPU build: it runs on the CPU.

### If you ran an Electron 0.1.x build

The 0.1.x Electron builds used the application id `ai.eora.lazytotext.desktop`;
0.2.0 uses `ai.eora.lazytotext`.

- **macOS** asks for Microphone and Accessibility once more, because the
  grants belong to the old id. The stale entry stays in System Settings,
  Privacy & Security until you remove it by hand.
- **Windows**: the old per-user install appears in Settings, Apps next to the
  new one (both use the same install folder, so the files are overwritten).
  The 0.2.0 installer tries to remove that entry's registry key after a
  successful install; if it is still listed, uninstall it from Settings. This
  installer step is untested on Windows.
- Settings, history and models are the same files and carry over.

## 0.1.24 — 2026-10-24

A pre-release QA pass over the Electron interface and the engine under it:
five testers filed about ninety defects, four developers fixed them in three
rounds, and independent retests checked each fix. The reports are in
`specs/010-electron-interface/qa/`.

### Fixed

- A dictation or a file longer than about 20 seconds failed with the small
  Vosk model and a live dictation was lost without a word. Audio is now cut
  at the quietest spot below each model's own limit, and a failed
  transcription always reports why instead of going silent.
- A failing language model no longer loses the dictation: any error in the
  post-processing step delivers the original text. The request has an overall
  deadline, never follows a redirect with the key, and never uses a proxy for
  a local address.
- Cancelling a model load left the app on "Loading" and a retry after a
  failed load never finished; both now end in a usable state. A dead
  inference worker is noticed and restarted instead of failing every
  dictation.
- Moving the models folder into itself deleted the downloaded models. The
  move is refused, and the copy is verified before anything is removed.
- The engine dying while the window is open is now shown, with a Restart
  button and automatic reconnection, instead of a window that looks alive.
- Passwords in a server address, API keys and the user's words no longer
  reach logs; the history file survives a damaged line; onnxruntime's
  telemetry is switched off; a saved microphone that no longer exists falls
  back to the default.
- A file opened from the OS at launch waited for nothing and was lost; it now
  waits for the model.
- Saving or exporting cannot overwrite an existing file unasked or write into
  the application's own folders, in any letter case.
- Kept recordings, the log and the history are readable by their owner only.
- Hotkeys that conflict with each other or with the system are refused and
  not saved; a refused change no longer reports "Saved".

### Changed

- The Electron window is served from its own scheme with a strict content
  policy, the Electron fuses are set, every bridge call checks who is calling,
  and the test hooks need an explicit flag.
- The loopback channel has a request deadline, sheds slow connections, takes
  the event stream's credential as a one-time ticket, refuses foreign origins
  and no longer sends API keys to the window.
- Error toasts expire, Cmd/Ctrl+1 to 6 move focus into the screen, a skip link
  was added, all screens share one content width, and more runtime messages are
  translated.
- The first-run steps use the whole row.
- `--data-dir` keeps config, log and history of a test run away from the real
  profile.

## 0.1.23 — 2026-10-24

### Fixed

- The global hotkeys did nothing in the Electron interface on macOS. The
  hotkey monitor there is an AppKit event monitor, which receives keys only
  while the process serves its event queue; Qt does that in the classic
  window and the headless runtime did not. It does now, and a regression test
  holds it. Found by pressing the real hotkey against the real runtime and
  watching a recording start, level, stop and be pasted.

### Added

- Tests for the Electron main process's native-dialog, shell and clipboard
  handlers, so what each one asks for and returns is pinned.

## 0.1.22 — 2026-10-24

### Added

- An Electron interface on the same engine: a window, a tray and a
  recording capsule over a headless Python runtime, with installers for
  Windows (installer and portable), macOS (dmg and zip, Apple Silicon only:
  the pinned onnxruntime has no wheel for Intel Macs) and Linux (AppImage
  and deb). Run it from source with
  `cd desktop && npm install && npm run dev`. It has its own app id, so it
  asks for the microphone and Accessibility permissions once on its own; it
  shares settings, history and models with the Qt app, and only one of the
  two can run at a time.
- A CI workflow that tests and builds the Electron interface on all three
  platforms, and a release step that attaches its installers to a tag.
- A new icon: the microphone the application has always had, on a tile of
  Monos paper in Gruvbox colours, with template glyphs for the macOS menu
  bar. `scripts/make_icons.py` draws every size.
- The project site and the screenshots are redone in the Monos style, and the
  screenshots are now taken from the packaged Electron app
  (`scripts/generate_desktop_screenshots.py`).
- Spec Kit for the project: a constitution, baseline specifications of what
  the application already does (`specs/001` to `009`), and the Electron
  interface as the first feature run through spec, plan and tasks.

### Changed

- The repository pins Python 3.12 in `.python-version`. The macOS bundle
  assumes it throughout, and a checkout whose environment had been created
  with 3.13 built a bundle whose inference worker could not start.
- Strings marked for translation no longer pull Qt into the headless
  runtime: `mark` moved to `app/translation_mark.py`.
- The worker-spawn workarounds for a frozen macOS app apply to py2app
  bundles only, so a PyInstaller build on macOS starts its inference
  worker the ordinary way.

## 0.1.21 — 2026-10-24

### Added

- Speed controls for the post-processing model: a reasoning-effort picker
  (provider default, off, minimal, low, medium, high), a cap on the reply
  length in tokens, and a timeout in seconds. A reasoning model can spend
  seconds thinking before it tidies one sentence; turning the effort down
  and capping the reply is how a dictation stops waiting for it. Each
  value is stored per preset and is left out of the request until it is
  set, so a server that does not know the field is never sent it.

### Changed

- The post-processing checkbox now lives in the language-model settings
  card instead of a card of its own.
- The "Several variants…" button is gone. The preset picker is always
  shown under the settings, and the name field with it.

## 0.1.20 — 2026-10-23

### Added

- A checkbox that mutes the system output while a recording is running, so
  music and notifications stay out of the microphone and do not compete with
  the dictation. macOS only — the mute is the system's own per-device
  mute, so the volume icon shows it and the state is the one macOS keeps.
  The output comes back when the recording stops, and a run that dies
  mid-recording is undone on the next launch.
- The result popup no longer moves to another screen while a dictation
  is being processed. The app used to look idle for a moment between
  the recording ending and the transcription starting, and the popup
  took that as its cue to hide and re-anchor itself — to the primary
  screen, if the cursor was not on one.
- The result popup no longer vanishes without a trace on macOS. The
  floating panel is now woken up with the app and put back on the
  space the user is looking at, and every appearance writes the
  window's state to the log, so the next time it goes missing says why
  instead of leaving a mystery.
- A checkbox that recognises the speech only and skips the silences, with
  the silero VAD. The recording is cut into its speech segments before it
  reaches the model, so the silences cost nothing. It works with every
  model, and the small VAD model is downloaded into the app's own cache the
  first time it is used — never in the middle of a dictation.

## 0.1.19 — 2026-10-22

### Fixed

- The microphone no longer wedges the app. On macOS, stopping a recording
  could deadlock inside the audio library: the microphone stayed held for the
  rest of the session, every dictation after the first one failed with "the
  microphone is still held by the previous recording", and quitting the app
  hung — the process stayed alive with no window and kept the single-instance
  lock, so every later launch was refused and the app looked launched but
  broken. The app now ships a patched build of that library, and it leaves
  immediately when a recording thread could not be stopped instead of hanging
  on the way out.

## 0.1.18 — 2026-10-16

### Fixed

- A stop that hangs no longer leaves the microphone held for the rest of the
  session. The recording thread is aborted when it has not finished within two
  seconds, and where it was blocked is written to the log. If the microphone
  still cannot be freed, the app says so and asks for a restart instead of
  recording nothing.
- The result popup no longer breaks when the screen it is anchored to goes
  away. It falls back to the current screen, so it hides on time.

## 0.1.17 — 2026-10-16

### Fixed

- The seconds on the first-run download line no longer blink. A progress
  update re-rendered the line without them, and they came back only with the
  next tick. The count now stays on the line for the whole download.
- The model pill in the top bar no longer jumps when the loading counter gains
  a digit (9 s to 10 s). Its width is held for the widest counter while a model
  loads, and the text inside it is the only thing that moves.

## 0.1.16 — 2026-10-15

### Changed

- A dictation's result is one popup. The recording capsule now shows what
  happened to the text as its title, with the text itself on the line under
  it, in the bottom-right corner. It sits on the same backing and at the same
  height as the recording states. The in-window toast and its separate banner
  are gone, so a dictation no longer raises two popups.
- The capsule changes in place. The result has no entrance animation of its
  own; the toast's rise and fade went with the toast.
- The title of a copied result names the paste shortcut, "Copied — press
  Cmd+V", so the text can sit on the line below it.

### Fixed

- A result popup could run past the right edge of the screen. Its width was
  read from the layout before the new text had settled, so a long transcript
  left the popup off-screen. The width now comes from the text at once, the
  transcript is cut to what the screen leaves room for (the whole text stays
  in History), and the popup is placed again whenever its size changes.

## 0.1.15 — 2026-10-15

### Changed

- The recording capsule and the transcription preview share one corner: the
  bottom-right of the screen. The capsule moved from the top centre down to
  that corner, and the preview stacks just above it.
- The preview banner sits on the same backing as the capsule and has the same
  height, both as a separate window and inside the open window.

### Fixed

- The separate preview banner had no backing: its text sat on the desktop when
  the main window was minimised to the Dock or hidden to the tray.
- A floating message could be placed a few pixels too low on its first
  appearance, because its size was measured before the stylesheet applied.

## 0.1.14 — 2026-10-15

### Changed

- The banner that confirms a finished transcription and shows a preview of the
  text now appears on its own when the main window cannot be seen: minimised to
  the Dock, hidden to the tray, or behind another app. Before, it was drawn
  inside the main window, so in those states it never reached the user. While
  the window is open and in front, the banner still appears inside the window.

## 0.1.13 — 2026-10-15

### Changed

- After a paste, the line under "Paste sent" reads "Copied to clipboard"
  (Russian: "Скопировано в буфер обмена"). It replaces the warning that the
  keystroke could not be confirmed. The text is on the clipboard either way,
  so that is the only thing the line says.

### Fixed

- On the icons-only sidebar, each icon sits in the middle of its pill. On
  macOS the glyph sat off-centre, so the outline around the selected icon
  looked uneven.

## 0.1.12 — 2026-10-14

### Changed

- The interface texts are rewritten in plainer language, and the Russian
  translations follow. Fewer dashes, shorter sentences, and no claim the app
  cannot back up.
- Post-processing no longer says "This Mac". The local providers are labelled
  "Ollama (this computer)" and "LM Studio (this computer)", because the app
  runs the same way on Windows and macOS.
- The first-run text no longer says "no cloud". Speech never leaves the
  computer. Post-processing can send the text to a cloud provider, and the
  screen says so.
- The Vosk Small card no longer calls itself the most accurate card. It is
  close to the top on accuracy and the fastest card in the catalogue.
- The README and the landing page were rewritten. The README has a
  Post-processing section, and the screenshots were regenerated.

### Fixed

- Resizing the window on the Models screen was slow. Each description was cut
  twice per resize step, and each cut measured every word. A description is
  now cut once per width change, and the line breaks are found by bisection.
  The result is the same.
- The Vosk Small card said it was "a download smaller than a screenshot". It
  is 30 MB, so the comparison was wrong.

## 0.1.11 — 2026-10-14

### Fixed

- No change to the application. The 0.1.10 tag pointed at a commit whose
  Linux test job failed on one check in the test suite: the catalogue card's
  description check collapsed whitespace on one side only. This release is the
  same application with that check fixed.

## 0.1.10 — 2026-10-14

### Changed

- Narrow windows: the window floor is now 900 by 600. Below 1000 px the
  sidebar shows icons only, centred on the selected item, and no longer
  scrolls sideways.
- Models: a language filter (Russian, English, multilingual) sits beside
  the search and sort. The search field takes the spare toolbar width.
- `docs/STATUS.md` records what is done, what was verified and what is
  still open.
- README: a section on optional post-processing. The user-facing docs did
  not describe it before.

### Fixed

- Post-processing with OpenAI-compatible services no longer sends
  `temperature: 0`. Reasoning-family models such as the gpt-5 line, which
  the Model field names as its example, are reported to reject any value
  but their default. With such a model every dictation fell back to the
  raw text.
- The prompts no longer contradict themselves. "Make concise" told the
  model to drop repetition while the shared rules keep the speaker's
  emphasis; the shared rules now yield to a request to shorten. The em
  dash rule no longer reaches inside a word, so что-то and Wi-Fi keep
  their hyphens. "Formal prose" forbids a salutation and a sign-off in its
  own prompt, as its card already promised, and no longer invites a
  letter. "Make concise" calls its prompt a version rather than a summary.

## 0.1.9 — 2026-10-14

### Fixed

- The paste-shortcut line in the delivery overlay ("Press Cmd+V in your app")
  now follows the language. It was always English before.

## 0.1.8 — 2026-10-14

### Changed

- **Post-processing is simpler.** The screen opens with the on/off switch
  and one model card. Several saved variants sit behind a "Several
  variants…" link. The transcribe preset choice appears only when there is
  more than one variant.
- **Usability fixes across the screens.** Model cards explain WER, RTF,
  size and VRAM on hover, and the catalogue can be sorted by accuracy or
  size. Long model descriptions fold to three lines with a show-more link.
  The default-variant button and Delete say why they are unavailable.
  Settings has jump links to its sections.
- **Minimum window size is 1100×680**, so Russian labels fit at a 1.75
  text scale.

### Fixed

- Preset button text no longer gets cut at a larger text scale.
- Tooltips, accessible names and the post-processing title follow a live
  language switch.

## 0.1.7 — 2026-10-14

### Added

- **Russian and English interface.** Settings → Appearance → Language
  switches the whole app at once, with no restart. Every screen, tray
  item, dialog and overlay message is translated, and the choice is
  remembered.

### Changed

- **Post-processing is its own screen.** The Presets screen is now
  Post-processing: the switch that turns rewriting on and off lives at
  its top, next to the presets it chooses between. The Settings card
  that repeated it is gone.
- **New app icon in the DESIGN.md palette.** A flat sage squircle with a
  dark microphone, no gradient. The tray icons for idle, recording and
  processing are redrawn in the same palette.

### Fixed

- The size of a model download no longer disappears on the first tick
  of the elapsed counter, and the counter runs on the real clock.
- Tooltips and placeholders that carry a value (for example "Show only
  Whisper models") now follow a language switch.
- The overlay's fullscreen-window behaviour failure goes to the app log
  instead of a temp file.

All notable changes to Lazy to Text. Versions are ordered newest first.

Entries describe what changed and why something was worth changing — the
traps that cost a rebuild are recorded in [AGENTS.md](AGENTS.md), not here.
Release assets and their exact sizes are on the
[release page](https://github.com/aa-blinov/lazy-to-text/releases).

## 0.1.6 — 2026-10-14

The model card now leads with the numbers the choice is actually made
from, instead of burying them in the first clause of a paragraph.

### Added

- **A light theme, and the app follows the system by default.** Settings
  → Appearance → Theme, with "Follow the system" first. The two
  palettes are the same fifteen colour tokens with different values and
  a single shared stylesheet, so there is nothing to drift out of step.

  Thirteen of the fifteen light values are canonical Gruvbox swatches,
  taken as published — the ground, the four-step surface ladder, the
  text ramp and the state colours are the palette's own light rows, not
  hand-picked approximations of them. The two that are not, could not
  be. Only five chromatic swatches clear 4.5:1 as ink on the cream
  ground, and there is no green and no yellow among them, so the success
  and warning colours are darkened from the swatches that are two steps
  too light. A search over every assignment of the sixteen swatches
  confirms it: relax the requirement that the state colours be
  chromatic and you get six solutions, every one of them a palette
  where success, warning, danger and the accent are all the same
  near-black.

- **The accent went from a cold saturated blue to a warm orange**, and the
  reason is worth stating because it is not the reason you would guess.
  The blue was never low-contrast: the icon sits on it at 5.82:1 and it
  sits on the sidebar at 5.25:1. It read wrong because a cold, fully
  saturated colour dropped onto a warm desaturated cream ground reads
  as a foreign object rather than as part of the palette. Temperature is
  the only lever available — in an inverted theme the icon-on-fill ratio
  and the fill-on-rail ratio are the same number, so there is no
  lightness or chroma to spend without taking the icon under AA.
  `faded_orange` is the swatch that survives both ratios.

- **The CPU and RAM bars followed the wrong theme.** On the light theme
  they were painted with the dark palette's colours: a near-black track
  on a cream window, and fills in the dark theme's green and amber. The
  recording level meter, the log screen's text colours and the Dock
  icon's gradient had the same fault.

  The cause is the theme swap itself. `TOKENS.colors` keeps its identity
  when the theme changes and only its contents are replaced, so holding
  the dictionary is safe and copying its values is not — and these took
  copies at import time, which is always the dark palette.

  Nothing caught it because nothing had ever painted one of those
  widgets and then asked what colour came out. The existing tests
  compare colours against each other, so a frozen constant agrees with
  itself under either theme. The new check switches themes, grabs the
  widget and reads the pixels.

- **Presets: named bundles of post-processing settings, on their own
  screen.** Editing provider, endpoint, model, credential and mode is
  five fields that always change together, which is a form rather than
  a setting. A preset is that bundle under a name — "Work", "Letters"
  — with a prompt of your own inside it, so the thing you switch
  between is the whole answer rather than one field of it.

  Presets lives in the sidebar, next to Models and Transcribe, and it is
  the **only** place those five fields are edited. Settings keeps the
  switch and one line naming what is in use, with a button that goes
  here. That is the whole design of the feature and it took two goes:
  the first version left the five fields in Settings as well, and a user
  who met both editors needs a word to tell them apart — which is where
  the question "what even is a profile" came from. One editor and the
  question does not arise.

  Not called "profile": that word comes from accounts and logins, where
  a profile is a person, and here there are usually two and none of them
  is anybody.

  **Transcribe carries the picker.** Choose a preset there and it runs
  for that dictation only; untick and the default comes back. The
  override is held on the state manager and read at dictation time, not
  written to the config — an override that persisted would change every
  later dictation while the label said it was for one.

  Two things deliberately do *not* vary per preset. Whether
  post-processing runs at all stays the app's switch in Settings,
  because two presets disagreeing about it is a setting with no
  answer. And a preset's own prompt still gets the shared rules
  appended — numerals as digits, language preserved — because the line
  under the picker promises those two to every reader, and dropping
  them when you typed your own wording would make that line a lie
  exactly when somebody was paying attention.

  **The first preset appears by itself.** On launch the settings you
  already have are shown as one named preset, so the screen opens
  on your own configuration instead of an empty list with a paragraph
  explaining the concept. Asking somebody to press New to see what they
  already have is backwards — and the paragraph was the tell: an
  interface explaining itself is an interface that has not made itself
  clear. **New** now means a second one.

  **Nothing migrates.** A config with no `profiles` key resolves to one
  implicit preset built from the flat keys it already has, so an
  existing install loads unchanged.

  Presets carry their own credentials, which exposed a hole worth
  naming: the settings change log redacts by section and key, so
  `llm.api_key` was covered and `llm.profiles` — a list of dicts — was
  not. Saving a preset wrote every credential in every preset into
  `app.log` in plain text, through a plain `repr`. Redaction now also
  walks the value, so a credential nested at any depth is covered
  rather than the next one needing a tuple.

  46 new tests across the model, the screen, the picker and the
  controller, and the thirteen that moved with the fields rather than
  being deleted. Mutations P1–P14 all killed; two are worth naming because
  the tests could not kill them at first. P13 turned a Settings edit
  into a no-op whenever `active_profile` was still empty — which is the
  state every install is in until a second profile is added. P12's
  mirror wrote a one-element list containing only the edited profile,
  so with two profiles a single field edit in Settings deleted the
  other profile and its key; the one-profile test beside it passed the
  whole time.

- **Optional text post-processing, between the recogniser and the
  clipboard.** Off by default. Settings → Post-processing picks which
  service runs the model and what it does with the words (clean up,
  make concise, formal prose). The speech is still recognised on this
  machine either way; with a cloud provider the *words* it produced are
  what leave.

  The picker names the services rather than offering a "Cloud API"
  that left the reader to remember an endpoint: Ollama and LM Studio on
  this machine, then OpenAI, OpenRouter, Groq, DeepSeek, Together AI,
  Mistral, xAI, Cerebras and NVIDIA NIM, and "Custom OpenAI-compatible
  server…" at the bottom for the self-hosted vLLM that no list can
  enumerate. Choosing one fills the address; the wire format follows
  the choice, so a preset cannot leave the request pointed at a path
  the service does not serve.

  One control per decision, which is why the mode picker has three
  entries and not four. The checkbox is the switch; the picker answers
  "what does it do". A fourth entry reading "Off" meant nothing — with
  the checkbox on it stored `mode: clean`, sent the clean-up prompt,
  and printed "Off: dictated text is pasted exactly as recognised"
  underneath. The text was being rewritten against a line saying it
  was not, and the choice did not survive a restart either.

  The Model field suggests `qwen3:8b, or gpt-5.4-mini` — one name of
  each shape, since an Ollama tag and a cloud model id are not the same
  kind of string and one example cannot cover both. Both were checked
  rather than remembered, and the pair they replace had quietly aged out
  of both ends: Qwen 3 has displaced Qwen 2.5 as the safe local
  default, and OpenAI lists `gpt-5-mini` as deprecated in its own docs.
  A placeholder is an example somebody types, so a stale one teaches a
  stale name.

  **The prompts carry shared house rules, and the house rules name the
  two ways this step breaks invisibly.** Language and numerals are the
  pair that produce output which looks fine and is wrong: an English
  answer to a Russian dictation, and "сорок два" left as words in a
  document that wanted a digit.

  - **Language is stated positively, and names its own trap.** The
    wording was `never translate` and `Stay in the original language` —
    a prohibition, written in English, about an input that is usually
    not English. A prohibition does not say what to write instead, and
    the language of the instructions is a far stronger prior than the
    language of a prohibition. It now says *answer in the language the
    dictation is in*, and then says why: these instructions are in
    English, and that is not a reason to answer in English.
  - **Numbers are written as digits** — quantities, dates, amounts,
    ordinals, measurements, phone and account numbers — with the
    Russian cases worked, since Russian dictation is what this app is
    for. This is the same concern the model card already raises from
    the other end: spoken numbers are where the recogniser is weakest,
    and this is the step that can fix them before the text reaches a
    document.
  - **"Repeated words" no longer means "delete repeated words".** The
    old phrasing would remove "очень-очень хорошо" along with the
    stumble. The rule now separates the accidental from the chosen.
  - Typographic marks (em dash, the language's quotation marks, the
    ellipsis character) and a flat ban on markdown, because a model
    adds bold and bullets by reflex and neither belongs in a paste.

  Held in one constant rather than copied into three prompts: a rule
  written into one prompt is a rule the other two quietly lack, and the
  modes differ in what they do with the words, not in how careful they
  are about them. Costed: the prompts went from ~450 to ~1200–1400
  characters, so roughly 110 to ~330 tokens of prefill on every
  dictation. That is the price of the rules, and it is paid on each
  call — the trade is deliberate rather than unnoticed.

  **The card then had to say the same things, and said three of them
  wrong.** A mode's description, the line under the picker, and the
  prompt sent to the model are three separate strings about one
  transformation, and nothing held them together. `Formal letter`
  promised a letter the prompt is forbidden to produce — the prompt says
  *do not add anything the speaker did not say*, so no salutation and no
  sign-off can come out of it, and the promise and the prompt could not
  both be satisfied. `Make concise` called itself *a short summary* while
  its prompt kept every fact and kept hedged things hedged; a summary is
  allowed to drop, and the label was asking for exactly what the prompt
  forbade. It is `Formal prose` now, and leads with *the same facts in
  fewer words*.

  The numeral rule needed the same care twice. `сорок два` arriving as
  `42` is the most visible thing this step does, and no description
  mentioned it. The first fix put it in Clean up's line — which is the
  old mistake again: a rule written into one description is a rule the
  other two quietly lack, and a user reading Make concise's line cannot
  tell that it rewrites numbers too. It sits in one shared line under the
  picker instead, beside `_HOUSE_RULES`, which is the same two facts the
  shared rules are. The description says what the mode does; the shared
  line says what always happens. A test bans the word "digit" from every
  description so the rule cannot drift back into one of them.

  The shared line also answers the question every user has before
  pointing a cloud model at their own dictation: **no mode translates**.
  That is a decision rather than an accident — the module docstring is
  an argument about why a translation mode was left out — and a
  docstring is not something a user reads.

  Mutations N1–N8 all killed. N8 is the one worth naming: a first version
  of the drift test compared descriptions against the shared line
  verbatim, and the subtler mutation — pasting "Numbers become digits"
  into Clean up alone — walked straight through it. The ban is on the
  claim, not on the sentence.

  Two decisions worth stating, because both cost something:

  - **A failure delivers the raw dictation and says so.** Not "the
    dictation is lost", and not "silently deliver untidied text" — the
    second is the price of the first, paid loudly at warning level
    rather than quietly. In a dictation tool the contract is "your
    words reach the window", and no optional feature gets to break it.
  - **`urllib.request`, not `httpx`.** `httpx` is installed, but only
    transitively, via `huggingface_hub`. This repo has already had the
    opposite argument: `requests` sat in `pyproject.toml` declared but
    imported by nothing, shipped into the bundle, and invited
    contributors to assume it was part of the app. Depending on a
    transitive copy is the same mistake pointed the other way.

  Both questions the card asks — is an API key wanted, are the words
  leaving — are answered by where the *address* points, not by which
  entry is highlighted. LM Studio on this machine and OpenRouter speak
  the same dialect and differ in exactly the one way that matters, and
  a self-typed address can be either. So a loopback endpoint takes no
  key: leaving the field active for one invites pasting a credential
  into a box that is never read and never sent, which is how a secret
  ends up stored in `config.yaml` on a machine that has no business
  holding one. And a remote endpoint says in the card that the
  dictation is uploaded, because "Local-first" is in the window title
  and that makes it untrue for whoever picks it.

- **WER and RTF on the model card, as numbers.** `WER 7.1% · RTF 0.018 ·
  260 MB · 2.0 GB VRAM` sits directly under the title. Both figures used
  to reach the reader only as prose inside the description, in the same
  weight and colour as the rest of the sentence, while size and VRAM —
  which the registry already held as fields — had a laid-out line of
  their own. Comparing two models meant reading two paragraphs.
- **`MEASURED` moved out of the test module into `app/model_mapping.py`.**
  It was written down once and enforced correctly — but it lived in
  `tests/`, which meant the app could not reach its own measurements.
  The tests still import it and still fail when a card, the README or
  the landing page drifts from it; the registry now owns the number.

### Changed

- **The recording capsule shows over full-screen apps again, and the app
  has a Dock icon.** The Dock icon is there while the main window is open
  and goes away during dictation, so the capsule can float above another
  app's full-screen window. The capsule is a non-activating panel that
  re-orders itself when the active Space changes. Its corners are the
  same 12 px as the app's primary surfaces.
- **The app icon's body is the 824 of 1024 px Apple grid**, not a size
  picked by eye against the neighbours in the Dock.
- **The test suite runs in parallel in CI** (`pytest-xdist`, `-n auto`),
  so a full run is a fraction of the serial time.

- **The window remembers where it was.** Size and position are stored per
  user and restored on the next launch, on both the tray path and a real
  quit. A window minimised at close time is not saved — a minimised
  window's frame is not where it pops back up to, and the damage only
  shows on the *next* launch, long after anyone connects it to the click
  they made here.
- **The Window menu.** Minimize and Zoom, which until now existed only as
  the yellow traffic light, plus every screen with its `Ctrl+N`
  accelerator. The keys already worked and were invisible; a shortcut
  nobody can find is the same as one that does not exist. The menu is
  now the *only* owner of those bindings — it used to be a parallel list
  of `QShortcut` as well, and two `ApplicationShortcut` bindings on one
  key is something Qt resolves by firing both or neither.
- **The app can be opened with a file.** Double-click in Finder, "Open
  With", or a drag onto the Dock icon, on nine audio and video types.
  This was the largest single gap in the app's behaviour: for a program
  whose entire job is turning a file into text, the only way in was
  dragging it onto the window.
- **Spacing comes off the token scale, and every card agrees on it.**
  Every gap was written as a bare number, and two of them were on no
  step of the five-step scale: 10 and 14, each sitting between two
  steps, which is the thing a scale exists to decide. The one that
  mattered most was `10` in `_make_section_card` — the vertical gap
  between rows of *every* settings-shaped screen in the app, chosen by
  nobody and inherited by everything. Page rhythms now take the step
  above whatever they separate: 16 on the card-heavy screens, 12 on the
  list screens.

  Two of the seven section cards on Settings are built by hand rather
  than through that helper — Storage and Hugging Face, on that same
  screen — so fixing the shared helper alone left them visibly tighter
  than their neighbours a scroll away. Gaps *inside* a row, between a
  caption and its field, stay at 10: that is the right distance for a
  pair, and those rows have a documented 2px of slack at the narrowest
  card width on Windows at text scale 1.75.

### Fixed

- **The Logs toolbar collided with itself.** "Show network logs" ended at
  x=1940 and the "Clear logs" button's border began at x=1942 — a 1 px gap
  where the row's 8 px was declared, so the button sat against the label's
  last letter. History's equivalent gaps measure ~8.5, which is what this
  row was meant to look like.

  Same cause and same fix as the preset picker below: a stylesheet-styled
  `QCheckBox` next to another widget in a `QHBoxLayout` loses that layout's
  spacing on macOS. The toggle now sits in a plain, unstyled holder and
  gets its spacing back.

  Every checkbox in the app was then measured against the widget on its
  right: this one and the preset strip's were the only two short of their
  layout's spacing, and the other four sit alone in their rows.

- **The preset picker sat on its own label.** The "Use this one instead"
  checkbox and the profile dropdown had no gap between them: the combo's
  border ran into the last letter of the label. Measured on macOS, the
  layout placed the combo one pixel *before* the checkbox's cell ended, so
  its own 8 px spacing never appeared — at every window width from 1200 to
  360 and in both themes.

  A layout applies its spacing to a plain widget and then, on cocoa, skips
  it for a stylesheet-styled checkbox. The same host with a label or a
  button in the checkbox's place measures a clean 8 px, so it is the
  styled checkbox specifically — not the width, not the theme, not the
  amount of text. The checkbox now sits in a plain, unstyled holder and
  gets its 8 px back.

  Two plausible alternatives were rendered and changed nothing: moving the
  checkbox's 10 px from `spacing` to the indicator's `margin-right`, and
  raising the layout's spacing — the latter only widens the cell the
  checkbox gets, and the combo moves with it.

  The defect does not exist on the offscreen platform, so the offscreen
  suite is blind to it by construction. The tests therefore pin the tree —
  the holder, and that it contributes no margin of its own — because a
  geometry assertion alone would stay green through a revert.

- **The sidebar icons were drawn at half the screen's resolution.** The
  nav glyphs were rasterised into a 20×20 pixmap and then stretched across
  the 40 physical pixels a 20 px icon occupies on a Retina display, so the
  1.6 px Heroicons strokes came out soft with a grey halo. They are now
  rasterised at the screen's device pixel ratio and scaled down into the
  slot: the same glyph at the same size on screen, with 2.9× fewer
  mid-tone pixels in the icon column.

  The pixmap stays *untagged*, which is the whole trick. Tagging it with
  `setDevicePixelRatio` is the obvious companion move and it renders wrong:
  a tagged 40×40 dpr-2 pixmap comes back from `QIcon::pixmap(iconSize)` at
  40×40, and the list delegate draws it into the 20 px slot at full device
  size — every glyph clipped to its top-left corner. Qt's item delegate
  does not honour the tag on the whole-pixmap draw path.

  Handing `QIcon` the resolved SVG instead renders natively per-dpr, but
  needs the file written to the cache first and came out byte-identical to
  just oversizing the pixmap, so it buys nothing and a frozen bundle would
  be asking for a writable cache for no gain.

- **A dropdown looked like a frame inside a frame.** The popup draws one
  rounded 8 px frame; the selected row was an accent rectangle held 8 px
  inside it with square corners, and the pair read as two nested frames.
  The row is now full-bleed, so the frame's own radius clips it and the
  popup is one shape with one filled region.

  There was no rounding fix available. Qt paints that row as a plain
  rectangle — `border-radius` on a combobox popup item is not honoured,
  measured on macOS with the highlight's left edge at x=10 on every row
  including its first and last — so the panel's padding is the only lever,
  and the labels keep their inset regardless because macOS reserves the
  check-icon column.

  Two measurements of this one line were taken on the offscreen platform
  and had to be thrown away: there the item rules do nothing at all, which
  reads as "Qt ignores this selector" and is only true of a platform
  nobody ships on.

- **`QFileOpenEvent.file()` is not a list.** It is documented to return a
  `QStringList` and returns a plain `str` on PySide6 6.11.0 — measured
  across all three constructors. The idiomatic `for path in event.file()`
  therefore walks the string character by character, emitting `"/"`,
  `"U"`, `"s"`…: one single-letter "path" per character of the real
  filename. Nothing raises; every request is reported to the user as a
  file that does not exist. Constructed from a URL it returns the *URL*
  rather than a path, which is a second shape the same code gets wrong.
- **A window restored onto a monitor that is no longer there is now
  centred instead of stranded.** Geometry alone bakes in an absolute
  position, so a window saved on a second display and restored after it
  was unplugged came back at coordinates nobody could reach — worse
  than forgetting the position, because it cannot be got back. The
  screen name is stored alongside the geometry and checked on the way
  back in.
- **Cueing a window back to the centre actually resizes it.** The old
  path clamped a local `QRect` and then called `move()`, which positions
  a window and leaves its size alone — so the clamp was discarded and
  the window kept the width that does not fit. Measured on an 800px
  screen: a 904px window came back at `QRect(-52, 88, 904, 624)`,
  clamped in appearance only.

### Changed

- **The speed adjective is gone from the card.** 13 of the 16 shipped
  models said "fast", so the word distinguished nothing while borrowing
  `success` — the token that marks the Active state. It had survived a
  review on a stated reason, *"the reader's first question is is-it-quick
  and the number itself is not in the description"*; RTF on the metric
  line is that number, and the premise the word rested on expired with
  it.
- **The metric line sits above the description**, not below it.
- **Transcribe no longer mentions dictation at all.** The empty state
  carried a `Ctrl+F8` cap and the sentence "The key below dictates into
  your focused window" — a key that cannot put text on that screen, and
  an explanation of where its text *does* go. This view is fed by file
  drops alone (`set_result` is only reached through the
  `current_file() == path` guard in `_TranscribeMixin`), so the honest
  answer to "no transcript yet" here is a file, not a hotkey. History
  keeps its cap, because a dictation is what lands there.
- **Browse is offered once instead of three times.** It was on the header
  button, in the drop zone ("or click Browse") and again in the empty
  state ("or pick one with Browse") — three invitations to one action on
  a screen whose only action is Browse.
- **The format count left the drop hint.** "Audio, lossless and video
  containers — 24 of them" answered a question nobody asked: the user
  has one file. The count was correct; the full extension list is still
  one hover away.
- **No em dash in the model cards.** All sixteen descriptions carried
  one, and all sixteen were rewritten. The punctuation was doing real
  work — it attached an aside to a model name ("Sber GigaAM v3 with
  CTC decoder — the default") or set one off inside a sentence ("the
  most accurate card here and the fastest — from a download smaller
  than a screenshot") — so this was an edit rather than a find-replace:
  a comma appositive, a colon, or a full stop carries the same meaning.
  No measured figure moved: 135 numeric tokens in, 135 out, diff empty.
  `test_no_model_card_copy_carries_an_em_dash` holds the line across
  the whole catalogue. It deliberately asserts nothing about the two
  spaces after a full stop, which is a separate convention.

  The Models page subtitle went with them ("slower to load — the app's
  own starting point is first"), since leaving one em dash on the
  screen directly above sixteen descriptions without them would read
  as an oversight rather than as a decision. The rest of the UI is
  untouched: its em dashes are either log lines or placeholder
  glyphs, where `"WER —"` means "no value" and is not punctuation at
  all.
- **The rest of that line went too.** What the count left behind was
  "Audio, lossless and video containers" — the same three-item list,
  still not describing the three buckets it appeared to name. "lossless"
  is not a container, and `.wav` / `.flac` / `.aiff` are already audio.
  It also restated the prompt one line above it. The drop zone now
  prints five concrete names — `MP3, WAV, M4A, MP4, MKV` — which answers
  the question people actually bring to a drop zone ("will *my* file
  work?") in a way a count never could. Each name is pinned against
  `_AUDIO_EXTS` by a test, because a hint that promises a rejected
  format is believed until it refuses the file.
- **The two Settings reset buttons name their own scope** — "Reset
  hotkeys" and "Reset storage". Both read "Reset to defaults" and
  both are visible at the same scroll position; the accessible names
  had always distinguished them, so this only brings the visible labels
  up to what the names already said. The storage button was first
  shipped as "Reset storage folder", which measured 36px wider at text
  scale 1.75 and pushed the card past the window floor on Windows CI.
  "Reset storage" is 31px narrower than the "Reset to defaults" it
  replaced, and the accessible name still carries the full form.
- **"Clear token" is disabled until a token exists.** It is the one
  control on the Settings page whose click loses something, and it wore
  the `danger` role while pointing at a field that is empty by default —
  the state the app actually starts in.

### Fixed

- **Settings labels were flush right on macOS and flush left
  everywhere else.** `QFormLayout`'s label alignment is a *platform*
  default and the two disagree — measured with this source and nothing
  else changed, `labelAlignment` was `2` (`AlignRight`) under cocoa and
  `1` (`AlignLeft`) under offscreen — and the card never named its own.
  The code read the default and handed it straight back, which looks
  like a setting and is not one. So on a Mac every row's label sat
  against the right edge of its column and the left margin came out
  ragged, `Model`, `Server` and `API key` each starting somewhere
  different from `Provider` beside them.

  The suite could not have caught it: it runs under
  `QT_QPA_PLATFORM=offscreen`, the one platform that already agreed
  with the intent. Every test and every offscreen screenshot showed a
  correct card while the shipped app showed a wrong one. Both
  alignments are now named outright, and the tests force macOS's
  defaults before building a card so the override is actually
  exercised — a test that reads the property on whatever platform
  happens to run it passes either way.
- **A test drove itself from the thing it audited.** The comment above
  `_REDACTED_SETTINGS` claimed the next credential someone adds is
  "covered by the same test rather than by someone's memory". It was
  not: every redaction test named `huggingface.token` explicitly, so
  adding `llm.api_key` and forgetting the frozenset would have put the
  key in `app.log` in plain text with all tests green. The first attempt
  at the missing test iterated `_REDACTED_SETTINGS` — which made it
  worse than useless, because dropping an entry dropped it from the
  loop that was supposed to notice. Membership is now derived from
  `DEFAULT_CONFIG` by key name, and matched on the whole name:
  `push_to_talk_key` and `cancel_recording_hotkey` are not credentials,
  and a substring rule that called them one failed the file for the
  wrong reason.
- **The post-processing card never saved.** The enable checkbox and the
  mode picker were built and wired to nothing, so ticking the box did
  nothing and picking a mode did nothing. Both are covered now.
- **Changing the provider did not move the endpoint with it.** The
  Server field kept whatever the previous provider used, so moving from
  the local default to a cloud one pointed the request at
  `127.0.0.1:11434` — the user's own machine, on a path Ollama does not
  serve — and the step failed with a connection error that reads like a
  broken app rather than a stale field. Now the endpoint follows the
  provider, unless it is one somebody typed, in which case it is left
  alone: an OpenRouter base or a self-hosted vLLM is the whole reason
  the field is editable. The same default now resolves per provider in
  `from_config`, so a config naming a cloud provider with no endpoint
  does not send dictations — and their `Authorization` header — back to
  loopback.

### Changed
  one, and all sixteen were rewritten. The punctuation was doing real
  work — it attached an aside to a model name ("Sber GigaAM v3 with
  CTC decoder — the default") or set one off inside a sentence ("the
  most accurate card here and the fastest — from a download smaller
  than a screenshot") — so this was an edit rather than a find-replace:
  a comma appositive, a colon, or a full stop carries the same meaning.
  No measured figure moved: 135 numeric tokens in, 135 out, diff empty.
  `test_no_model_card_copy_carries_an_em_dash` holds the line across
  the whole catalogue. It deliberately asserts nothing about the two
  spaces after a full stop, which is a separate convention.

  The Models page subtitle went with them ("slower to load — the app's
  own starting point is first"), since leaving one em dash on the
  screen directly above sixteen descriptions without them would read
  as an oversight. The rest of the UI is untouched: its em dashes are
  either log lines or placeholder glyphs, where `"WER —"` means "no
  value" and is not punctuation at all.

### Fixed

- **`test_the_two_reset_buttons_are_worded_the_same` asserted the wrong
  thing.** It asked two buttons with different scopes to carry the same
  caption, on the ground that a stray plural reads as a typo — which is
  what produced two identical labels in the first place. It now asserts
  the opposite, and that each label names what it resets.
- **`test_model_card_colours_fast_and_only_fast` could not fail when its
  own premise stopped holding.** Its docstring said the coloured
  verdict "has to be a minority, or colouring it says nothing"; the
  assertion was `0 < coloured < len(MODELS)`, which at 13 fast of 16
  passes while the docstring is false for most of a year. The premise is
  now asserted directly, in `test_the_speed_word_is_not_a_minority`.
- **`test_no_empty_state_hardcodes_a_hotkey_anymore` read one view's
  removal as a regression.** It asserted every view with an empty state
  builds a `hotkey_cap(`, which is true of History and no longer true of
  Transcribe — so keeping the assertion would have argued for putting the
  cap back. It is now scoped per view: History must build its cap from
  `default_start_hotkey()` and hold no literal, Transcribe must contain
  no `hotkey_cap(` call at all. The hardcoded-default risk it guards is
  unchanged and still covered, on the view that renders one.

## 0.1.5 — 2026-10-11

The version is now readable at the bottom of Settings, where a bug report
asks for it, instead of three interactions away in the About dialog.

### Added

- **Version footer on the Settings view**, pinned to the bottom of the
  window. It sits beside the scroll area rather than at the end of the
  scrolling column, so it stays in view at every scroll position — the
  settings list is taller than any window, so a footer inside it would
  have been below every card.
- **`app/version.py`**, one place that answers "which version is this?".
  The About dialog and the footer read the same string by construction.
- **`test_the_runtime_reports_the_version_the_tree_declares`**, which
  compares what the app *would print* against `pyproject.toml`. The
  existing version tests all compare strings inside the repository, so
  they stayed green while the UI displayed the previous version.

### Fixed

- **Stale installed metadata no longer misreports the version.** After a
  version bump the venv keeps serving the previous `dist-info`, and the
  footer showed `0.1.3` on a tree declaring `0.1.4`. A version that lies
  is worse than no version: the user quotes it in a bug report and
  believes it.

### Changed

- `tests/test_version.py` now requires **exactly one** hardcoded version
  fallback, in one module. It previously accepted two in the About dialog
  and read only the first, which is how the second was free to drift.

## 0.1.4 — 2026-10-11

The macOS bundle now carries the hardened runtime and is signed in a way
that keeps the inference worker alive under it.

### Added

- **Hardened runtime on the release bundle.** Measured before:
  `flags=0x0(none)`; after: `flags=0x10000(runtime)`, `CodeDirectory`
  `v=20400` → `v=20500`. Apple requires this before it will notarize
  anything.
- **`scripts/entitlements.plist`**, declaring `com.apple.security.device.audio-input`.
  The runtime denies what it does not permit, so a hardened dictation app
  records nothing without it.
- **`codesign --verify --deep --strict` as a build gate.** A signature
  that does not verify is worse than no signature, and verifying is a
  separate question from `codesign` exiting 0. A build here once passed
  both the exit-status check and a certificate-anchored requirement check
  while failing `--verify` with *"a sealed resource is missing or
  invalid"* — a gap only Apple's notary service would have surfaced.

### Changed

- **Signing moved from `--deep` to inside-out**: leaves first, bundle last.
  `--deep` signs nested code as a side effect of signing the container,
  which leaves the order to codesign rather than to the build script.
- **Nested code is selected by what it is, not by whether it is
  executable.** 27 Mach-O files under `Contents` carry no execute bit and
  are the load-bearing ones: `libpython3.12.dylib`, which the inference
  worker links against, 22 pyobjc modules behind the autopaste and the
  permission probes, and scipy's gfortran dylibs plus portaudio.
- **The recording overlay follows the cursor.** It anchors to the screen
  under the pointer rather than the primary display — dictation is a
  global hotkey, and a confirmation delivered to the wrong screen is
  worse than none.
- **`setuptools` and `pygments` are out of the bundle**, 7.63 MB of
  build-time cruft that reached the artifact as dependencies of a
  dependency.
- **The file-path resampler is now asserted to be the microphone's
  resampler.** The numpy fallback is not equivalent: on real Russian
  speech it changes 2.13% of words, and it carries roughly twice the
  energy in the 7–8 kHz band because linear interpolation has no
  anti-alias filter.

### Fixed

- **The inference worker no longer dies under the hardened runtime on a
  self-signed build.** The runtime matches loaded libraries against the
  loading process's Team ID, and a certificate you generate yourself never
  has one — so `libpython3.12.dylib` was refused and the worker died on
  its first instruction. The window still opened, because the app falls
  back to the in-process backend; nothing reported an error.
- **Entitlements reach the worker.** `Contents/MacOS/python` is `exec`'d
  in its own right, so the runtime is enforced against its own signature
  and it needed its own entitlements rather than the bundle's.

### Known limitations

- Signed with a self-signed certificate, so **another Mac still requires
  right-click → Open**. TCC grants survive rebuilds on your own machine,
  which ad-hoc signing did not give. Clearing this needs an Apple Developer
  ID ($99/year, waivable for nonprofits, education and government); the
  command sequence is in README under *Notarizing the Mac build*.
- Inference runs on CPU for the default Russian model. Measured choice,
  not a fallback: CoreML takes 81% of the nodes and is still slower.

## 0.1.3 and earlier

- **0.1.3** (2026-10-08) — the About dialog's version fallbacks and the
  version-consistency test.
- **0.1.2** (2026-10-07) — packaging and CI corrections.
- **0.1.1** (2026-10-06) — history and configuration work.
- **0.1.0** (2026-10-05) — first release.
