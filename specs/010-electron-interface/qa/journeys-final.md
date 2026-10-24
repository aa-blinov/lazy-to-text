# QA final round: user journeys (area: journeys)

Tester: journeys (round three). Date: 2026-10-24. Build: worktree `llm-reasoning-tokens-config-624055`, app 0.1.23, HEAD `1ec7d86` plus uncommitted fixes.

## How this was run

- Own runtime on port 18503 (`--dev --dev-port 5803 --no-single-instance --no-stdin-watch --token devtoken --data-dir <scratch>`), own Vite on 5803, own Browser tab (a second tab only for `overlay.html`, to read the capsule). Scratch: `.../scratchpad/jf` with `data` / `data2` / `data3` (three separate profiles, each with its own `config.yaml`, `logs/app.log`, history) and a scratch hub (`storage.models_dir` -> `jf/hubroot`, `vosk-ru-small` copied in). `HF_HUB_OFFLINE=1` for every runtime after the first hour (see "Mistake" below).
- Real microphone with speech from `say -v Milena` through the speakers; real global hotkeys (Ctrl+Option+F5/F6 sent through System Events) started and stopped the dictations. Other testers' runtimes were playing speech on the same machine, so the microphone path was noisy and Vosk Small output on it is not evidence about the app (see "Not tested").
- A browser tab has no `window.l2t`. For Browse, Save, Export and the replace-confirm I injected a stub (`openFile`, `saveFile`, `confirm`, `pathForFile`, `clipboard`) after load and removed it for the in-window dialogs. So: the real native dialogs, the capsule window, tray, `backend.restart` and a drop of a real file from Finder were NOT exercised. The "overwrite" checks below are the runtime half (`files.save_text`, `history.export` with `overwrite: true`) behind a stubbed dialog; the OS dialog's own "replace?" prompt is not tested.
- Test files (all under `.../scratchpad/jf/files`): `d30.aiff` 30.5 s speech, `f67.wav` 62 s (not 67; Milena at -r 110 would not stretch further), `long.wav` 89 min (171 MB), plus `corrupt.mp3`, `notes.txt`, `empty.wav`, `fake.wav`.
- Mistake of mine, disclosed: I started the second runtime without `HF_HUB_OFFLINE=1`, and a `models.select whisper-base` (testing "busy") began a real download. I cancelled it within 17 s; 44 KB of metadata files had been written to my scratch hub and I deleted them. No model was downloaded.

## Retest of the failed originals and R1..R8

