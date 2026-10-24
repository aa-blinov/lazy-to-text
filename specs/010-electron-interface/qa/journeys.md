# QA: user journeys (area: journeys)

Tester: journeys. Date: 2026-10-24. Build: worktree `llm-reasoning-tokens-config-624055`, app version 0.1.23.

## How this was run

- Real runtime (`python -m app.server`, port 18103) from my own scratch directory, real Vite (port 5403), and the Browser pane against `http://127.0.0.1:5403/?port=18103&token=devtoken`. Real onnx-asr with the real `vosk-ru-small` model copied into a scratch models folder (`storage.models_dir` pointed at the scratch folder in a hand-written `config.yaml`).
- Real microphone (MacBook Pro mic) fed by `say -v Milena` through the speakers; dictation started and stopped with `recording.toggle`. Real fake-LLM server (my own, port 18903) for post-processing.
- A browser tab has no `window.l2t`. For native dialogs I injected a stub (`openFile`, `saveFile`, `confirm`, `openDirectory`, `clipboard`, `pathForFile`) into the page and recorded its calls. Where the stub mattered it is said below. The capsule, tray and real native dialogs were not exercised (Electron only).
- Auto-paste was switched off for every dictation so no keystroke could go into another window.
- Not downloaded: no model. First-run download was exercised offline (`HF_HUB_OFFLINE=1`) to get the failure path.
- Environment findings that affect everyone testing in parallel:
  - **In a dev checkout the history file and `app.log` do not follow the profile directory.** The runtime writes `<worktree>/logs/transcription_history.jsonl` whatever the cwd is, so every tester's runtime (and the developer's own earlier history, entries from 08:36 and 11:14 today were there) share one history. I therefore never pressed Clear on the real flow (confirmation cancelled) and deleted/undid only my own entries. Recorded as QA-JOURNEYS-12.
  - The browser tab id `tab-2` was taken over by another tester during my run (the page navigated to port 18106 under me); I switched to my own tab.
  - My runtime was killed once by something that was not me (graceful shutdown line in the log, no action of mine at the time). Not counted as a defect.

## Defects

### QA-JOURNEYS-1  A dictation longer than about 21 s with the lightest model is lost, silently
Severity: S1
Status: FIXED - see QA-RUNTIME-3; every failed transcription now ends in delivery outcome failed with a readable detail and the audio kept in <logs>/unprocessed-recordings (last 3); verified by tests/test_state_manager_failure_outcomes.py and the real-model re-run. NEEDS renderer/Qt - show `detail` of a failed delivery (the capsule still prints the fixed text)
Where: dictation pipeline with `vosk-ru-small` (backend `app/backends/onnx_backend.py`, `_transcribe_chunk`), seen through Electron's capsule, Logs and History. The same code is under the Qt interface.
Steps:
1. Fresh scratch profile, `vosk-ru-small` active and loaded, auto-paste off.
2. `recording.toggle`; speak (via `say`) a text that lasts about 28 s; `recording.toggle` again.
3. Watch events, History and the clipboard.
Expected: the words arrive (`delivery` copied/pasted) and an entry lands in History; if the model cannot do it, a visible failure outcome and the audio or text is not simply dropped.
Actual: state goes `recording` -> `processing` (0.2 s) -> `idle`. No `delivery` event at all, no `history` event, no entry, nothing on the clipboard. The only trace is an ERROR in Logs: `OnnxAsr transcription failed: [ONNXRuntimeError] ... Reshape node ... '/encoder/encoders.0/layers.0/self_attn_weights/Reshape_3' ... cannot be reshaped` and one user-facing line `Error processing recording: Subprocess error: TranscriptionError: The model failed while transcribing: [ONNXRuntimeError] ...`. The capsule is driven by `state` and `delivery` only, so it would go from Processing to nothing. The 28 s of speech is gone.
Bisected with files of the same synthesised speech: 20 s transcribes, 22 s, 24 s, 25 s, 26 s, 30 s, 51 s, 60 s, a 2.5 min file and a 10 min file all fail with the same ONNX error (chunks are 25 s: the limit is a model limit below that). Reproduced 1 time live (dictation) and 10 of 10 file runs over 21 s.
Evidence: logs from `logs.list` (quoted above); events recorded in the page (`state` recording 20154, processing 41015... idle 41221, no `delivery`).
Suspected cause: `_CHUNK_SAMPLES = 25 * 16000` is longer than this model accepts; and the failure path of `transcribe` publishes no `delivery: failed` so the pipeline's outcome contract (FR-006, scenario 2) is not met for an exception.

