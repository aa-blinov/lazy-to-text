# Feature Specification: Dictation Pipeline

> **Note (spec 011):** this spec was written against the former Qt interface. The Electron interface (spec 010) replaced it and the Qt code was removed (spec 011). The behaviour described here is still the behaviour spec of the engine; mentions of `app/gui` below name files that no longer exist, and the equivalent lives in the Electron renderer (`desktop/renderer`) and the runtime (`app/server`).

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "Speak into the microphone with a global hotkey, get the recognised text into whatever window has focus, locally, without looking at the app."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dictate into the focused window with two hotkeys (Priority: P1)

The user focuses any text field in any application, presses the start hotkey, speaks, presses the stop hotkey, and the recognised text is inserted at the cursor. This is the default recording mode (`two_keys`).

**Why this priority**: This is the product. Everything else (models, history, post-processing, overlay) hangs off this path.

**Independent Test**: With a loaded model and the default `two_keys` mode, press start, speak, press stop. The text appears in the focused window and a History entry exists.

**Acceptance Scenarios**:

1. **Given** the app is idle and the model is ready, **When** the user presses the start hotkey, **Then** the start sound plays, recording begins, and the state becomes `recording`.
2. **Given** a recording is running, **When** the user presses the stop hotkey, **Then** the stop sound plays, the recording stops, the state goes straight from `recording` to `processing` (never through `idle`), the audio is transcribed, and the text is delivered to the focused window.
3. **Given** the app is not idle (processing, loading a model, or already recording), **When** the user presses the start hotkey, **Then** the keypress is ignored and no second recording starts.
4. **Given** the app is not recording, **When** the user presses the stop hotkey, **Then** nothing happens.
5. **Given** the model is not ready (not loaded, or still loading), **When** the user presses the start hotkey, **Then** a user-visible message says the model is not ready and the start sound plays so the user knows the keypress was caught.

---

### User Story 2 - Hold a key to talk (push-to-talk) (Priority: P1)

The user chooses `push_to_talk` mode and a single key. Holding the key records; releasing it stops and transcribes. A press shorter than a minimum hold time is treated as an accident and discarded.

**Why this priority**: The fastest dictation gesture, and the only mode that can use a lone modifier key.

**Independent Test**: Set mode to `push_to_talk` with `right_cmd` (macOS) or `right_alt`. Hold for one second while speaking, release: text is delivered. Tap for 100 ms: no text, no history entry.

**Acceptance Scenarios**:

1. **Given** push-to-talk mode, idle app and a ready model, **When** the user presses and holds the configured key, **Then** recording starts once for that press (auto-repeat while held is ignored).
2. **Given** a push-to-talk recording, **When** the key is released after at least the minimum hold time (default 0.2 s), **Then** the recording stops and is transcribed.
3. **Given** a push-to-talk recording, **When** the key is released before the minimum hold time, **Then** the recording is cancelled without transcription and a user message says so.
4. **Given** push-to-talk mode, **When** the user presses the key while the app is not idle, **Then** the press is ignored (the state is not `idle`), and a held flag is still set so the later release does nothing harmful.
5. **Given** a push-to-talk key name that the platform does not recognise, **When** the listener is built, **Then** push-to-talk is inactive and a warning lists the recognised names; the cancel binding still works.

---

### User Story 3 - Toggle with one hotkey (Priority: P2)

In `toggle` mode (or in `two_keys` mode when the start and stop combinations are identical), one binding starts a recording when idle and stops it when recording.

**Why this priority**: A convenience for users who want one shortcut; also protects against registering the same key twice.

**Independent Test**: Set mode `toggle`, press the start combination twice with speech in between.

**Acceptance Scenarios**:

1. **Given** `toggle` mode and idle state, **When** the combination is pressed, **Then** recording starts (if the model is ready).
2. **Given** `toggle` mode and a running recording, **When** the combination is pressed, **Then** recording stops and is transcribed.
3. **Given** `toggle` mode and state `processing` or `model_loading`, **When** the combination is pressed, **Then** nothing happens.
4. **Given** `two_keys` mode where the start and stop strings are equal ignoring case and surrounding spaces, **When** the listener is built, **Then** it registers one toggle binding and no separate stop binding.