| ID | Result | Evidence |
| --- | --- | --- |
| QA-JOURNEYS-8 first-run download failure, retry | PASS | No-model profile, `HF_HUB_OFFLINE=1`. First-run Download -> "The download did not finish. Nothing was saved. Check that this computer is online, then press Try again." Pressed Try again 3 more times: each ended in about 1 s with the same sentence (4 x "Failed to load gigaam-v3-ctc model" in `app.log`, `models.state` idle, `last_load.outcome: error` with a `reason` sentence). Same on Models: Download pressed 4 times, each fails, one toast, never stuck on "Starting". Russian: "Загрузка не завершилась. Ничего не сохранено. Проверьте, что компьютер в сети, и нажмите «Повторить»." |
| QA-JOURNEYS-11 raw error text | PASS | Browse `corrupt.mp3`, `notes.txt`, `empty.wav`, `fake.wav`: English "Could not read audio from X. The file may be damaged, cut short, or not an audio or video file."; Russian "Не удалось прочитать звук из файла «X». Файл может быть повреждён, оборван или не быть аудио- или видеофайлом." Missing file and a folder: "Этого файла больше нет." Relative path, URL, `file://`, `~/x.wav`: `bad_path`, "That is not a full path to a file." No `Subprocess error:`, no exception class, no ONNX text. Other sentences that still leak (F2, F3) are not file-decode ones. |
| QA-JOURNEYS-12 dev history/log shared | PASS | Three runtimes with `--data-dir`: `config.yaml`, `logs/app.log` and `logs/transcription_history.jsonl` appeared under each data dir; the worktree has no `logs/` directory and its `config.yaml` is untouched (mtime 11:34, `git status` shows only QA files). History of one profile did not appear in another. Remaining condition, documented in the guide: models root is not moved, `storage.models_dir` has to be set (I set it). |
| QA-JOURNEYS-R1 refused hotkey: no "Saved", field reverts | PASS | Real key presses in the capture field: Start := Ctrl+Option+F6 (= Stop) and Cancel := Ctrl+Option+F5 (= Start). Start field went back to Ctrl+Option+F5; toast "Not saved" with the conflict sentence; no "Saved", no "Saved, but not applied yet"; `settings.get` and `config.yaml` unchanged; `aria-invalid` only on the field the sentence names. Also set all three hotkeys of a fresh profile by keyboard only (Enter on the field, chord, next field): saved and live. |
| QA-JOURNEYS-R2 50 ms double tap | PASS (runtime), see F1 | `recording.toggle` twice with 50 ms, 200 ms: `delivery {outcome: failed, detail: "The recording was too short to transcribe. Speak a little longer before you stop."}`, WARNING "The recording was too short to transcribe (under 0.3 s) - nothing was pasted." in the log, no ONNX text, model not called. 400 ms goes through the model. 0 ms gives "Nothing was recorded: no audio came from the microphone." (accurate for 0 samples). The sentence reaches the user only in the Logs (English), not the capsule (F1). |
| QA-JOURNEYS-R3 retry after a failed load | PASS | See QA-JOURNEYS-8; also `models.select` of the same alias 5 times in a row through Models and first-run, every attempt ended `idle`. |
| QA-JOURNEYS-R4 Russian runtime sentences | PASS for the decode sentence, residue in F2, F3 | Every screen walked in Russian (Transcribe, Models, History, Post-processing, Settings, Logs, Storage dialog, About, Clear confirm, first-run, engine-stopped dialog): nothing in English except technical names, model ids, "Hugging Face", palette names, user data (preset "Default"), Logs lines (by design). Failures I provoked in Russian: bad file, unsupported (dropped `.txt`: "That file type is not supported." translated), no model, bad path, bad address (`not a url`: "В адресе не должно быть пробелов и переводов строк."; `ftp://...`: "Адрес должен начинаться с http:// или https://, например http://localhost:11434."), unreachable server, engine down, save outside allowed folders. Untranslated: F2, F3. A decimal with a dot remains in a model description ("на 1.6 пункта"). |
| QA-JOURNEYS-R5 Microphone select follows | PASS | Settings open: `devices.select 1` from outside -> select showed "[1] Микрофон MacBook Pro" within 1.5 s; `devices.select null` -> "System default". `-1` is refused with `device_failed` (not a way to reset). |
| QA-JOURNEYS-R6 "No model yet" vs "Model not loaded" | PASS | Weights moved away before start, persisted model vosk: after putting them back with the runtime running, strip "Модель не загружена / Загрузить", Transcribe banner "Модель не загружена"; the strip's Load button loaded it ("Vosk Small ... готова к работе"). With nothing selected and nothing on disk: strip "No model yet / Open Models", banner "No model yet". Observation (not counted): with nothing selected but weights on disk the strip still says "No model yet". |
| QA-JOURNEYS-R7 stale identity after a failed Browse | PASS | `empty.wav` fails (identity "empty.wav / Error"), runtime stopped, weights moved away, runtime started, Browse `short.wav`: identity line and old file gone, one notice only ("Модель ещё не загружена..." with Open Models). |
| QA-JOURNEYS-R8 hotkey conflict wording | PASS | Toast and field text: `Stop is the same as Start (ctrl+alt+f6). Choose "One key: press to start and stop" if one hotkey should do both.` (the radio's own label). The key name is printed raw (lowercase `ctrl+alt+f6`) while the field shows "Ctrl + Option + F6": cosmetic. |
| QA-JOURNEYS-4 engine stopped, auto-reconnect (re-run on the new build) | PASS | Recording running, `kill -9` of the runtime: within about 4 s the alertdialog "Движок остановился" (`aria-modal`, focus inside, log path, Повторить); the capsule page went empty (not stuck on recording); worker processes exited with it. "Повторить" with the engine down: "Движок не вернулся. Попробуйте ещё раз." Runtime restarted on the same port: dialog closed by itself, strip live, state idle, language and screen kept. |
| Save/export with overwrite (stubbed dialog) | PASS | Transcribe "Save .txt" to an existing file: replaced (204 -> 1497 bytes, UTF-8), status "Saved: ...". Edited transcript saved as edited. History export to an existing file: replaced. Refused with a sentence: folder, wrong extension (`.docx`), missing folder, `/System/...`, app data dir. Cancel from the dialog: nothing happens. |

## Fresh-profile pass (regressions)

| Journey | Result |
| --- | --- |
| 1 First run | Empty hub: first-run (Choose / Download / Learn the key), failed download with Try again/Back, "Set up later", then Models. After putting the weights in place, "See all models instead" (by keyboard) opened Models; Select by keyboard loaded Vosk Small, strip "Current model: vosk-ru-small / Engine: CPU". The success step "Learn the key" needs a real download: not reached. |
| 2 Dictation, 30 s | Real hotkey start, 30.5 s of speech played, real hotkey stop: capsule page "RECORDING / Speak now / 00:12" (clock advancing), strip "RECORDING" with the level meter, then idle; history entry duration 34.0 s, delivery "copied" (auto-paste off). Text accuracy in this room was poor and varied run to run (see Not tested); the same audio as a file transcribed with all 56 words. Post-processing with a fake LLM: "FAKE: ..." delivered; server killed: raw text delivered with the "Check the post-processing preset" line. |
| 3 File, 62 s | 116 words for 114 spoken, 0.23 s. Edit by typing -> "117 words . Edited". Browse another file: confirm "Replace the edited transcript?"; Keep editing kept the text, Replace replaced it. Copy put the edited text on the (stub) clipboard. 89 min file: done in 18.5 s; a second short file queued behind it and finished after. |
| 5 Post-processing | Server, model and key typed with the keyboard: key saved on leaving the field, field cleared, "A key is saved. Type a new one to replace it."; key not in the DOM, not in `app.snapshot`/`presets.get`. It is in `config.yaml` in clear text (Qt does too; for the security tester). Test connection against the fake server: "The model answered in 0.0 s." Enable by keyboard (Space) works. |
| 6 Settings | Auto-paste switch by Space; hotkeys by keyboard; theme, palette, text size 125 %, max duration, clipboard, sound cues set; `settings.get`, `presets.get`, `history.list` byte-identical across a graceful restart; `models.state` differs only in `last_load`. Light + Nord + 125 % at 900x600: `scrollWidth == clientWidth` on all six screens. |
| Keyboard only | Cmd+1..6 switch screens; accessible name on every focusable control of all six screens (0 unnamed, no positive tabindex); focus ring on a focused control is a 2 px solid outline; Delete-model confirm opens on the keyboard, Escape closes it and focus returns to the Delete button; hotkey capture, switches, Select/Download by Enter/Space. Gap: F6. |

## New defects

### QA-JOURNEYS-F1  A too-short recording says nothing useful on screen; the one good sentence is in the log, English only
Severity: S3
Where: `desktop/renderer/src/components/capsule/copy.js` (`failed` branch), runtime log line.
Steps:
1. Runtime with a model, Russian interface. Open `overlay.html` (the capsule page) in a tab.
2. `recording.toggle` twice, 100 ms apart (a double tap of the hotkey does the same).
Expected: the capsule or a toast says the recording was too short and to speak longer (the runtime sends exactly that sentence in `delivery.detail`).
Actual: the capsule reads "НЕ УДАЛОСЬ ДОСТАВИТЬ / Ничего не вставлено. Причина в журнале." (same words for every failure). In Logs the reason is "The recording was too short to transcribe (under 0.3 s) - nothing was pasted.", English in a Russian window, followed by an unrelated WARNING "Audio looks silent (peak<0.01). Wrong microphone selected, muted in Windows Sound settings, or input gain too low?" on a Mac, which sends the user to the microphone.
Evidence: `delivery` event `{"outcome":"failed","detail":"The recording was too short..."}`; capsule page text above; `data2/logs/app.log`. Reproduced 3 of 3.
Suspected cause: the capsule ignores `detail` for `failed` (the developer note on QA-JOURNEYS-R2 already says NEEDS renderer).
Status: FIXED - the capsule shows the runtime's `delivery.detail` (translated through `translateRuntime`) as the body of a failed delivery, up to two lines, with the title "Recording too short" for `kind: 'too_short'`; the main window also raises a toast with the same sentence (`App.svelte`, `components/capsule/copy.js`, `Overlay.svelte`, `ru.shell.json`, `ru.runtime.json`). Verified by `capsule.test.js` (copy, Russian capsule) and `keyboard-toasts.test.js` ('says why in a toast'); repro re-run by hand on a restarted runtime: two `recording.toggle` calls 150 ms apart show "ЗАПИСЬ СЛИШКОМ КОРОТКАЯ / Запись слишком короткая для расшифровки. Говорите чуть дольше..." on `overlay.html` and a toast in the window. The "Windows Sound settings" warning is the Python side.
Status: FIXED (runtime part) - the `delivery` event of a too-short recording carries `kind: "too_short"` besides `detail`; the "muted in Windows Sound settings" wording is now per platform (macOS: "System Settings > Sound"). Verified by `test_a_too_short_recording_reports_its_kind_to_the_runtime`, `test_the_runtime_forwards_the_kind_in_the_delivery_event`, `test_the_silent_microphone_hint_names_the_platforms_own_settings`. NEEDS renderer: the capsule must read `kind` and show `detail`.

### QA-JOURNEYS-F2  Two save/export refusals are partly or wholly English in the Russian interface
Severity: S3
Where: `app/server/safe_paths.py` lines 182 and 189-193, `ru.runtime.json`.
Steps: Russian UI. Transcribe a file, "Save .txt" (or History > Export), choose `/System/x.txt` (any folder that belongs to the system or an installed application); then choose `.../out/` (a folder) or `x.docx`.
Expected: Russian sentences.
Actual: toast/status "Не удалось сохранить: That folder belongs to an installed application or the system. Choose another place." (whole sentence English; the neighbouring "Эта папка принадлежит приложению. Выберите другое место." is translated) and "Выберите имя текстового файла с окончанием .txt, .md, .markdown or .text." (the list is joined with an English "or"). Same in the History export toast. Also the exported history file itself is English ("Transcription History Export", "Date:", "Duration:") in a Russian window.
Evidence: scratch `out/` runs above. Reproduced 3 of 3 for each sentence.
Suspected cause: the `/System`-class sentence has no entry in `ru.runtime.json`; the extension list is built with an English "or" before it is substituted into `%1`.
Status: FIXED (renderer half) - `ru.runtime.json` has both "That folder belongs to an installed application [or the system]" sentences; the extension list inside "Choose a text file name that ends in %1." is written with "или" (`translatePart` in `lib/i18n.js`); the exported history file is built in the renderer in a non-English interface (`exportText` in `lib/history.js`, written by `files.save_text`; English still uses `history.export`). Verified by `i18n-runtime.test.js`, `rpc.test.js`, `history.test.js` ('writes the exported file in the interface language'). The exported file of the Qt app stays English (`app/history_manager.py`).
Status: FIXED (runtime part) - the `/System`-class sentence has a Russian entry in `ru.runtime.json`; the list joined with an English "or" is built in `check_output_path` and is still English (the template `Choose a text file name that ends in %1.` has its entry, the list inside %1 is not translated): NEEDS renderer. The exported history file itself stays English as in Qt.

### QA-JOURNEYS-F3  "Test connection" failure shows the raw error, with the exception class, in both languages
Severity: S3
Where: `presets.test` message, Post-processing screen; also the log line "Post-processing failed (...)".
Steps: Post-processing, server `http://127.0.0.1:1`, any model name, Test connection.
Expected: a sentence for the user ("Could not reach the server at http://127.0.0.1:1. Check the address and that it is running."), translated.
Actual: `could not reach http://127.0.0.1:1/api/chat (ConnectionRefusedError)`, lowercase, English in the Russian UI, with a Python exception class. Same text inside the dictation log line (`...failed (could not reach http://127.0.0.1:18913/api/chat (ConnectionRefusedError))`). QA-JOURNEYS-11 removed exactly this kind of plumbing from the file path.
Evidence: screenshot text in Russian window; `data2/logs/app.log`. Reproduced 3 of 3.
Status: FIXED (renderer half) - the Test connection result and the address note go through `translateRuntime`; `ru.runtime.json` has every new connection sentence ("The server did not answer at %1. Is it running?", "The server at %1 did not answer in time.", "The server answered with an error (HTTP %1).", "The server refused the key.") and the old lowercase ones as a fallback. Verified by `i18n-runtime.test.js`; repro re-run by hand in the Russian UI with `http://127.0.0.1:1`: "Сервер 127.0.0.1:1 не отвечает. Он запущен?".
Status: FIXED - `app/llm/client.py` answers with stable sentences: "The server did not answer at <host>:<port>. Is it running?", "The server refused the key.", "The server answered with an error (HTTP n).", "The server answered with a redirect (HTTP n), which is not followed.", "The server at <host>:<port> did not answer in time."; Russian entries added. Verified by `test_nothing_listening_says_the_server_did_not_answer_and_names_host_and_port`, `test_a_refused_key_has_its_own_sentence`, `test_other_http_failures_say_the_server_answered_with_an_error`, `test_a_credential_in_the_address_never_reaches_the_sentence`. The log line "Post-processing failed (%s)" embeds the English sentence (NEEDS renderer if nested lines are to be translated).

### QA-JOURNEYS-F4  Error toasts never go away and pile up
Severity: S4
Where: Toaster usage for `model_load` and export failures.
Steps: no-model profile, Download fails (toast); load another model successfully, kill and restart the engine, switch screens.
Expected: the failure toast expires or is replaced by the success of the same model action.
Actual: "Could not load GigaAM v3 CTC" stayed in the bottom-right corner for more than ten minutes, across a successful load of Vosk and an engine restart; three "Export failed" toasts stacked on top of each other over the bottom of the Post-processing form until closed by hand. Seen 3 times.
Status: FIXED - every toast goes through `lib/toast.js`: a duration of 0 (or none) on a danger or warning toast becomes 8 s, success and neutral 4 s, the stack holds three, the Toaster is `max=3`, bottom-right above the status strip, in the library's `aria-live` region. Verified by `keyboard-toasts.test.js` (expiry, cap, region, no direct `@monos/ui` toast import anywhere); repro re-run by hand: a failed delivery toast was there at 6.5 s and gone at 9 s.
Status: NEEDS renderer - toast lifetime is the renderer's.

### QA-JOURNEYS-F5  Cancelling a model load waits for a running file transcription
Severity: S4
Steps: Transcribe the 89 min file; while it runs select another model (`models.select whisper-base`), then Cancel.
Actual: "Cancelling model load..." at 16:59:17, the load abandoned at 16:59:29 when the file finished (about 12 s). The window stays on a loading state with Cancel pressed. Selecting a model also cancels a running recording silently (log "Cancelling recording to switch to ... model"; same as Qt). Reproduced 1 of 1.
Status: FIXED - the worker's command loop no longer runs transcriptions inline: they run one at a time on a worker thread, so `cancel_load`, status and model switches are answered at once (`app/backends/subprocess_worker.py`). Verified by `test_a_cancel_is_answered_while_a_file_is_being_transcribed` (the cancel reply arrives while the file is still running).

### QA-JOURNEYS-F6  Switching screens by the keyboard does not move the focus
Severity: S4
Steps: Cmd+3, Tab; Cmd+1, Tab.
Actual: the first Tab goes to the next item of the sidebar (Models, then History), not into the screen; a keyboard-only user passes up to six sidebar stops each time and there is no skip link. The earlier retest recorded "first Tab goes to the first control" (that was after a mouse click). 2 of 2.
Status: FIXED - Cmd/Ctrl+1..6, Cmd/Ctrl+, and a menu navigation focus the new screen's heading (`tabindex=-1`, `lib/focus.js`), and a "Skip to content" link is the first Tab stop (visible on focus). Verified by `keyboard-toasts.test.js`; repro re-run by hand: from a sidebar button, Ctrl+3 left focus on `H1 History tabindex=-1`, Ctrl+5 on `H1 Settings`.
Status: NEEDS renderer - keyboard focus after a screen switch.

### QA-JOURNEYS-F7  A 0.4 s accidental recording pastes a stray letter
Severity: S4
Steps: auto-paste on, `recording.toggle` twice 400 ms apart in a quiet room.
Actual: `delivery {outcome: pasted, text: "с"}` and a history entry "с" (Vosk Small emits a letter for near silence). The 0.3 s limit is below that. Reproduced 1 of 1; model dependent.
Status: FIXED - see QA-RUNTIME-F10: a one-letter result from under 1 s of audio is dropped, so a 0.4 s accidental recording pastes nothing. Verified by `test_a_stray_one_word_result_is_not_pasted[с-0.4-0.05]`.

## Covered, no defect

- Failed model load and retries on first-run and on Models; Models Cancel; Delete confirm by keyboard with Escape.
- Real global hotkey start/stop; capsule page states (recording clock, failed); hotkey capture by keyboard; conflict refusal.
- Engine killed during a recording: dialog, retry message, auto-reconnect, no stuck recording state, no orphan worker.
- Persistence across restart of settings, presets, history; light/Nord/125 % at 900x600 without horizontal overflow.
- Accessible names on all controls; dialogs trap focus and return it.
- Output mute untouched in this pass (`output muted` false at the end).

## Not tested, and why

- Real native open/save/confirm dialogs, the capsule window, tray, close-to-tray, `backend.restart` with a new port and token, drops from Finder: Electron only; a stub stood in for the dialogs.
- "Learn the key" step of first-run and a successful download with progress: needs the network (not allowed).
- ASR accuracy of dictation: other testers' speech and the room made the microphone path unreliable (the same 30 s audio gave a different tail on each of two runs, and nearly clean as a file). The chunk boundary of Vosk (15 s) on a long dictation could not be separated from the noise; not reported.
- QA-JOURNEYS-2 (stale microphone while muting) and QA-JOURNEYS-16 handler items were not re-run: nothing under them changed in the files I read; their last result stands.
- Packaged app: I did not wait for `rebuild.done` (it does not exist yet, nothing here uses the packaged build).

## Result table

| ID | Result |
| --- | --- |
| QA-JOURNEYS-1 long dictation / long file | PASS (34 s dictation delivered; 62 s and 89 min files) |
| QA-JOURNEYS-2 stale microphone, mute | PASS (earlier result, not re-run) |
| QA-JOURNEYS-3 conflicting hotkey | PASS |
| QA-JOURNEYS-4 runtime death | PASS |
| QA-JOURNEYS-5 drop over edited transcript | PASS |
| QA-JOURNEYS-6 no-model state | PASS |
| QA-JOURNEYS-7 active but not loaded | PASS |
| QA-JOURNEYS-8 first-run download failure | PASS |
| QA-JOURNEYS-9 wrong screen named in log | PASS |
| QA-JOURNEYS-10 175 % text at 900x600 | PASS (125 % and light/Nord re-checked; 175 % not re-run) |
| QA-JOURNEYS-11 raw `Subprocess error:` text | PASS (but see F2, F3) |
| QA-JOURNEYS-12 shared dev history/log | PASS |
| QA-JOURNEYS-13 settings do not follow | PASS |
| QA-JOURNEYS-14 Logs mixes two runtime lives | PASS (Logs after restart: 21 lines, new life only) |
| QA-JOURNEYS-15 unnamed controls | PASS |
| QA-JOURNEYS-16 small items | PASS (partial: decimal dot in a model description, log lines English, exported file English) |
| QA-JOURNEYS-R1 | PASS |
| QA-JOURNEYS-R2 | PASS (runtime); sentence not shown on screen, F1 |
| QA-JOURNEYS-R3 | PASS |
| QA-JOURNEYS-R4 | PASS (decode sentence); other sentences F2, F3 |
| QA-JOURNEYS-R5 | PASS |
| QA-JOURNEYS-R6 | PASS |
| QA-JOURNEYS-R7 | PASS |
| QA-JOURNEYS-R8 | PASS |

## New defects, ranked

1. QA-JOURNEYS-F1 (S3) Too-short recording: generic capsule text, the real sentence only in an English log, followed by a "Windows Sound settings" warning on a Mac.
2. QA-JOURNEYS-F2 (S3) Two save/export refusal sentences English or half English in Russian; exported history file English.
3. QA-JOURNEYS-F3 (S3) Test connection and the post-processing log show a raw error with `ConnectionRefusedError`, English in both UIs.
4. QA-JOURNEYS-F4 (S4) Error toasts never expire and stack over the form.
5. QA-JOURNEYS-F5 (S4) Cancel of a model load waits for a running file transcription.
6. QA-JOURNEYS-F6 (S4) Cmd+N does not move focus; first Tab walks the sidebar; no skip link.
7. QA-JOURNEYS-F7 (S4) A 0.4 s accidental recording pastes "с".

Everything I started is stopped: runtime (18503), Vite (5803), fake LLM (18913), both of my Browser tabs; system output is unmuted. Left behind outside `qa/`: only my scratch directory `/private/tmp/claude-501/-Users-justcomex-Documents---------pet-lazy-to-text--claude-worktrees-llm-reasoning-tokens-config-624055/36839e4b-2af5-4aaf-8ca3-57be3ba743eb/scratchpad/jf` and the system clipboard (the real hotkey dictations copied text; the first 0.4 s test also pasted one letter into whatever window had focus). While running a batch of key presses without a tab id, six Tab presses went to another tester's tab (`seed`, port 5701); they only moved focus.