### QA-JOURNEYS-2  A recording that fails to start leaves the whole system output muted, and the UI says "Recording started"
Severity: S1 (a stale saved microphone) / S2 (the mute alone)
Status: FIXED (core) - failed start restores the output mute and reports an outcome in every path (False, raise, stream failure, time limit); stale device falls back to default; verified by tests/test_state_manager_failure_outcomes.py and tests/test_audio_recorder_stale_device.py. NEEDS handlers - devices.select refusing an unknown device
Where: `devices.select` (`app/server/handlers/devices.py`), recorder start, `app/system_audio.py`.
Steps:
1. Settings: turn on "Mute other sounds while recording" (macOS).
2. `devices.select {device: 99}` (an index that is not a device; this is what a saved index looks like after a headset is unplugged).
3. `recording.toggle`.
Expected: `devices.select` refuses an unknown device (`device_failed`, as the contract says); a failed start unmutes the output and tells the user.
Actual: `devices.select` answers `{device: 99}` and writes `audio.device: 99` to the config. `recording.toggle` answers `{state: "recording"}`, the log says `INFO U Recording started! Speak now...`, then `ERROR Error during audio recording: Error querying device 99` (not user-facing) and the state returns to idle with no outcome. `osascript -e 'output muted of (get volume settings)'` answers `true`, `output-mute.json` lists devices 57 and 71, and the machine stays silent until the runtime is quit (graceful stop unmuted it; a second `toggle` did not). Reproduced 3 of 3 (three toggles). In the UI the picker only offers real devices, so the way in is a saved index that no longer exists.
Evidence: `output muted` true after two failed starts; false after runtime stop.
Suspected cause: `devices.select` stores without validating; the start path mutes before the recorder opens and does not undo on failure.
Status: Handler side FIXED, NEEDS core for the mute - `devices.select` refuses an unknown device (see QA-RUNTIME-5; verified by `tests/server/test_settings.py::test_an_unknown_device_is_refused_and_nothing_is_stored_or_switched`, live `devices.select 99` -> `device_failed`, `audio.device` stays null). The start path must unmute the output when the recorder fails to open (`app/state_manager.py`, core).

### QA-JOURNEYS-3  A conflicting hotkey typed into the capture field is refused on screen but saved and applied
Severity: S2
Where: Settings > Hotkeys, the capture field (`Settings.svelte`, `lib/hotkey.js`) against spec 006 FR-021 and acceptance scenario 1 of story 6.
Steps:
1. Settings > Hotkeys, two keys mode, Start ctrl+f8, Stop ctrl+f9, Cancel ctrl+f10.
2. Click the Start field, press Ctrl+F9 (or, second run, Ctrl+F10).
Expected: the message names the reason and the value is not stored, the listener keeps the old binding.
Actual: the page shows "Stop is the same as Start (ctrl+f9)..." under Stop, but `config.yaml` now has `start_recording_hotkey: ctrl+f9` and the log shows `Changed start_recording_hotkey: ctrl+f6 -> ctrl+f9`; with Start == Stop the listener configures a single toggle hotkey (`Configured toggle hotkey: ctrl+f9`), so the user's two-key setup silently became something else, and it survives a runtime restart and a page reload. Second run: Start := ctrl+f10 (= Cancel) saved as well. `settings.validate_hotkeys` and `settings.set_hotkeys` over RPC do refuse both, so the capture path does not go through them. Reproduced 2 of 2.
Evidence: config.yaml lines `start_recording_hotkey: ctrl+f9` / `ctrl+f10`; runtime log lines.
Status: FIXED - a conflicting binding refuses the whole `settings.set_hotkeys` request, whichever field was edited; verified by `tests/server/test_settings.py::test_capturing_the_stop_key_into_start_is_refused_and_nothing_changes` and `::test_capturing_the_cancel_key_into_start_is_refused_and_nothing_changes`; live: `settings.set_hotkeys {mode: two_keys, start: "ctrl+f9"}` over a stored f8/f9/f10 -> `saved: false`, stored start/stop/mode unchanged. The renderer must read `saved` and keep showing the field's old value.
Status: FIXED on the runtime side (`settings.set_hotkeys` now refuses a conflicting request as a whole); the renderer needed no change: it keeps the refused binding on screen with the reason beside it. Verified by the repro in the UI: Start field, Ctrl+F9 pressed; the screen shows the sentence under Stop, `config.yaml` still has `start_recording_hotkey: ctrl+f8`. The renderer also shows `save_error` now (toast 'Not saved to disk').