---

### User Story 4 - Cancel a recording (Priority: P2)

While recording, a cancel hotkey discards the audio without transcribing it.

**Why this priority**: Recovers from a false start without polluting History or the clipboard.

**Independent Test**: Start recording, press cancel: the cancel sound plays, nothing is transcribed, the state returns to `idle`.

**Acceptance Scenarios**:

1. **Given** a running recording, **When** the cancel hotkey is pressed, **Then** the buffer is discarded, the cancel sound plays, the tray goes back to `idle`, and a user message says the recording was cancelled.
2. **Given** no recording is running, **When** the cancel hotkey is pressed, **Then** nothing happens.
3. **Given** the cancel binding is empty in config, **When** the listener is built, **Then** no cancel binding is registered.
4. **Given** push-to-talk mode, **When** the cancel hotkey is pressed during a hold, **Then** the recording is cancelled the same way (the cancel binding is honoured in all three modes).

---

### User Story 5 - Know where the text went (Priority: P1)

After every dictation the user learns one of three outcomes: the paste keystroke was sent, the text is on the clipboard for the user to paste, or nothing was delivered.

**Why this priority**: The user is looking at their document, not at this app. "Did it go in?" must have an answer where they look (see spec 007 for the overlay that shows it).

**Independent Test**: Run a dictation with auto-paste on, then off, then with the paste keystroke blocked (macOS Accessibility revoked). Each yields `pasted`, `copied`, `copied` respectively; a clipboard failure yields `failed`.

**Acceptance Scenarios**:

1. **Given** auto-paste is on and the keystroke is sent, **When** delivery finishes, **Then** the outcome is `pasted`, and the Logs view says the keystroke was posted (never that the text was "pasted", because no platform API confirms what the target app did).
2. **Given** auto-paste is off, **When** delivery finishes, **Then** the text is on the clipboard, the outcome is `copied`, and the user is told which shortcut to press (Cmd+V on macOS, Ctrl+V elsewhere).
3. **Given** the copy succeeded but the keystroke could not be sent, **When** delivery finishes, **Then** the outcome is `copied` (not `failed`) and the dictation is still recorded in History.
4. **Given** the clipboard rejected the text, **When** delivery finishes, **Then** the outcome is `failed`, the text is not recorded in History, and the user is told it never reached the clipboard.
5. **Given** any outcome, **When** it is reported, **Then** the delivery callback receives the outcome, the paste shortcut (only for `copied`) and the delivered text, and an exception inside that callback never turns a delivered dictation into a processing error.

---

### User Story 6 - Failures are named, silence is not an error (Priority: P1)

The user is told the real reason when no text arrives: the model failed, no speech was heard, no audio reached the app, or the audio was silent.

**Why this priority**: Saying "no speech detected" for a model crash sent users hunting for a microphone problem they did not have (constitution principle II).

**Independent Test**: Make the backend raise `TranscriptionError`, return `""`, and return text in turn; check the three distinct user messages.

**Acceptance Scenarios**:

1. **Given** the backend raises `TranscriptionError`, **When** the pipeline runs, **Then** the user message says the model failed and this was not silence, the detail goes to the Logs view, and nothing is pasted.
2. **Given** the backend returns an empty string, **When** the pipeline runs, **Then** the user message says no speech was detected, nothing is pasted, and no History entry is written.
3. **Given** the recorder produced no chunks, **When** recording stops, **Then** the user is warned that no audio came from the microphone and advised to restart the app if it keeps happening, and the pipeline ends without transcribing.
4. **Given** the recorded peak amplitude is below 0.01, **When** recording stops, **Then** the user is warned that the audio looks silent and that the microphone may be wrong, muted or too quiet; the audio is still transcribed.

---

