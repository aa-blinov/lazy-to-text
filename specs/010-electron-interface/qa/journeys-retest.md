# QA retest: user journeys (area: journeys)

Tester: journeys (second pass, a different engineer from the first). Date: 2026-10-24. Build: worktree `llm-reasoning-tokens-config-624055`, app 0.1.23, HEAD `42d92f6` plus uncommitted fixes.

## How this was run

- Own runtime on port 18303 (`--dev --dev-port 5603`, the guide's command without `--dev` is refused by the Origin check for a Vite tab), own Vite on 5603, scratch directory with its own `config.yaml` (`storage.models_dir` pointed at a scratch copy of the hub, `vosk-ru-small` loaded). Own Browser tab. Own fake LLM server (port 18913).
- Real microphone, speech from `say -v Milena` through the speakers, real global hotkeys (a synthesised Ctrl+Option+F8/F9 through System Events started and stopped a dictation: works).
- A browser tab has no `window.l2t`; for native dialogs and drops I injected a stub (`openFile`, `saveFile`, `confirm` returning a button index as the real one does, `pathForFile`) and removed it for the plain-tab checks. The capsule, tray, real native dialogs and the Electron shell side of `backend.restart` were not exercised.
- Auto-paste off for all dictations. Output mute was checked with `osascript` after every mute test; the system is unmuted.
- Environment findings:
  - QA-JOURNEYS-12 is not fixed: the log (`<worktree>/logs/app.log`) and history (`<worktree>/logs/transcription_history.jsonl`) are still shared by every dev runtime, so my History shows other testers' entries (`FAKE: ...`). I never pressed Clear.
  - All dev runtimes share the same global hotkeys (default Ctrl+F8/F9/F10). Another tester's keypress started a recording in my runtime once and my own transcript got foreign speech. I moved my runtime to Ctrl+Option+F8/F9/F10 after that.
  - The scratch hub also held no second model, so model-switch journeys were tested with the deletion/restore of `vosk-ru-small` only.

## Retest of the 16 defects

One line per ID; `Retest:` is mine.

| ID | Retest | Evidence |
| --- | --- | --- |
| QA-JOURNEYS-1 long dictation / long file | PASS | Dictation of 32 s speech (35 s recording): states recording -> processing (0.2 s) -> idle, `delivery copied`, history entry with all 69 words, same text as the file run. File of 64 s: 139 words in 0.4 s (138 spoken). A 322 s file: 694 words (690 spoken), done in 1.2 s. Auto-stop at a 4 s limit: delivered. A recording of ~50 ms (accidental double tap) is a new defect, QA-JOURNEYS-R2 |
| QA-JOURNEYS-2 stale microphone, mute stays on | PASS (partial) | `devices.select` 99, -1: `device_failed` with `field: device`; "x", true, 1.5: `bad_params`; nothing stored. With `audio.device: 99` on disk and mute on: the log says "The saved microphone (device 99) is not available - using the system default input", the recording starts on the default, mute is on while recording and `output muted` is false after stop; `output-mute.json` removed. A real failure of the recorder to open (the other branch of the fix) could not be provoked with the hardware here (the iPhone mic opened fine), so the "failed start unmutes" branch is covered by the unit test only |
| QA-JOURNEYS-3 conflicting hotkey saved | PASS (runtime), see QA-JOURNEYS-R1 | Real key presses in the capture field: Start := Ctrl+F9 (= Stop) and Cancel := Ctrl+F8 (= Start). `settings.get`, `config.yaml` and the listener log keep the old bindings; the reason is shown (also in Russian). A valid change (Cancel := Ctrl+F5) saves, applies live ("Configured cancel hotkey" in the log) and persists. But the toast is wrong, R1 |
| QA-JOURNEYS-4 runtime death | PASS | `kill -9` of the runtime (twice, once while recording): within about 4 s the window shows "The engine stopped" (alertdialog, focus inside, log path, Try again), strip says engine stopped; Try again with the engine down: "The engine did not come back. Try again." Restarted on the same port: the dialog closes by itself, the strip is live, a dictation appends to History live, state is idle (not stuck on recording). Same in Russian. Not exercised: Electron's `backend.restart` and a new port/token (shell) |
| QA-JOURNEYS-5 drop over edited transcript | PASS | Edited the text (Edited label), dropped another file from Transcribe and from Models. Desktop dialog stub: "Replace the edited transcript?" Keep editing keeps the text and the file, Replace transcribes. In-window dialog (plain tab): Escape keeps, Replace replaces |
| QA-JOURNEYS-6 no-model state | PASS | Hub moved away, runtime restarted: first-run screen; "Set up later" path: strip "No model yet / Open Models", Transcribe shows "No model yet ... Open Models", Browse and drop answer "No model is loaded yet. Download one or load the one you chose." (no "wait"); `recording.toggle` and `files.transcribe` answer `not_ready` with the right sentence. The hotkey itself still gives no on-screen sign (capsule is Electron only) |
| QA-JOURNEYS-7 Active but not loaded | PASS | Model folder moved away before start, put back with the runtime running: `models.state` active vosk, cached true, `ready` false; the card shows "Not loaded" and a Load button; clicking it loads, toast "ready", Engine CPU, dictation works. The strip kept saying "No model yet" until then (QA-JOURNEYS-R6, S4) |
| QA-JOURNEYS-8 first-run download failure | PASS (first attempt), FAIL on retry | HF offline: copy now reads "Nothing was saved. Check that this computer is online, then press Try again.", no Logs pointer, no toast. But Try again hangs, see QA-JOURNEYS-R3 (S2) |
| QA-JOURNEYS-9 wrong screen named in log | PASS | Slow server (timeout 2 s): "Post-processing failed (could not reach ... (TimeoutError)) - delivering the raw transcription instead. Check the post-processing preset, or turn the step off." Raw text delivered, in History |
| QA-JOURNEYS-10 175 % text at 900x600 | PASS | Text size 175 %, 900x600, all six screens: `scrollWidth == clientWidth` for main (624 px), no page scroll, strip intact. Russian Models also |
| QA-JOURNEYS-11 raw `Subprocess error:` text | FAIL (partial) | English: `fake.wav`, `corrupt.mp3`, `notes.txt`, empty file: "Could not read audio from X. The file may be damaged, cut short, or not an audio or video file." (prefix gone). In Russian the sentence stays English: "Ошибка: Could not read audio from corrupt.mp3. The file may be damaged..." (QA-JOURNEYS-R4). The title of the defect says "also in Russian" |
| QA-JOURNEYS-12 shared dev history/log | FAIL (not fixed, no Status in the report) | Still shared; see environment note |
| QA-JOURNEYS-13 settings do not follow | PASS (partial) | `settings.set` of language, theme, text size, sound cues from outside: the open page follows each (language and Nord palette switched live). `devices.select` from outside does not update the Microphone select (R5, S4); the hotkey card keeps its own draft by design |
| QA-JOURNEYS-14 Logs mixes two runtime lives | PASS | Logs open with 153 lines, runtime restarted: 21 lines, all from the new life, in order, following the newest |
| QA-JOURNEYS-15 repeated unnamed controls | PASS | Computed accessible names of every button, input, switch, radio on all screens: History Copy/Delete carry the row text ("Copy: ..."), Models Select/Download/Load/Show more carry the model name, 'Type it instead' carries the field; the only repeats are rows with identical text and the per-card family filter chips (named by family). No unnamed control |
| QA-JOURNEYS-16 small items | PASS (partial) | Cleared "Longest recording": value restored (123) with "Enter a number of seconds from 0 to 3600". `models.inference.set` with `beam_size: "abc"`: `bad_params`, stored value kept. A bad server address: sentence "The address must start with http:// or https://" shown as typed and the stored address unchanged. `presets.create`: copy without the key (`api_key_set` false). `models.storage.apply /etc`: "That folder cannot be written to." Units are localised ("КБ", "мс", "с"). Still open: decimal separators (`4.7 с`, `RTF 0.018`) and "MB" inside the model descriptions in Russian while the titles say "МБ"; log lines stay English; the History Model column still wraps `vosk-ru-small` onto two lines at 1100 px (three at 800 px) |

## Journeys re-walked end to end

| Journey | Result |
| --- | --- |
| 1 First run | Fresh profile with no model: first-run (Choose, Download, Learn the key steps), "Set up later", failed download (offline) with Try again/Back. Seeded model on disk: the shell opens directly. A retry after a failed download hangs: R3 |
| 2 Dictation | By RPC toggle and by real global hotkey: 5 s, 12 s, 35 s dictation, auto-stop, cancel, rapid toggles, dictation during a file run: all end idle with an outcome. History appends live after a reconnect. Delete + Undo restores the same entry, details dialog opens with focus inside and Escape returns focus to the trigger; Export writes UTF-8 (a folder inside the app's own config dir is refused with a toast); Clear asks first (cancelled, nothing lost) |
| 3 Transcribe | Browse, drop, edit (Edited), replace guard, Save/Copy not re-run in depth; error states for missing/corrupt/non-audio/empty file; stale identity line after a failed Browse names the previous file (R7, S4) |
| 4 Models | Cards, names, no-model state, Not loaded + Load, Cancel of a hanging load works from the first-run screen |
| 5 Post-processing | Edit server and key in the UI (typed with the keyboard: key saved on blur and on leaving by Cmd+3, field cleared, "A key is saved. Type a new one to replace it.", CLEAR removes it at once), key never in the DOM (`<input type=password>` value is emptied after save), `app.snapshot`, `presets.get`, runtime log or app.log (greps for the key: 0). Test connection against the fake server works (the request carried model and `temperature 0`). Failure path delivers the raw text |
| 6 Settings | Microphone by keyboard (open, arrows, Enter), toggles, longest recording, hotkeys, appearance; persistence: `settings.get`, `presets.get` and `models.state` byte-identical before and after a runtime restart (theme, palette Nord, text size, language, max duration, clipboard keep, hotkeys, preset with key) |
| 7 Logs | Rendered, filters, user-facing messages, resets on reconnect |
| 8 Runtime death | See QA-JOURNEYS-4 |
| 9 Keyboard | Cmd+3 switches screens; the first Tab after a screen switch goes to the screen's first control; dialogs trap focus (alertdialog, `aria-modal`); microphone select and hotkey capture by keyboard; Escape cancels capture |
| 10 Russian | Walked every screen after switching language live (the page follows without reload); list of what is left in English below |

### Russian: strings left in English (all screens, dark, 1100x800)

- Transcribe: "Could not read audio from X. The file may be damaged, cut short, or not an audio or video file." inside "Ошибка: ..." (R4). The status text created before the language switch (e.g. "Error: That file is no longer there.") is frozen in the language it was created in; created in Russian it is translated.
- Transcribe: aria-label "Dismiss" of the status notice.
- Models: "260 MB", "30 MB", "50 MB" in the descriptions (titles say "МБ"); decimals with a dot everywhere.
- Logs: all runtime lines ("Messages for you" too), by design of the runtime.
- Post-processing: preset name "Default" (user data, stored in English).
- Technical names that stay Latin on purpose: model aliases, Hugging Face, WER/CER/RTF, "Ctrl/Option", palette names, "silero VAD".
- Toasts created before a language switch (for example "Export failed") stay in the earlier language until closed.
- Hotkey conflict sentence names "Toggle mode" / «Переключение», but the radio is called "One key: press to start and stop" / «Одна клавиша: ...» (R8, S4).

## New defects (introduced by the fixes or missed)

### QA-JOURNEYS-R3  A model load started after a failed one never finishes; the first-run screen and Models sit on "Starting..." until Cancel
Severity: S2
Where: backend/state manager (`app/backends/onnx_backend.py` `_do_load` error branch, `app/state_manager.py` wait loop), seen in `FirstRun.svelte` and Models.
Steps:
1. Fresh runtime with no model on disk, `HF_HUB_OFFLINE=1` (or any failing download).
2. `models.select {alias: "gigaam-v3-ctc"}` (or press Download on the first-run card). It fails after about 3 s (`last_load.outcome: error`, state idle).
3. Do it again (or press Try again).
Expected: fails again the same way.
Actual: the state stays `model_loading`, `loading: true`; the log has the same "CPU fallback also failed" error as the first time but never "Failed to load" afterwards, only "Still loading gigaam-v3-ctc... (30s/60s/90s elapsed, backend status=loading)". The screen shows "Starting... 19 s" and a Cancel button, nothing else; the third attempt gives `busy`. Cancel (`models.cancel_load`) recovers; the backend is not wedged (a later select of a present model loads). Reproduced 3 of 3 retries after a first failure (RPC alone, and through the UI).
Evidence: `rt.log` lines "Switching to gigaam-v3-ctc model..." twice, one "Failed to load" only; `models.state` after 40 s.
Suspected cause: the error branch of `_do_load` writes `_status = "error"` only if `not self._cancel_requested and self._model_name == model_name`; after the first failure one of these no longer holds, so status stays `loading`.
Status: FIXED (renderer side; the runtime's wedge is the Python fixer's) - `FirstRun.svelte` reads `models.state.last_load` while waiting and shows the failure (with Try again and Back) as soon as a load that ended in `error` after this attempt is reported, even if the state still says loading; a retry first calls `models.cancel_load` so a stuck load cannot answer `busy`; `DownloadProgress.svelte` says 'This is taking longer than usual. You can cancel and try again.' after 45 s of start/load with no progress, Cancel stays on both screens and in the strip; the `model_load` toast shows the runtime's `reason` sentence. Verified by `tests/models.test.js` (three FirstRun tests, 'a failed load') and by the repro re-run on a no-model runtime with `HF_HUB_OFFLINE=1`: failure, Try again, failure again (the runtime now ends the second load too).
Status: FIXED - root cause was in the worker's status push (`app/backends/subprocess_worker.py`): the broadcaster compared each poll with its own previous poll, so after a failure it remembered `error`; the retry's `loading` went out with the command, the retry failed again inside one 100 ms poll (offline or missing weights fail at once), the broadcaster saw `error` == `error` and pushed nothing, and the parent cache stayed on its optimistic `loading` for ever. Both writers now read and record under one lock and compare against what the parent was last told. A failed load also gives `last_load.reason` / `model_load.reason` (a sentence for the user, no exception text) in `app/server/handlers/models.py`; verified by `test_a_retry_that_fails_inside_one_poll_still_reports_the_failure` (fails on the old worker) and `test_a_failed_or_cancelled_load_is_named`; repro re-run by hand on a real runtime (scratch hub with no model, `HF_HUB_OFFLINE=1`): four `models.select` of `gigaam-v3-ctc` in a row each ended `idle` with `last_load.outcome: error` and the reason, then `vosk-ru-small` copied in and selected loaded (`ready: true`). The unfixed race is timing dependent and did not reproduce by hand on the old code in my two tries, so the unit test is the witness of the cause.

### QA-JOURNEYS-R2  A very short recording (accidental double tap of the hotkey) is reported as a model failure with raw ONNX text
Severity: S3
Where: `StateManager` failure outcome (the fix of QA-JOURNEYS-1), delivery `detail`, user-facing log.
Steps: start and stop a recording about 50 ms apart (`recording.toggle` twice with a 50 ms pause; a real double press of the hotkey does the same).
Expected: "recording too short" or the usual "No speech detected", nothing technical.
Actual: `delivery {outcome: "failed", detail: "Could not transcribe the recording (the speech model failed, this was not silence): The model failed while transcribing: [ONNXRuntimeError] : 2 : INVALID_ARGUMENT : Non-zero status code returned while running Conv node. Name:'/encoder_embed/conv/conv.7/Conv' Status M..."}`, the same text as a user-facing ERROR line. 150 ms gives "No speech detected", 300 ms and more transcribe. A recording of no samples is handled well ("Nothing was recorded: no audio came from the microphone"). Reproduced 3 of 3 at 50 ms (also seen at "0.0 s").
Suspected cause: the model gets fewer samples than its front end accepts and the new failure path prints the exception text; short buffers should be padded or reported as too short before the model is called.
Status: FIXED - `StateManager` treats a recording under 0.3 s as "too short" (warning in the log, `delivery {outcome: "failed", detail: "The recording was too short to transcribe. Speak a little longer before you stop."}`, the model is not called, nothing kept); `OnnxAsrBackend` pads any buffer under 8000 samples with silence (files too), and a model failure no longer carries the runtime exception text in its message (`app/state_manager.py`, `app/backends/onnx_backend.py`); verified by `test_a_recording_too_short_to_be_speech_is_not_a_model_failure`, `test_a_short_buffer_is_padded_before_the_model_sees_it`, `test_a_failed_transcription_carries_no_runtime_text`; repro re-run by hand on a real runtime with vosk loaded: `recording.toggle` twice 50 ms apart gave the sentence above and `too short` in `app.log`. The capsule still shows its generic "Delivery failed" copy and the Logs line is English only (NEEDS renderer if a distinct "too short" capsule text is wanted).

### QA-JOURNEYS-R1  A refused hotkey capture toasts "Saved, but not applied yet", and the field shows a binding that is not in force
Severity: S3
Where: `desktop/renderer/src/components/settings/HotkeysCard.svelte` `save()` (the `else if (!result.live)` branch), `settings.set_hotkeys` answer `saved: false`.
Steps: Settings > Hotkeys, two keys mode, click Start, press Ctrl+F9 (= Stop). Same with Cancel := Ctrl+F8.
Expected: nothing is saved, and the screen says so (the conflict sentence, no "Saved").
Actual: the sentence appears under the other field, but also a warning toast "Saved, but not applied yet" (6 s) although `saved` is false and `config.yaml`/`settings.get` still hold the old values; the Start field keeps showing Ctrl+F9 while Ctrl+F8 is live, until the screen is reopened. The renderer never reads `saved`. Reproduced 3 of 3, English and Russian ("Сохранено, но пока не применено").
Suspected cause: `result.saved` ignored; `live: false` with no `live_error` falls into the "not applied" toast.
Status: FIXED - `HotkeysCard.svelte` `save()` honours `saved: false`: the field goes back to `result.settings.hotkey`, an error toast ('Not saved') carries the conflict sentence, no 'Saved' and no 'Saved, but not applied yet'; verified by `tests/settings.test.js` 'does not say "Saved" when the runtime refused the whole change' and by the repro (real Ctrl+F9 in the Start field, Russian UI: Start shows Ctrl+F8 again, `settings.get` unchanged).

### QA-JOURNEYS-R4  Russian: the file-decode failure sentence is not translated
Severity: S3
Where: `lib/transcribe.js` `friendlyError` (the sentence carries the file name, so the lookup of the whole string misses).
Steps: Language Russian, Transcribe, Browse a corrupt or non-audio file.
Actual: "Ошибка: Could not read audio from corrupt.mp3. The file may be damaged, cut short, or not an audio or video file." Reproduced 3 of 3 (corrupt.mp3, notes.txt, fake.wav); "That file is no longer there" and "file type is not supported" are translated.
Status: FIXED - runtime sentences are translated by whole string and by template (`translateRuntime` in `lib/i18n.js`, applied to every RPC error in `lib/rpc.js`, to `friendlyError`, mic-test and hotkey `live_error`/`save_error`); every user-facing string the handlers and `safe_paths` return is in `i18n/ru.runtime.json`; verified by `tests/transcribe.test.js` 'second QA round', `tests/rpc.test.js` and the repro (corrupt.mp3 in Russian: 'Не удалось прочитать звук из файла «corrupt.mp3». ...'). Also the 'Dismiss' label of the notices, the mic-test 'peak/rms' line, decimals and units (`formatNumber`, `localizeFigures`: RTF, MB in model descriptions, RAM, sizes, seconds): `tests/text.test.js`, `tests/history.test.js`. Left as designed: runtime log lines, user data (preset names), a status text created before a language switch.

### QA-JOURNEYS-R5  The Microphone select does not follow a device change made by another client
Severity: S4
Where: `lib/settings.js` (the `settings` event re-reads `settings.get`, not `devices.list`; the select reads `devices.current`).
Steps: Settings open on the Microphone; `devices.select {device: 1}` from elsewhere.
Actual: `settings.get` and `devices.list` say 1, the select keeps showing "[0] ..." and a later edit on the stale page overwrites. Other settings follow. Reproduced 1 of 1.
Status: FIXED - `lib/settings.js` re-reads `devices.list` on a `settings` event that names `audio.device`, on reconnect, and `Settings.svelte` on window focus; verified by `tests/settings.test.js` 'follows a microphone chosen elsewhere' and the repro (`devices.select` over RPC while Settings is open: the select followed and went back to 'System default').
Status: NEEDS renderer - the runtime already emits `settings {keys: ["audio.device"]}` after `devices.select` (tested at `tests/server/test_settings.py`, the `audio.device` event assertion); the screen must re-read `devices.list`/`devices.current` on that event, not only `settings.get`.

### QA-JOURNEYS-R6  The strip says "No model yet" while a model is on disk and only not loaded
Severity: S4
Where: status strip. Steps: QA-JOURNEYS-7 repro; before pressing Load the strip reads "No model yet / Open Models", the card reads "Not loaded". The wording is wrong for "installed, not loaded" (Transcribe says "download one, or load the one you chose" correctly). Reproduced 1 of 1.
Status: FIXED - the strip reads `models.state` (`active` with weights in `cached`): 'Model not loaded' with a Load action (`models.select`) when the model is on disk, 'No model yet' with Open Models only when nothing is; Transcribe's banner title follows the same rule; verified by `tests/status.test.js` (two tests) and the repro (weights moved away at start, put back: strip 'Модель не загружена / Загрузить', click loads, strip shows the model).

### QA-JOURNEYS-R7  After a failed Browse the identity line still names the previously failed file
Severity: S4
Where: Transcribe. Steps: Browse `empty.wav` (fails), then Browse another file with no model loaded: the error is shown for the new file but the identity card keeps "empty.wav / Failed". Also two notices (a "No model yet" banner and the error) say the same thing at once. Reproduced 2 of 2.
Status: FIXED - a run refused before it starts no longer restores a failed file's identity (`lib/transcribe.js`), and the 'No model yet' banner is hidden while the refused-run notice (same button) is shown; verified by `tests/transcribe.test.js` 'does not keep naming a file that failed'. Not re-run in the real UI: the repro needs a model that becomes unloaded after a failed run.

### QA-JOURNEYS-R8  The hotkey conflict message names a mode that does not exist under that name
Severity: S4
"Switch to Toggle mode if one hotkey should do both" / «Включите режим "Переключение"», while the radio is "One key: press to start and stop". Reproduced 3 of 3.
Status: NEEDS Python - the sentence is the English template from `app/hotkey_rules.py` ('Switch to Toggle mode ...'); the renderer only translates it. Rename the mode in the sentence to 'One key: press to start and stop' (or the radio to match) there and in `app_ru.ts`.
Status: FIXED - `app/hotkey_rules.py` now says `Choose "One key: press to start and stop" if one hotkey should do both` (the radio's own label, Qt and Electron alike); `app/i18n/app_ru.ts` and `desktop/renderer/src/i18n/ru.json` regenerated with `scripts/update_translations.py` and `scripts/export_translations.py` (the Russian sentence names «Одна клавиша: нажатие запускает и останавливает запись»; the missing Russian for "The push-to-talk key matches another hotkey" was added on the way); verified by `test_capturing_the_stop_key_into_start_is_refused_and_nothing_changes` and `test_stop_equal_to_start_points_at_the_one_key_mode` in `tests/server/test_settings.py` (message contains the mode label, no "Toggle").

### Observation, not counted as a defect
- `INFO Transcribed: <the user's words>` is written to `app.log` and to the Logs view for every dictation. FR-016 allows what the Qt application already allows, and Qt logs it too; flagging it for the security tester.

## Covered, no defect

- Plain-tab connection loss and recovery (QA-JOURNEYS-4), wrong port at load: "The engine stopped" dialog, no blank window.
- Real global hotkey start/stop with a unique binding; settings (theme, palette, text size, language, hotkeys, preset with key, max duration, clipboard) persistent across a graceful restart.
- API key flow: typing, saving on blur and on shortcut navigation, never echoed, clear, new key replaces.
- Accessible names on all screens; Escape and focus return on dialogs; Cmd+1..6.
- 322 s file and 35 s dictation complete; rapid toggling and dictation during a file run end idle.
- Export refuses the app's own folder with a toast; a normal folder writes the file.

## Not tested, and why

- Capsule, tray, close-to-tray, native dialogs, real file drag from Finder, OS file open, `backend.restart` with a new port/token: Electron only (the shell tester's area).
- Download progress, Cancel of a successful long download, "Start dictating" after a real download: needs the network.
- A real recorder-open failure with mute on (QA-JOURNEYS-2 second branch): no way to provoke it with this hardware.
- Skip silence (silero VAD): downloads a model. Permission banners (macOS grants belong to the terminal).

## Result table

| ID | Result |
| --- | --- |
| QA-JOURNEYS-1 | PASS |
| QA-JOURNEYS-2 | PASS (failed-start unmute branch not reproducible here) |
| QA-JOURNEYS-3 | PASS (toast wrong, R1) |
| QA-JOURNEYS-4 | PASS |
| QA-JOURNEYS-5 | PASS |
| QA-JOURNEYS-6 | PASS |
| QA-JOURNEYS-7 | PASS |
| QA-JOURNEYS-8 | FAIL on retry (R3); copy itself PASS |
| QA-JOURNEYS-9 | PASS |
| QA-JOURNEYS-10 | PASS |
| QA-JOURNEYS-11 | FAIL (Russian text, R4) |
| QA-JOURNEYS-12 | FAIL (not fixed) |
| QA-JOURNEYS-13 | PASS (mic select, R5) |
| QA-JOURNEYS-14 | PASS |
| QA-JOURNEYS-15 | PASS |
| QA-JOURNEYS-16 | PASS (decimals, "MB", log lines, History column still open) |

## New defects, ranked

1. QA-JOURNEYS-R3 (S2) A load after a failed load never finishes; first-run and Models sit on "Starting..." until Cancel.
2. QA-JOURNEYS-R2 (S3) A 50 ms recording (hotkey double tap) is a "model failed" outcome with raw ONNX text in the delivery detail and the log.
3. QA-JOURNEYS-R1 (S3) A refused hotkey capture toasts "Saved, but not applied yet" and the field shows a binding that is not live.
4. QA-JOURNEYS-R4 (S3) Russian: decode failure sentence stays English.
5. QA-JOURNEYS-R5, R6, R7, R8 (S4) Microphone select does not follow an outside change; strip says "No model yet" for an installed model; stale identity line after a failed Browse; conflict message names a mode that is not called that.

Everything I started is stopped: runtime (18303), Vite (5603), fake LLM (18913), my Browser tab; the system output is unmuted. Left behind outside `qa/`: about fifteen of my own entries in `<worktree>/logs/transcription_history.jsonl` and lines in `<worktree>/logs/app.log` (shared dev paths, QA-JOURNEYS-12), the system clipboard contents, and the scratch directory `/private/tmp/claude-501/-Users-justcomex-Documents---------pet-lazy-to-text--claude-worktrees-llm-reasoning-tokens-config-624055/36839e4b-2af5-4aaf-8ca3-57be3ba743eb/scratchpad/j`.