### QA-JOURNEYS-4  The window does not notice that the runtime died and offers no way back
Severity: S2
Where: `desktop/renderer/src/lib/rpc.js` (`source.onerror`), `desktop/electron/main.cjs` (`l2t:backend-exit`), `lib/backend.js`.
Steps:
1. Open the window against a running runtime (idle, model loaded).
2. `kill -9` the runtime process.
3. Wait, switch screens, start a file transcription.
Expected (spec Edge Cases): "the window says so, offers Restart".
Actual: the status strip keeps `IDLE / Current model: vosk-ru-small / Engine: CPU / CPU 32% / RAM ...` indefinitely; no Notice. A file run ends with `Error: Failed to fetch`. `rpc.js` reports `__disconnected` only when `EventSource.readyState === CLOSED`, which a dropped connection never reaches (it stays CONNECTING and retries). The main process does send `l2t:backend-exit` and `preload.cjs` exposes `onBackendExit`, but nothing in `renderer/src` subscribes to it (grep), and there is no Restart control anywhere (grep `Restart` in the renderer finds only text about restarting the app). When the same runtime came back on the same port the page recovered on its own (EventSource reconnect), so the dev-tab case is fine; the shipped case (new process, new port and token) has no recovery path. Reproduced 1 of 1 live, plus the code reading above.
Evidence: page text after the kill, `Error: Failed to fetch`.
Status: FIXED - `lib/rpc.js` decides the link is down when the stream errors and `/health` does not answer (or the shell reports the exit through `window.l2t.backend.onExit`, or the older `onBackendExit`), `lib/backend.js` resets state/engine/resources/progress/level, `EngineDown.svelte` blocks the window with 'The engine stopped', the log path and Restart (`window.l2t.backend.restart()`; 'Try again' in a plain tab), reconnection is automatic (`__connected`, a new connection is read from the shell, `onRestarted` is honoured), and after it every screen is remounted (`{#key $epoch}`) so settings, presets, models, history and logs are read again; the event stream now uses `app.events_ticket`. Verified by `tests/link.test.js` (17 tests) and the repro: `kill -9` of the runtime showed the dialog and 'Engine stopped' in the strip within about 4 s; a new runtime on the same port was picked up without a click and the dialog closed. The Electron-only parts (`backend.restart`, `onRestarted` with a new port) were exercised with fakes, not against the shell.
Status: Shell side FIXED (shell fixer) - the main process now notices the runtime ending, tells every window with `l2t.backend.onExit({code, signal})`, offers `l2t.backend.restart()` (resolves with the new `{port, token}` once the runtime is ready, rejects with a readable message), announces `l2t.backend.onRestarted({port, token})` to every window and keeps `l2t.connection()` current (rejects with "The engine is not running." while it is down); `l2t.backend.logPath()` gives the log. NEEDS renderer - subscribe to those, show the banner with Restart and the log path, and reconnect the event stream and the cached connection in `lib/rpc.js` after `onRestarted` (the new process has a new port and token).

### QA-JOURNEYS-5  Dropping a file anywhere on the window throws away the user's edited transcript without asking
Severity: S3
Where: `lib/transcribe.js` `transcribePath`, drop overlay (`installFileInbox`).
Steps:
1. Transcribe a file, edit the text (the "Edited" note appears).
2. Open any screen and drop another supported file anywhere on the window (also from Models).
Expected: a transcript the user changed by hand is not discarded by a stray drop (FR-013 made "drop anywhere" the new, easier gesture).
Actual: the screen goes to Transcribe and the run replaces the text at once; the edited text is gone, no confirmation, no undo. Reproduced 1 of 1 (dispatching real `dragenter/dragover/drop` events with a `File`).
Status: FIXED - `transcribePath` asks first when the text was edited (desktop dialog, or an in-window AlertDialog in a plain tab) for drop, Browse and OS open alike (`lib/transcribe.js`, `App.svelte`); verified by `tests/transcribe.test.js` 'replacing an edited transcript' (5 tests).