### User Story 7 - Long recordings stop themselves (Priority: P2)

A recording stops and is transcribed automatically when it reaches the configured maximum duration.

**Why this priority**: Bounds memory and inference time; the user who walks away from a running recording still gets the words.

**Independent Test**: Set `audio.max_duration` to 5, start recording, stay silent for 6 s: the stop sound plays and the pipeline starts without a stop hotkey.

**Acceptance Scenarios**:

1. **Given** a recording whose elapsed time reaches `audio.max_duration`, **When** the limit is hit, **Then** the recorder stops, the stop sound plays, the app is marked busy before the pipeline thread starts (so a hotkey cannot start a second recording in the gap), and the audio is transcribed and delivered like a normal stop.
2. **Given** `audio.max_duration` is 0 or negative, **When** recording, **Then** there is no limit.

---

### User Story 8 - Audible confirmation of every keypress (Priority: P3)

Three short sounds (start, stop, cancel) confirm that a hotkey was caught. Sounds can be disabled.

**Why this priority**: The user cannot see the app; the sound is the only immediate confirmation.

**Independent Test**: Toggle `audio_feedback.enabled`; press start, stop, cancel.

**Acceptance Scenarios**:

1. **Given** sounds are enabled, **When** recording starts, stops or is cancelled, **Then** the matching sound plays on a background thread without blocking the hotkey path.
2. **Given** a start press that cannot start a recording (busy, model not ready), **When** it is pressed, **Then** the start sound still plays.
3. **Given** `audio_feedback.enabled` is false, **When** any of the three events happens, **Then** nothing plays and the log says feedback is disabled.
4. **Given** a configured sound file does not exist, **When** the app starts, **Then** a warning names the missing file and the app continues.

---

### User Story 9 - The system output is quiet while recording (Priority: P3)

Optionally (macOS only) the system output is muted for the duration of a recording and restored afterwards. The setting lives in Settings (spec 006); this story fixes the ordering relative to the pipeline.

**Why this priority**: Opt-in refinement, but its ordering with the confirmation sounds is a contract.

**Independent Test**: With `audio.mute_output_on_record` on, observe call order: start sound, mute, recorder start; on stop: restore, stop sound.

**Acceptance Scenarios**:

1. **Given** the option is on, **When** recording starts, **Then** the start sound plays first, then the output is muted, then the microphone opens.
2. **Given** the recorder fails to start, **When** the start is abandoned, **Then** the output is restored.
3. **Given** a stop, a cancel, or application shutdown mid-recording, **When** it happens, **Then** the output is restored before the stop or cancel sound plays (and before the process goes away on shutdown).
4. **Given** muting fails, **When** recording starts, **Then** the failure is logged as a warning and the recording proceeds.

---

### Edge Cases

- A hotkey fires on a background thread; all state decisions use a lock-protected state machine so that two quick presses cannot start two recordings.
- Stopping marks the app busy before the recorder is stopped, because the recorder's stop blocks for tens to hundreds of milliseconds and an `idle` dip in between makes the overlay hide and re-appear re-anchored on the primary screen.
- The recorder is asked to start while a previous recording thread is still alive after its stop: the old stream is aborted; if it still cannot be released the user is told the microphone is held by the previous recording and to restart the app, and no recording starts (see spec 008).
- Start is pressed while a pending model change is queued: the model change runs after the current transcription finishes, then the state returns to `idle`.
- The audio buffer is released at the end of every pipeline run, including on error.
- A device that only supports its native rate (for example WASAPI) is captured at that rate and resampled to 16 kHz mono before the model sees it; stereo is averaged to mono.
- Key auto-repeat while a combination is held never fires the callback twice (macOS drops repeat events; push-to-talk has a held flag).
- Media or system keys on macOS must not kill the hotkey thread; the listener tolerates events delivered without an `injected` flag.
- A hotkey string the macOS parser cannot map is skipped with a warning; the other bindings still work.
- When two bindings overlap, the one with more keys is registered first.
- A hotkey callback that raises must not stop the listener (macOS: callbacks run on a dedicated worker thread; exceptions are logged).
- Pressing start while a LLM post-processing call is in flight counts as `processing` and is ignored.

## Requirements *(mandatory)*

### Functional Requirements

**State machine**

- **FR-001**: The system MUST expose exactly four states: `idle`, `recording`, `processing`, `model_loading`, evaluated in the priority order model_loading, processing, recording, idle.
- **FR-002**: A backend that reports status `loading` while the app is otherwise idle MUST be reported as `model_loading`.
- **FR-003**: A new recording MUST start only when the app is not processing, not loading a model, not already recording, and the backend health check passes; an exception from the health check MUST count as "not ready".
- **FR-004**: Stopping MUST take the state from `recording` to `processing` without an intermediate `idle`.
- **FR-005**: When the transcription pipeline ends, the busy flag MUST be cleared in all cases, and a queued model change MUST then be executed; otherwise the tray state MUST return to `idle`.
- **FR-006**: The UI controller MUST observe state by polling at a fixed interval (200 ms default) and emit a change signal only when the state differs from the last one.

**Hotkey modes**

- **FR-007**: The system MUST support the modes `two_keys` (default), `toggle`, `push_to_talk`; an unknown mode value MUST fall back to `two_keys`.
- **FR-008**: In `two_keys` mode a start binding MUST start recording only from `idle` with a ready model, and a stop binding MUST stop only while `recording`.
- **FR-009**: Identical start and stop combinations in `two_keys` mode MUST collapse into one toggle binding.
- **FR-010**: In `toggle` mode a single binding MUST start from `idle` and stop from `recording`, and ignore busy states.
- **FR-011**: In `push_to_talk` mode the configured key MUST start recording on press and stop on release; releases before `hotkey.push_to_talk_min_hold_seconds` (default 0.2) MUST cancel the recording.
- **FR-012**: The accepted push-to-talk key vocabulary MUST include right-side modifiers under several aliases (right cmd/command/win/windows/super, right option/alt, right shift, right ctrl/control); `fn` MUST be available on macOS and Linux only. Windows additionally accepts the native tokens `right_window` and `right_menu`.
- **FR-013**: Modifier aliases `ctrl|control`, `shift`, `alt|option`, `cmd|command|win|windows|super` MUST be normalised on macOS; `esc|escape`, `return`, `pageup`, `pagedown`, `del` MUST be accepted as key aliases.
- **FR-014**: The cancel binding MUST be optional (empty disables it) and MUST work in all three modes.
- **FR-015**: Changing any of the six hotkey parameters (`start_recording_hotkey`, `stop_recording_hotkey`, `cancel_combination`, `mode`, `push_to_talk_key`, `push_to_talk_min_hold_seconds`) at runtime MUST stop the listener, rebuild the bindings and restart it, and MUST do nothing when no value actually changed; an unknown parameter name or invalid mode MUST be rejected with an error.
- **FR-016**: Stopping the listener MUST reset the push-to-talk held flag so a later start is not stuck.
- **FR-017**: On macOS the hotkeys MUST use native event monitors (global and local) so grants take effect without a restart; on Windows the `global-hotkeys` library; elsewhere `pynput`.
- **FR-018**: Default combinations MUST be `ctrl+f8` / `ctrl+f9` / `ctrl+f10` (start/stop/cancel) on macOS and `ctrl+f2` / `ctrl+f3` / `ctrl+f6` elsewhere, because macOS reserves `Ctrl+F1`..`Ctrl+F7` for system navigation. The default push-to-talk key is platform specific (right cmd on macOS, right alt elsewhere).

**Recording**