### QA-JOURNEYS-6  The no-model state has no way forward, and tells the user to "wait"
Severity: S3
Where: Transcribe screen, status strip, `files.transcribe` message, dictation hotkey, `FirstRun` copy.
Steps:
1. First run, choose "Set up later" (or finish setup once, then have no model on disk: weights removed, runtime restarted; `firstrun.status.show` is false because `onboarding.complete` is true).
2. Look at Transcribe and the strip; browse a file; press the hotkey (`recording.toggle`).
Expected: the empty state of the app says no model is installed and links to Models (Qt shows "No model"); a failed run says what to do.
Actual: Transcribe invites a drop as if all were well; the strip reads `Current model: vosk-ru-small   Engine: —` for a model that is not on disk; a file run says `Model isn't ready yet — wait for it to finish loading.` although nothing is loading and nothing ever will; the hotkey plays the start sound and writes one log line (`Model is not ready yet. Please wait...`), with no on-screen sign. Reproduced 3 of 3 (Set up later; two removals).
Status: Handler side FIXED, renderer for the screens - `recording.toggle` and `files.transcribe` answer `not_ready` with the sentence for the situation (loading / no model installed / not loaded) instead of 'wait'; verified by `tests/server/test_core_handlers.py::test_starting_without_a_model_is_refused_with_the_reason` and `::test_a_file_run_without_a_model_says_the_same_thing`. The empty state of Transcribe and the strip are the renderer's.
Status: FIXED (renderer side) - 'No model yet' in the strip and on Transcribe with a link to Models, and no 'wait' message when nothing is loading; verified like QA-VISUAL-12. The hotkey with no model is the runtime's (`recording.toggle` now answers `not_ready` with a sentence; the capsule does not show it).

### QA-JOURNEYS-7  A model that is on disk and marked Active but not loaded cannot be recovered from the UI
Severity: S2
Status: FIXED (core) - request_model_change loads a selected-but-unloaded model; NEEDS handlers - models.select must not answer noop in that state, it should call it
Where: Models (card state), `models.select` (`noop`).
Steps:
1. Runtime running with the model on disk. Stop it, move the model's hub folder away, start the runtime (the log says `skipping auto-load`), put the folder back (a restored backup, a drive mounted late, a storage folder switched).
2. Open Models.
Expected: the card offers Select (or Load) and the model loads.
Actual: `models.state` says `active: vosk-ru-small, cached: true`; Engine is `—`; the card shows Active and no Select button; `models.select {alias}` answers `{noop: true}`; `files.transcribe` says `not_ready`. Only restarting the runtime fixes it (it then loads: `provider: CPU`). Reproduced 2 of 2.
Status: FIXED (handler) - `models.state.ready` says whether the backend has a model loaded, and `models.select` on an active, present model that is not loaded loads it instead of answering `noop`; verified by `tests/server/test_models.py::test_selecting_the_active_model_loads_it_when_the_backend_has_nothing_loaded`. The card must offer Select when `active && !ready` (renderer).
Status: FIXED - the active card of a model on disk that the engine does not run shows 'Not loaded' and a Load button that calls `models.select`; the runtime now loads instead of answering `noop` in that case (`_engine_ready`); a `noop` anyway is reported in a toast. Verified by `tests/models.test.js` (two tests); the repro itself (moving the hub folder) was not re-run in the UI.

### QA-JOURNEYS-8  Failed first-run download: the message refers to things that are not on screen, the reason is hidden
Severity: S3
Where: `FirstRun.svelte` (download step, failed state).
Steps: first-run screen, press Download with the network unavailable (`HF_HUB_OFFLINE=1`).
Expected: the failure says why in words, offers retry.
Actual: heading "The download did not finish." with "Nothing was saved. Press the key on the card to try again." (there is no card or key on that step; the buttons are Try again, Back), and a toast "Could not load GigaAM v3 CTC ... The model did not start. The Logs say why." The first-run screen has no way to open Logs (no sidebar), so the pointer to Logs leads nowhere; the real reason (`LocalEntryNotFoundError ... outgoing traffic has been disabled`) is in the log only. Two identical toasts pile up after Try again. Reproduced 2 of 2 attempts.
Status: FIXED - copy now says 'Check that this computer is online, then press Try again', a Show log file button appears where the shell can reveal the file, the model-load toast is not shown on the first-run screen and carries one id elsewhere, so retries do not pile up (`FirstRun.svelte`, `components/models/store.js`); verified by the repro with `HF_HUB_OFFLINE=1` (one message, no toast). The reason itself still lives in the log, as the runtime sends no reason in `model_load`.

### QA-JOURNEYS-9  Post-processing failure line points to the wrong screen
Severity: S4
Status: FIXED - the line now says to check the post-processing preset; test suites green
Where: user-facing log line from the post-processing step.
Steps: preset with an unreachable or slow server (timeout 2 s), dictate.
Actual: `Post-processing failed (could not reach http://127.0.0.1:18903/slow/api/chat (TimeoutError)) — delivering the raw transcription instead. Fix it in Settings, or turn the step off.` In this interface the preset lives in Post-processing, not Settings. The raw text was delivered correctly (history holds it). Reproduced 1 of 1.

### QA-JOURNEYS-10  Large text size at the minimum window width: horizontal scroll and a truncated strip
Severity: S3
Where: shell layout, Models and Transcribe at 175 % text size, 900x600.
Steps: Settings > Appearance > Text size 175 %, window 900x600, open Models.
Actual: the sidebar (14 rem) takes about 40 % of the width, main is 502 px wide with a 770 px scroll width (Models) and 520 px (Transcribe), the search field and filter row are cut, the strip reads `Current model:…`. Reproduced 1 of 1 (the other screens fit).
Status: FIXED - same change as QA-VISUAL-4; verified at 175% on 900x600 for all six screens.

### QA-JOURNEYS-11  Raw internal error text reaches the user, also in Russian
Severity: S3
Status: FIXED - prefix removed at the source (subprocess_backend rebuilds TranscriptionError); verified by tests/backends/test_transcription_errors_across_the_pipe.py
Where: Transcribe error line (`lib/transcribe.js`), backend error wording.
Steps: transcribe an unreadable file (`fake.wav`, `corrupt.mp3`, `notes.txt` via Browse).
Actual: `Error: Subprocess error: TranscriptionError: Could not read audio from fake.wav — neither libsndfile nor ffmpeg could decode it`; in Russian: `Ошибка: Subprocess error: TranscriptionError: Could not read audio ...`. Source text said what went wrong, but the `Subprocess error: TranscriptionError:` prefix is plumbing, and nothing is translated. Same prefix in the long-file failure (`... [ONNXRuntimeError] ...` whole). Reproduced 3 of 3.
Status: FIXED - `file.failed` carries a sentence and a `code`, never `Subprocess error:`/exception class/ONNX text (see QA-RUNTIME-15); the Russian translation of these sentences is the renderer's. Verified by `tests/server/test_files.py::test_failure_reasons_lose_their_plumbing`.
Status: FIXED (renderer text) - `friendlyError` (see QA-VISUAL-13); the runtime's wording is the runtime's.