- **FR-019**: The recorder MUST capture mono audio at the device's native rate and deliver 16 kHz float32 mono to the backend.
- **FR-020**: The recorder MUST honour `audio.device` (an index, or a case-insensitive substring of an input device's name); an unresolvable value MUST fall back to the system default.
- **FR-021**: The recorder MUST publish the most recent peak amplitude (0..1) of the live stream for the level meter, and MUST reset it to 0 on stop.
- **FR-022**: The recorder MUST stop and hand over its audio when `audio.max_duration` seconds (default 300) elapse, unless the value is not positive.
- **FR-023**: A recording thread that does not finish within its join timeout MUST have its input stream aborted; the failure to release MUST be reported and block the next start.
- **FR-024**: Recorder construction MUST log every input device and the one chosen, and MUST fail loudly if no input device can be queried.

**Transcription step**

- **FR-025**: The pipeline MUST transcribe the audio through the active backend and log the recorded duration as a user-visible message.
- **FR-026**: A `TranscriptionError` MUST be reported as a model failure and MUST NOT be reported as "no speech detected".
- **FR-027**: An empty transcription MUST end the pipeline with a "no speech detected" message and no delivery and no History entry.
- **FR-028**: A short preview of the recognised text (80 characters, truncated with an ellipsis) MUST be shown in the Logs view and MUST NOT be written to the log file (marked sensitive).
- **FR-029**: The text MUST pass through the optional post-processing step (spec 005) before delivery, and the post-processing step MUST fall back to the raw text on any failure.

**Delivery**

- **FR-030**: The delivered text MUST end with one non-breaking space so consecutive dictations do not stick together, and the History entry and `last_transcription` MUST NOT carry that space.
- **FR-031**: Delivery MUST return exactly one of `pasted`, `copied`, `failed`.
- **FR-032**: With `clipboard.auto_paste` on, the text MUST be copied, then (after `clipboard.key_simulation_delay`, at least 20 ms) the paste shortcut MUST be sent: Cmd+V on macOS, Ctrl+V on Windows and Linux.
- **FR-033**: With `clipboard.preserve_clipboard` on, the previous clipboard content MUST be restored after the paste, after a delay of at least 150 ms.
- **FR-034**: With `clipboard.auto_paste` off, the text MUST only be copied and the user told which shortcut to press.
- **FR-035**: When the optional "auto-enter" path is used, an Enter keystroke MUST follow a successful paste; when Enter cannot be sent the user MUST be told the text is on the clipboard and that they must submit it. (No hotkey currently selects this path; it is available to callers of the stop operation.)
- **FR-036**: A dictation that reached the clipboard (`pasted` or `copied`) MUST be added to History with text, duration, model and language (`auto` when unset); a `failed` delivery MUST NOT be added. A failure to write History MUST be logged and MUST NOT affect the delivery.
- **FR-037**: Changing `auto_paste` at runtime MUST take effect on the next dictation without restart.
- **FR-038**: The clipboard manager MUST fail construction loudly if the clipboard cannot be read, and on macOS MUST diagnose (not prompt for) the Accessibility post-event permission.

**Feedback**

- **FR-039**: Start, stop and cancel sounds MUST be played on daemon threads, and the stop sound MUST be played before the microphone stream is closed.
- **FR-040**: On Windows the audio device MUST be pre-warmed at startup and again after a model load finishes, because the first sound after an idle period is otherwise dropped.
- **FR-041**: The three sound files MUST be configurable through `audio_feedback.start_sound`, `stop_sound`, `cancel_sound`; defaults are the bundled `record_start.wav`, `record_stop.wav`, `record_cancel.wav`.
- **FR-042**: The output-mute ordering of User Story 9 MUST hold.

**Level meter**

- **FR-043**: While the state is `recording` the UI MUST poll the recorder's input level at up to 60 Hz and feed the sidebar meter; on leaving `recording` the poll MUST stop and the meter MUST be set to 0.

### Key Entities

- **Dictation state**: one of `idle`, `recording`, `processing`, `model_loading`; derived, not stored.
- **Recording mode**: `two_keys`, `toggle`, `push_to_talk`; stored in `hotkey.mode`.
- **Hotkey binding**: a combination string (modifiers joined with `+` plus one key) or a lone push-to-talk key name, with a role (start, stop, toggle, cancel, push-to-talk).
- **Audio buffer**: 16 kHz mono float32 samples from one recording; released after the pipeline ends.
- **Delivery outcome**: `pasted`, `copied`, `failed`.
- **History entry**: written for `pasted` and `copied` outcomes (spec 004).
- **Pending model change**: a model switch requested while a dictation was processing, executed when it ends (spec 002).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can complete a dictation (start, speak, stop, text in the target window) using only the keyboard and without switching to the app window.
- **SC-002**: Every dictation ends with exactly one of three delivery outcomes and one visible or audible signal; no dictation ends silently.
- **SC-003**: A model failure is never worded as "no speech detected"; the two are distinguishable by the user from the message alone.
- **SC-004**: A second recording can never start while one is recording or processing, regardless of how fast hotkeys are pressed.
- **SC-005**: A push-to-talk tap shorter than the minimum hold produces no text and no History entry.
- **SC-006**: The system output is never left muted after a recording ends, is cancelled, fails to start, or the app quits.
- **SC-007**: Latency figures for recording start, transcription and delivery are published in README.md and `app/model_mapping.py` (not restated here).

## Assumptions

- Local ONNX inference through the active backend (spec 002) is available; this spec does not describe how a model is chosen or loaded.
- Global hotkeys require the OS permissions described in spec 006 (macOS Accessibility; microphone permission on macOS).
- The pipeline runs on a worker thread; the Qt thread only observes state. The Electron interface reuses the same state machine, hotkey listener and clipboard manager.
- No hotkey is bound to the "auto-enter" delivery variant.
- Hotkey strings are validated in Settings (spec 006); the listener itself only skips unmappable macOS combinations and warns on unknown push-to-talk names.
- `system_tray` config is not consumed by the dictation pipeline; the tray follows the UI-level state (spec 007).

## Where it lives

Source:

- `app/state_manager.py`: the state machine, start/stop/cancel/toggle, the transcription pipeline, delivery reporting, pending model change, output-mute ordering, the one-shot profile override.
- `app/hotkey_listener.py`: three-mode listener, per-platform backends (Windows `global-hotkeys`, macOS native monitor, Linux `pynput`), push-to-talk vocabulary and press/release logic, runtime reconfiguration.
- `app/macos_hotkeys.py`: native AppKit event monitor, combination parser, key-code table, push-to-talk modifier-flag tracking, callback worker thread.
- `app/audio_recorder.py`: input stream thread, device resolution, resample and mono mix, peak level, max duration, stuck-thread abort, microphone test.
- `app/clipboard_manager.py`: copy, paste keystroke per platform, Enter keystroke, `deliver_transcription` three-way result, clipboard preservation.
- `app/audio_feedback.py`: start/stop/cancel sounds, Windows pre-warm, missing-file warning.
- `app/system_audio.py`: output mute used by the pipeline (detail in spec 006).
- `app/recording_factory.py`: builds recorder, feedback, clipboard, state manager and hotkey listener from config.
- `app/gui/controllers/recording_controller.py`: polls the state, forwards history and delivery signals to the Qt thread.
- `app/gui/controllers/app_controller.py`: level-meter polling, reaction to state changes.
- `app/config_manager.py`: `hotkey`, `audio`, `clipboard`, `audio_feedback` defaults.
- `app/assets/sounds/`: the three bundled sounds.

Tests:

- `tests/test_hotkey_listener.py`, `tests/test_macos_hotkeys.py`, `tests/test_clipboard_manager.py`, `tests/test_audio_feedback.py`, `tests/test_audio_recorder_resample.py`, `tests/test_audio_recorder_stuck_stream.py`.
- `tests/test_state_manager_cancel.py`, `_delivery.py`, `_audio_feedback.py`, `_output_mute.py`, `_overlay_anchor.py`, `_async_change.py`.
- `tests/gui/test_recording_controller.py`, `tests/gui/test_recording_factory.py`.
- No test opens a real microphone or loads a model; those claims are measured by hand.