### QA-JOURNEYS-12  Dev runtime shares history, log and models root across profiles
Severity: S4 (dev and QA only; frozen builds use user directories)
Where: `app/server/runtime.py` (models root and history/log paths resolved from the checkout, not the cwd that holds `config.yaml`).
Steps: run two runtimes from two different scratch directories; dictate in one; open History in the other.
Actual: both show the same entries, and `app.log` is shared; the models root defaults to `<worktree>/models` unless `storage.models_dir` is set. QA README promises "own scratch directory for the config, history and models".
Status: FIXED - `python -m app.server --data-dir <folder>` (or `L2T_DATA_DIR`) keeps `config.yaml`, `logs/app.log` and `logs/transcription_history.jsonl` under that folder (`app/utils.py` `data_dir_override`, `app/config_manager.py`, `app/server/__main__.py`); documented in `implementation-guide.md` rule 8; verified by `tests/test_data_dir.py` and a real runtime started with `--data-dir` (the log and config appeared there, the checkout's `logs/` was not touched). Models are not moved: set `storage.models_dir`.

### QA-JOURNEYS-13  Microphone/hotkey/language settings do not follow a change made elsewhere
Severity: S4
Where: `lib/settings.js`, Settings and the language switch.
Steps: open Settings; change `clipboard.preserve_clipboard`, `hotkey.*` (reset) or `ui.language` from another client (`settings.set`, `settings.reset_hotkeys`).
Actual: the open page keeps the old value (switch stays on; the hotkey field shows the old binding; the UI stays English) until reload; a later edit on the stale page writes over the new value. Presets do follow (their event is wired). In shipped Electron the only second writer is Qt, which cannot run at the same time, so this is minor. Reproduced 3 of 3.
Status: FIXED (runtime side) - `settings.set`, `settings.set_hotkeys`, `settings.reset_hotkeys` and `devices.select` emit a `settings` event; verified by `tests/server/test_settings.py::test_changes_are_announced_so_an_open_screen_can_follow`. The Settings screen must re-read `settings.get` on it (renderer).
Status: FIXED - the renderer follows the runtime's `settings` event: the Settings screen reads `settings.get` again and the window re-reads the snapshot (theme, palette, language, also in the capsule); verified by `tests/settings.test.js` 'reads the settings again when another client changed one'. The hotkey card keeps its own draft until the screen is reopened.

### QA-JOURNEYS-14  Logs view mixes records of two runtime lives after a restart
Severity: S4
Where: `components/logs/store.js` (`merge` by id).
Steps: Logs open, restart the runtime under the same page, wait for new records.
Actual: the count stayed at 195 while new records arrived; the new runtime's lines (ids 1..30) replace/interleave with the old ones by id and sort to the top, so "Following the newest line" shows old records at the bottom. Not reachable in shipped Electron (no restart without relaunching the renderer). Reproduced 1 of 1.
Status: FIXED - the Logs store starts over when the window reconnects (`components/logs/store.js`, keyed on the reconnection counter), so two lives of the runtime are not merged by id; verified by `tests/logs.test.js` 'starts over when the window reconnects'; the live restart in the UI was exercised for QA-JOURNEYS-4 only.

### QA-JOURNEYS-15  Repeated unnamed controls for assistive technology
Severity: S3
Where: History rows (11 x "Copy", 11 x "Delete"), Models cards (15 x "Download", 16 x "Show more"; the Select/Delete buttons are the same), Settings (3 x "Type it instead").
Steps: read the accessibility tree / compute accessible names on each screen.
Actual: identical names with no row or card context (`aria-describedby` absent; the Models buttons sit in an unnamed `role=group`). A screen-reader user cannot tell which row Delete removes. Everything else I computed (all inputs, switches, radios, icon buttons) had a name. Reproduced on all three screens.
Status: FIXED - History Copy/Delete carry the row text, Models Select/Download/Delete/Load/Show more carry the model name, 'Type it instead' carries its field; verified by `tests/history.test.js`, `tests/models.test.js`, `tests/settings.test.js` and the accessibility tree in the repro ('Удалить: https://example.com/aaaa...').

### QA-JOURNEYS-16  Small items
Severity: S4
- Clearing the "Longest recording" field (or a non-number) stores `0`, which means "no limit", so a user who deletes the number to type another one leaves recording unlimited if they stop there. Negative and over-limit values are rejected back to the previous value, which is fine. (Seen 2 of 2.)
- Units and numbers are not localised in Russian: `110 KB · 23 ms`, `4.9 s` in History, `RTF 0.018` with a dot. User-facing log lines ("Messages for you") stay English in the Russian UI.
- `models.inference.set` with a non-numeric `beam_size` silently resets a stored value to the default instead of keeping or rejecting it (20 -> 5).
- `presets.test` with an address that is not a URL answers `the request failed (ValueError)`; nothing says the address is invalid.
- `models.storage.apply` with an unwritable folder (`/etc`) and `move: true` answers `started`, the copy fails with `Permission denied`, and the config still switches to the new folder, so the downloaded model disappears from the catalogue until the folder is switched back. The UI guard (`models.storage.plan`: "That folder cannot be written to") stops this path, so it is reachable only by a race or another client. (Seen 1 of 1.)
- History table at 1100 px: the Model column wraps `vosk-ru-small` onto three lines.
- A new preset is a copy of the first preset including its API key, and the name field after Duplicate reads the old name for a frame (contract says so for Duplicate; "New preset" carrying the key is worth a second look next to the cloud privacy line).
Status: Partly FIXED - handler items done: `models.inference.set` refuses a non-numeric `beam_size` instead of resetting it; `presets.test` with an address that is not a URL says why in `llm_test.message`; `models.storage.apply` refuses an unwritable folder before anything is written; a new preset (`presets.create`) no longer inherits the first preset's key. Verified by `tests/server/test_models.py::test_inference_settings_that_would_be_silently_replaced_are_refused`, `tests/server/test_presets.py::test_a_test_with_a_bad_address_answers_with_the_reason_and_calls_nothing`, `::test_a_new_preset_does_not_inherit_the_first_ones_key`, `tests/server/test_models.py::test_apply_refuses_a_folder_that_cannot_be_written`. The 'Longest recording' field storing 0, localisation and the History column are the renderer's.
Status: PARTLY FIXED - emptying 'Longest recording' no longer stores 0 (the value is restored with a notice; typing 0 still means no limit); durations and sizes use the interface unit ('3.3 с'). Not fixed here: decimal separators and 'RTF' in Russian, the log lines (runtime text), the items about `models.inference.set`, `presets.test` wording and `models.storage.apply`, which are the handlers'.

## Covered, no defect

| Journey | Result |
| --- | --- |
| 1 First run: fresh profile shows the setup screen with the recommended model | OK |
| 1 "See all models instead" then selecting the seeded vosk model, shell, status strip, relaunch | OK. `onboarding.complete` stays false after this path (only "Start dictating" sets it, per FR-075); first-run does not return while a model is on disk |
| 1 "Set up later" then relaunch | OK: first-run returns on the next launch (deferred only for the session) |
| 1 Download failure offline, Try again, Back | Works (copy defects in QA-JOURNEYS-8) |
| 1 "Start dictating" at the end of a real download | Not exercised (needs the network) |
| 1 Delete the only model after first run | The active model cannot be deleted (card shows no Delete; RPC answers `in_use`); matches the Qt rule. Removal outside the app is QA-JOURNEYS-6/7 |
| 2 Dictation of 8 s: states recording -> processing -> idle, levels at 20 Hz, delivery `copied` with detail, history entry live, language and duration right | OK (3 dictations) |
| 2 Cancel a recording: no entry, back to idle | OK |
| 2 Auto-stop at the longest-recording limit (4 s): processed and delivered | OK |
| 2 History live append while the screen is open, search, "No matching", Escape clears, details modal, Escape closes and returns focus | OK |
| 2 Delete + Undo (single and two quick deletes), export (save dialog stub, file written), Clear history confirmation shown (cancel kept 9 entries) | OK. Clear itself was not run (shared history, see above) |
| 3 Browse a file: transcript, Edited label appears and goes with word count, Copy copies the edited text, Save .txt writes UTF-8 | OK |
| 3 Missing file, unreadable file, non-audio file, drop of an unsupported type, drop with several files (first supported used) | Errors shown, drop zone returns (wording in QA-JOURNEYS-11) |
| 3 Switch screens during/after a run and come back | Text, edits and Edited label kept (state is in a store) |
| 4 Model search (name, alias, number), no match empty state, sort Smallest first, family chips | OK |
| 4 Per-model inference settings: clamp (beam 99 -> 20, temperature -5 -> 0), persisted in `model_overrides` | OK |
| 4 Storage plan guard, move to another folder and back, model keeps working | OK |
| 4 HF token: set (field cleared, never echoed in DOM, snapshot or logs), "A token is saved", clear | OK. The token is stored in clear in `config.yaml` as the spec allows |
| 5 Create, duplicate, delete the active preset (first remaining becomes active), activate, delete confirmation | OK |
| 5 Switch on, test connection against the fake server, key sent as Bearer, reasoning effort and max tokens reach the request, failure messages (refused, timeout) carry no key | OK |
| 5 Dictation through the fake model and through a slow one (raw text delivered, user-facing line) | OK (wording QA-JOURNEYS-9) |
| 5 Cloud privacy line appears as the address is typed; local address shows the local line | OK |
| 5 Timeout 1..600 and max tokens 0..32768 bounds, persistence after page reload and runtime restart, API key rendered as a password field | OK |
| 6 Toggles, longest recording, palette, theme, text size persist after reload and after runtime restart (`settings.get` and `presets.get` byte-identical before and after) | OK |
| 6 Hotkey validation over RPC (duplicate, empty part, lone key, Stop == Start, Cancel == Start/Stop), set and reset | OK. The capture field is QA-JOURNEYS-3 |
| 6 Mode switch two_keys / toggle / push_to_talk: fields enable and disable, Cancel emptied and restored, PTT key shown | OK |
| 6 Microphone list, select, test with speech (peak and rms, verdict, 59 level events) | OK. Invalid index is QA-JOURNEYS-2 |
| 6 Permission banners forced to untrusted/denied through a patched `fetch`: both banners and buttons shown with right text | OK |
| 7 Logs: level filters, user-facing filter (21 of 195), search, empty state, pause on scroll, clear asks first (kept) | OK. Copy needs the desktop clipboard bridge; the browser refused, so not verified |
| 9 Cmd/Ctrl+1..6 and Cmd+, in sidebar order; Shift or a seventh key ignored | OK |
| 9 Escape closes the history dialog and focus returns to the trigger | OK |
| 9 Accessible names on inputs, switches, radios and icon buttons | OK except QA-JOURNEYS-15 |
| 10 Russian: every screen, sidebar, dialogs, banners, placeholders translated; only IDs, model names and log text stay Latin | OK except units/log lines in QA-JOURNEYS-16 |
| 8 Runtime back on the same port: the page reconnects and works | OK (dev case) |
| 8 Presets changed by another client appear live | OK |

## Not tested, and why

- Capsule, tray, window close-to-tray, native dialogs, real drag from Finder, OS file open: Electron only (no Electron run to avoid the shared Vite port 5173; the stub covers the renderer side only).
- "Start dictating" after a real download, download progress, cancel and rollback of a load: needs the network or a slow backend; offline failure only. Model Cancel/rollback with a fake slow backend was not built.
- Transcribing a second file while the first runs: no successful slow file was possible (vosk finishes a long file in about a second, and files over 21 s fail, QA-JOURNEYS-1). A failing huge file followed by a second one behaved correctly (stale result dropped).
- Skip-silence (silero VAD): switching it on downloads a model.
- Real macOS permission denials (python under the terminal gets the terminal's grants); only forced banner states.
- Delivery by real paste (`pasted`), `Paste sent` wording, keystroke failure.
- A second Electron window, light theme with each palette, text-scale effects on every screen.
- Dates and numbers formatting beyond what is listed.

## Ranked summary

1. QA-JOURNEYS-1 (S1) A dictation over about 21 s with the lightest model silently vanishes: no outcome, no history, no capsule.
2. QA-JOURNEYS-2 (S1/S2) A saved microphone that no longer exists is accepted, recordings fail with "Recording started", and the whole system stays muted.
3. QA-JOURNEYS-3 (S2) Conflicting hotkeys typed into the capture field are saved and applied despite the error.
4. QA-JOURNEYS-4 (S2) The window never learns that the runtime died and has no Restart.
5. QA-JOURNEYS-7 (S2) A model on disk, marked Active but not loaded, has no recovery in the UI.
6. QA-JOURNEYS-5, 6, 8, 10, 11, 15 (S3) Silent loss of edited transcript on drop; no-model state with a "wait" message; first-run failure copy; 175 % text at 900 px; raw `Subprocess error` text; duplicated accessible names.
7. QA-JOURNEYS-9, 12, 13, 14, 16 (S4) Wrong screen named in a log line; shared dev history; stale settings across clients; log merge after restart; small items.

Everything started was stopped (runtime, Vite, fake LLM server, my browser tab); the system output is unmuted. Left behind outside `qa/`: about nine of my own entries in `<worktree>/logs/transcription_history.jsonl` and lines in `<worktree>/logs/app.log` (shared dev paths, QA-JOURNEYS-12), and the system clipboard contents.

File: `/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055/specs/010-electron-interface/qa/journeys.md`
