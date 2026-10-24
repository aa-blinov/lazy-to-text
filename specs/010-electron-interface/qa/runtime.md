# QA: runtime (app/server, RPC API, domain code it calls)

Tester: runtime area. Build under test: worktree at `a7421c2` (no local changes). Runtime driven over loopback HTTP with a small
urllib client, on port 18101, token `devtoken`. Each run used its own scratch directory with a **copy** of `app/` and `pyproject.toml`
(so config, logs, history and models were isolated from the repo and from the user's profile), started with
`.venv/bin/python -m app.server --no-single-instance --no-stdin-watch`. Real model: `vosk-ru-small` (copied from `models/hub`).
Real microphone: speech was synthesised with `say -v Milena`, converted with `afconvert`, and played through the speakers with `afplay`
while the runtime recorded. Fakes (forced by the environment): a local fake LLM HTTP server (port 18191) and a local TCP "black hole"
standing in for Hugging Face (proxy env, port 18192), so no model was downloaded. Scripts and raw output are in the scratchpad
(`.../scratchpad/tools`); the key outputs are saved as `qa/evidence/runtime/*.txt`.

Disclosure: one run (`r17`) selected a model whose fake local copy had just been deleted by the race in QA-RUNTIME-12, and the runtime
started a real Hugging Face download of `vosk-ru` before I stopped it (about 69 MB reached the scratch folder, which I deleted).
After that every runtime was started with a dead proxy. The first two runs (before I isolated the copy) wrote to the worktree's
ignored `logs/` folder (`app.log`, two history lines).

Counts: **S1: 5, S2: 4, S3: 6, S4: 8** (23 defects).

---

## S1

### QA-RUNTIME-1  An LLM request that raises anything but `LLMError` makes the dictation vanish; one variant writes the API key to app.log
Severity: S1
Status: FIXED - llm/client.py `complete` converts every exception to LLMError (type only), validates address/key, state_manager `_postprocess_with_llm` catches Exception; verified by tests/test_llm_client_hardening.py, tests/test_state_manager_failure_outcomes.py (any_exception_from_the_llm_step, malformed address, key newline)
Where: `app/llm/client.py` `complete()` (catches only `HTTPError`, `URLError`, `socket.timeout`, `OSError`) and `app/state_manager.py:_postprocess_with_llm` (catches only `LLMError`); everything else lands in the pipeline's outer `except Exception`.
Steps (2 runs each, all reproduced, real dictation with vosk-ru-small, `presets.update` + `llm.set_enabled true`, fake server on 18191):
1. Set the preset `base_url` to `myserver` (any URL without a scheme or colon, also `127.0.0.1`), or `http://127.0.0.1:18191/a b`, or `http://127.0.0.1:18191/ё`.
2. Or set `api_key` to a value with a newline (`abc\ndef`) or non-Latin-1 text (`ключ`) with provider `openai`.
3. Or leave the config valid and make the server answer with garbage that is not HTTP (`GARBAGE\r\n\r\n`), or a malformed chunked body.
4. `recording.toggle`, speak, `recording.stop`.
Expected: the documented contract of `_postprocess_with_llm`: on any failure deliver the raw transcription ("your words reach the window"), as it does for HTTP 401/500, empty or non-JSON replies, timeouts and a refused connection.
Actual: no `delivery` event, nothing on the clipboard, no history entry; log: `Error processing recording: unknown url type: 'myserver/api/chat'` / `...GARBAGE` / `...IncompleteRead(0 bytes read)` / `...URL can't contain control characters` / `...'ascii' codec can't encode character` / `...'latin-1' codec can't encode characters`. Control run with HTTP 500: delivered and in history. The spoken text is lost (the audio buffer is released in `finally`).
Second effect (same cause): with the newline key the exception text is `Invalid header value b'Bearer abc\ndef'`, i.e. the **API key is written to app.log**, `logs.list` and the `log` event (4 occurrences in `r4/logs/app.log`).
Evidence: `qa/evidence/runtime/llm_uncaught.txt`, `qa/evidence/runtime/creds_in_log.txt`.
Suspected cause: catch `Exception` (or add `ValueError`, `http.client.HTTPException`, `UnicodeError`) around the request in `complete()` and raise `LLMError` with the exception type only; strip/validate the key and URL in `presets.update`.
Status: NEEDS core - `complete()` and `_postprocess_with_llm` must treat every exception as a fallback to the raw text (core has added `endpoint_problem`/`key_problem` to `app/llm/client.py`). Handler side FIXED - `presets.update` refuses a malformed address, a key with a line break or non-Latin-1 text, and credentials in the URL at save time (`app/server/handlers/presets.py` `clean_fields`/`address_problem`); verified by `tests/server/test_presets.py::test_a_malformed_address_is_refused_and_nothing_is_saved` (13 addresses) and `::test_an_api_key_that_cannot_be_sent_is_refused_and_never_echoed`; live: `presets.update` with `http://[::1`, `myserver`-style and newline-key values answered `bad_params` with the field, config untouched.

### QA-RUNTIME-2  `models.storage.apply` with a folder inside the models folder and "move" deletes every downloaded model
Severity: S1
Where: `app/server/handlers/models.py:_storage_worker`, `app/utils.py:move_cached_dir`; `models.storage.plan` does not detect it.
Steps (reproduced 2 of 2):
1. Fresh runtime, model `vosk-ru-small` on disk (15 files, 117 MB under `<root>/models`).
2. `models.storage.get` -> `path = <root>/models`. `models.storage.plan {path: "<root>/models/hub"}` -> `{same: false, old_size: 120035116, destination_has_models: false}` (no warning).
3. `models.storage.apply {path: "<root>/models/hub", move: true}`; wait 5 s.
Expected: refuse a destination inside the folder being moved (or inside the current root), or move safely.
Actual: `os.rename` fails with EINVAL, the copy-then-delete fallback copies the tree into itself and then `rmtree`s the source, taking the copy with it. After: 0 files, 0 KB, `models.state.cached` empty. The final event says `phase: done, changed: true`. The user's downloaded models are destroyed and the app reports success.
Evidence: `qa/evidence/runtime/storage_move_into_hub.txt`.
Suspected cause: no containment check between source and destination in `plan`/`apply`/`move_cached_dir`.
Status: FIXED - `models.storage.plan` and `apply` refuse a destination that is inside, or a parent of, the current models folder (links resolved) with `bad_path`; the worker re-checks it; the move is `move_hub` (rename, else copy into a destination that did not exist, compare names and sizes file by file, only then remove the source; a mismatch removes the partial copy and keeps the source) - `app/server/handlers/models.py`; verified by `tests/server/test_models.py::test_a_folder_inside_the_models_folder_is_refused_by_plan_and_apply`, `::test_a_copy_that_does_not_match_keeps_the_original_and_removes_the_partial_copy` and five more; live repro (`storage.apply {path: <root>/hub, move: true}`) answers `bad_path` and the 1000-byte weight file is still there.

### QA-RUNTIME-3  `vosk-ru-small`: any dictation or file longer than about 21 s fails and the words are lost
Severity: S1
Status: FIXED - onnx_backend per-model chunk cap (vosk 15 s, real limit 20.05 s measured), quiet-point cuts, halving retry; verified by tests/backends/test_long_audio_chunking.py and by re-run with the real vosk-ru-small: 67 s file via files.transcribe -> file.done, 60 s dictation through StateManager + real worker -> copied, 1023 chars
Where: `app/backends/onnx_backend.py` `_CHUNK_SAMPLES = 25 s`, model card `vosk-ru-small`.
Steps (reproduced for files at 20 s ok / 22 s, 24 s, 30 s, 60 s, 120 s, 300 s, 600 s, 1200 s, 1 h all failing; and for a live 25.5 s dictation):
1. Runtime with `vosk-ru-small` loaded. `files.transcribe` on a 22 s WAV (any speech; I repeated a 6 s clip).
2. Or dictate for 25 s.
Expected: text, as for 20 s (280 chars). The app caps recording at 300 s by default and the chunker claims to handle long audio.
Actual: `file.failed` with `Subprocess error: TranscriptionError: The model failed while transcribing len22.wav: [ONNXRuntimeError] ... Reshape node ... Input shape:{1,246,16}, requested shape:{-1,2491,4,4}`. Live dictation: `Error processing recording: Subprocess error: TranscriptionError: ...` (same ONNX text, plus a ~25 KB traceback in the log ring), nothing delivered, nothing in history, audio discarded. Any recording past about 21 s with this card is lost, and a 1-hour file cannot be transcribed at all.
Evidence: `qa/evidence/runtime/vosk_21s.txt` (20 s ok, 22 s fails).
Suspected cause: the 25 s chunk is longer than the Zipformer graph accepts; this card needs a smaller chunk. Other cards were not measured (only this model is on disk).

### QA-RUNTIME-4  Credentials in the preset `base_url` (`user:password@host`) go to app.log, `logs.list` and the `log` event
Severity: S1
Status: FIXED - app/log_redaction.py (record class redacts in every sink) + config_manager `_scrub_secrets`; verified by tests/test_log_redaction.py
Where: `app/config_manager.py:update_user_setting` change log (`_redact_for_log` scrubs `api_key`/`token` only; the flat `llm.base_url` and the `llm.profiles` repr print the URL raw). `app/llm/client.py` already has `_safe_url` for exactly this and does not use it here.
Steps (reproduced 1 run, 13 occurrences): `presets.update {profile:{id:"default", base_url:"http://user:PLANTEDPW@127.0.0.1:18191", api_key:"sk-FAKEKEY-9f8e7d6c", ...}}`, then `presets.duplicate`, `presets.update` again, `presets.reset_key`; grep.
Expected: no credential in any log. The planted `api_key` is correctly absent (`'api_key': '<set>'`).
Actual: `Updated setting llm.base_url: 'http://127.0.0.1:11434' -> 'http://user:PLANTEDPW@127.0.0.1:18191'` and the whole profile list with the URL, in `app.log` (13), `logs.list` (13), the `log` events (13) and stderr (13). The key and the HF token (`hf_PLANTEDTOKEN123`) were absent everywhere (0 of 0).
Evidence: `qa/evidence/runtime/creds_in_log.txt`.
Status: FIXED for new values, NEEDS core for stored ones - an address with `user:password@` is refused at save time (`address_problem`), so it is never written or logged; verified by `tests/server/test_presets.py::test_a_malformed_address_is_refused_and_nothing_is_saved[http://user:PLANTEDPW@...]`; live: refused, `PLANTEDPW` 0 hits in app.log and stderr. A value already in config.yaml is still printed by `config_manager._redact_for_log` when it changes (core: scrub URL userinfo there).

### QA-RUNTIME-5  A saved `audio.device` that no longer exists disables hotkeys and recording, and the app cannot recover without a restart
Severity: S1
Status: FIXED (core part) - AudioRecorder falls back to the system default with a user-facing line, never raises in the constructor, set_device raises ValueError for a missing device; verified by tests/test_audio_recorder_stale_device.py. NEEDS handlers - devices.select must validate before writing audio.device (recorder.set_device now raises ValueError; call it before update_user_setting)
Where: `app/audio_recorder.py:_test_microphone` raising in the constructor, `app/server/runtime.py:_build_stack`, `app/server/handlers/devices.py`.
Steps (reproduced 2 of 2): config with `audio.device: 99` (what remains after an unplugged USB or Bluetooth microphone, or an index shift), start the runtime.
Expected: fall back to the system default input and say so; the device list stays usable.
Actual: `app.snapshot.stack_error = "Error querying device 99"`; `recording.toggle` -> `no_stack`; `devices.list` -> `{devices: [], current: null}` (so a picker has nothing to offer); `devices.select {device: 1}` answers `{device: 1}` as a success but `stack_error` stays and `settings.get.capabilities.recording_stack` stays false. No hotkeys, no dictation, no in-app way out (only a restart, which nothing tells the user to do).
Evidence: `qa/evidence/runtime/stale_device.txt`.
Suspected cause: an unknown device index is fatal in the recorder constructor; `devices.select` writes the config but cannot rebuild a stack that never existed.
Status: Handler side FIXED, NEEDS core for the stack - `devices.select` refuses an index that `devices.list` does not offer (`device_failed`, nothing stored or switched) - `app/server/handlers/devices.py`; verified by `tests/server/test_settings.py::test_an_unknown_device_is_refused_and_nothing_is_stored_or_switched` (4 values) and live (`devices.select 99` refused, `audio.device` stays null). Core must still make `AudioRecorder`/`Runtime._build_stack` fall back to the system default when a stored device is gone and rebuild the stack after `devices.select`.

---

## S2

### QA-RUNTIME-6  One mistyped preset address ("http://[::1") bricks every `presets.*` method until config.yaml is edited by hand
Severity: S2
Status: NEEDS handlers - presets.update must validate base_url before saving; core side done: is_local_url never raises, LLMSettings.problem exposes endpoint_problem()/key_problem() for the handler to reuse
Where: `app/server/handlers/presets.py` (`_profile_dict` reads `profile.remote`, which calls `is_local_url` and raises `ValueError: Invalid IPv6 URL`); `presets.update` writes the bad value, then fails while building its reply.
Steps (reproduced 2 runs): `presets.update` with `base_url: "http://[::1"` -> `internal: Invalid IPv6 URL` (but saved). Then `presets.get`, `presets.update` (even with a valid URL), `presets.create`, `presets.activate`, `presets.privacy`, `llm.set_enabled` all answer `internal: Invalid IPv6 URL`; `presets.delete` answers `last_preset`. After a restart `presets.get` still fails. With post-processing enabled each dictation is also lost (QA-RUNTIME-1).
Expected: validate the address on save (a `bad_params` for the field) or tolerate it when reading.
Evidence: `qa/evidence/runtime/preset_bricked.txt`.
Status: FIXED - addresses are validated at save time and a bad stored value is read tolerantly (`base_url_error`, `remote: true`), so no `presets.*` call fails on it - `app/server/handlers/presets.py`; verified by `tests/server/test_presets.py::test_a_bad_stored_address_cannot_make_every_call_fail` and `::test_a_malformed_address_is_refused_and_nothing_is_saved`; live: a config.yaml holding `base_url: http://[::1`, then `presets.get`, `llm.set_enabled`, `presets.create`, `presets.update` all answered normally and the field could be repaired.

### QA-RUNTIME-7  `models.cancel_load` does nothing while a model is loading or downloading
Severity: S2
Status: FIXED (core cause) - SubprocessBackend marks status loading before sending load/change_model and the worker pushes status before replying; verified by tests/backends/test_transcription_errors_across_the_pipe.py (loading before push, worker push order). Not re-run against a real download (no downloads allowed)
Where: `app/state_manager.py:_watch_model_change` + `app/backends/subprocess_backend.py:status()` (cached from async pushes); `cancel_model_change` returns False when `is_model_loading` is already cleared.
Steps (reproduced 4 of 4): runtime with a model loaded, download endpoint pointed at a local black hole; `models.select {alias:"vosk-ru"}` (not on disk) -> `downloading: true, state: model_loading`; wait 2-6 s; `models.cancel_load`.
Expected: `cancelled: true`, config restored, previous model reloaded.
Actual: `{cancelled: false, state: "model_loading", loading: true}` every time; the download keeps running. The watcher polls `backend.status()` right after `change_model`, still reads the previous model's cached `ready`, clears `is_model_loading` and writes **"Successfully switched to vosk-ru model"** to the log (a user-visible line) although nothing has loaded. The `state` event goes `idle` then `model_loading` again. The user cannot stop a mis-picked multi-gigabyte download (only quitting the app does).
Evidence: `qa/evidence/runtime/cancel_load_noop.txt`.
Status: Handler side FIXED, NEEDS core - `models.cancel_load` now asks the backend directly when the state manager's flag is already down but the backend still reports `loading`, clears the flag and reports `cancelled: true` (`app/server/handlers/models.py` `_cancel_in_backend`); verified by `tests/server/test_models.py::test_a_load_the_state_manager_lost_track_of_is_still_cancelled`; a real download was not started (no network by rule). Core: `StateManager._watch_model_change` reads the previous model's cached `ready` right after `change_model` (clears `is_model_loading` early and logs 'Successfully switched to <model>'); it must wait until the new load reports `loading` (or for the status change that belongs to this switch) before it can say ready.

### QA-RUNTIME-8  A file result or a delivery is lost if the renderer is not subscribed at that moment
Severity: S2
Where: `app/server/events.py` (only `state`, `engine`, `resources`, `progress`, `mic_test`, `permissions` are sticky), `app/server/handlers/files.py`.
Steps (reproduced 1 run): no `/events` subscriber (stands for a renderer reload or an SSE reconnect after sleep); `files.transcribe` a 20 s file; wait; connect to `/events`.
Expected: some way to get the outcome (replay, or a method returning the last run).
Actual: the replay carries only the sticky events; `file.done` is gone and there is no `files.*` method that returns a past result. The transcript of a long file transcription is unrecoverable and the screen would wait forever. The same holds for `delivery`, `model_load`, `llm_test`, `model_delete`.
Evidence: `qa/evidence/runtime/lost_file_done.txt`.
Status: FIXED - `files.results` / `files.result` / `files.dismiss` keep the last 12 file runs (running, done, failed) whether or not a window listens; `app.last_events` returns the last `delivery`, `model_load`, `model_delete`, `llm_test`; `models.state.last_load` carries the last load - documented in the contracts; verified by `tests/server/test_files.py::test_a_finished_run_can_be_read_back_with_no_subscriber` (and 5 more), `tests/server/test_core_handlers.py::test_the_last_outcome_events_can_be_asked_for`, `tests/server/test_models.py::test_the_outcome_of_the_last_load_is_part_of_the_state`.

### QA-RUNTIME-9  The LLM timeout is per socket read, so a slow server holds a dictation in `processing` indefinitely and it cannot be cancelled
Severity: S2
Status: FIXED - one wall-clock budget (timeout_s) around the whole LLM exchange; verified by test_a_server_that_drips_bytes_cannot_hold_the_dictation and the never-answering server test
Where: `app/llm/client.py` (`urlopen(..., timeout=settings.timeout_s)`; `response.read` loops), `recording.cancel` returns `cancelled:false` in `processing`.
Steps (reproduced 1 run): preset `timeout_s: 2`, fake server that answers headers with `Content-Length: 100000` and then sends one byte every 0.8 s; dictate.
Expected: the dictation ends after about `timeout_s` with the raw text.
Actual: `state` stays `processing` for more than 65 s (polled every 5 s; the server was set to drip for about 240 s); `recording.toggle` and `recording.cancel` do nothing (`cancelled:false`); no new dictation can start.
Suspected cause: no overall deadline (`time.monotonic` budget) around the read.
Status: NEEDS core - the dictation path (`app/llm/client.py`) needs an overall deadline. Handler side FIXED for the connection test: `presets.test` ends at `timeout_s` + 3 s with a message even when the server drips; verified by `tests/server/test_presets.py::test_a_server_that_never_finishes_answering_ends_the_test_at_the_deadline`.

---

## S3

### QA-RUNTIME-10  Hotkey conflicts are only detected by exact string, and a refused field falls back to a value that is itself a conflict
Severity: S3
Where: `app/hotkey_rules.py:find_conflicts`, `app/server/handlers/settings.py:set_hotkeys/_fallback`.
Steps (reproduced 1 run each):
1. `settings.validate_hotkeys {mode: two_keys, start: "ctrl+shift+a", stop: "shift+ctrl+a", cancel: ""}` -> no error; same for `cmd+f8`/`command+f8`, `alt+a`/`option+a`; Cancel `control+f8` vs Start `ctrl+f8`. `settings.set_hotkeys` saves them (`live: true`).
2. `settings.set_hotkeys {mode: toggle, start: "ctrl+f8"}` (stores Stop = Start), then `{mode: two_keys, start: "ctrl+f8", stop: "", cancel: "ctrl+f10"}` (or omit `stop`).
Expected: the equivalent spellings are conflicts; a refused Stop must not fall back to a value equal to Start.
Actual: (1) accepted. (2) error on `stop` is returned, but the stored Stop (the toggle mirror) is kept, so two-key mode is saved with Stop == Start, which `settings.get` then reads back as `mode: toggle` with `cancel: ctrl+f10` still set. The user chose two keys and ends up in toggle with a stale Cancel.
Status: FIXED - equivalent spellings compare equal (`hotkey_rules.canonical`) and a conflict refuses the whole `settings.set_hotkeys` request (nothing written, nothing applied, `saved: false`), decided on the values that would be stored; verified by `tests/server/test_settings.py::test_other_spellings_of_the_same_key_are_the_same_conflict` (6 cases) and `::test_leaving_toggle_with_an_empty_stop_does_not_store_stop_equal_to_start`; live: `ctrl+shift+a`/`shift+ctrl+a` refused, config unchanged.

### QA-RUNTIME-11  `settings.set` (and every config write) reports success when the config file cannot be written
Severity: S3
Status: NEEDS handlers - ConfigManager.last_write_error now holds the failure text (None on success); settings.set should report it
Where: `app/config_manager.py:_write_config_file` (logs `Error writing configuration`, swallows it), `app/server/handlers/settings.py:set_value`.
Steps (reproduced 1 run): `chmod 444 config.yaml; chmod 555 <dir>`, start, `settings.set {key:"ui.theme", value:"dark"}`.
Expected: an error or `live_error`/warning so the screen can tell the user the change will not survive a restart.
Actual: `{key, value:"dark", live_error:null}`; `app.snapshot` shows `dark`; the file on disk still says `system`; only the log says `Error writing configuration: [Errno 13]`.
Status: Handler side FIXED, NEEDS core for the root cause - `settings.set`, `settings.set_hotkeys` and `settings.reset_hotkeys` now return `save_error` (a sentence) when the settings file or its folder is not writable (`persist_problem`); verified by `tests/server/test_settings.py::test_a_change_that_cannot_be_written_to_disk_says_so`. `ConfigManager._write_config_file` still only logs the failure (core could record it and expose it).

### QA-RUNTIME-12  `models.select` is accepted while the same model is being deleted
Severity: S3
Where: `app/server/handlers/models.py:_select` (does not look at `ctx.deleting`).
Steps (reproduced 2 runs): model B cached and inactive; call `models.delete {alias:B}` and, 10 ms later, `models.select {alias:B}`.
Expected: `busy`.
Actual: `delete` -> `started`, `select` -> `{downloading: false, state: model_loading}`; the delete finishes (`deleted: true`), and the load that follows has to fetch the model again (it started a real download in my run). The card said "not downloading" at click time.
Status: FIXED - `models.select`/`download` answer `busy` while that model, or one sharing its repository, is being deleted or while the models folder is being changed; `delete` and `storage.*` refuse each other and a select that has just started; verified by `tests/server/test_models.py::test_select_is_refused_while_the_same_model_is_being_deleted` and three more.

### QA-RUNTIME-13  A log folder that cannot be opened stops the runtime from starting at all
Severity: S3
Status: FIXED - get_project_logs_path falls back to the user log folder, Runtime.start survives a failing file logger, StateManager survives a history folder error; verified by tests/test_config_wrong_types.py (logs fallback)
Where: `app/bootstrap.py:_install_file_logging` / `app/utils.py:get_project_logs_path`, called from `Runtime.start` before the stack is built.
Steps (reproduced 2 of 2): `logs` is a file (`FileExistsError`) or `logs/` is read-only (`PermissionError ... app.log`), start `python -m app.server`.
Expected: start and log to stderr only (the stack error path exists for exactly this).
Actual: traceback on stderr, no `ready` line, exit 1; Electron would show "backend did not start".

### QA-RUNTIME-14  A wrong type in config.yaml breaks the recording stack, or startup, instead of falling back to the default
Severity: S3
Status: FIXED - ConfigManager._fill_defaults replaces wrongly typed leaves by defaults with a user-facing line; verified by tests/test_config_wrong_types.py
Where: `Runtime._build_stack` (`int(whisper_cfg["beam_size"])`), `settings._read`, `utils.get_models_root`.
Steps (each reproduced 1 run, isolated key per run): `whisper.beam_size: abc` -> `stack_error: invalid literal for int()...` (no hotkeys, no dictation); `audio.max_duration: abc` -> same plus `settings.get` `internal`; `hotkey.start_recording_hotkey: 5` or `stop_recording_hotkey: [1]` -> `'int' object has no attribute 'strip'`; `hotkey.push_to_talk_min_hold_seconds: abc` -> stack error and `settings.get` `internal`; `storage.models_dir: 5` -> the runtime crashes at start with `AttributeError`.
Expected: the app starts, ignores the field, rewrites it (the YAML parse failures are quarantined correctly; a parseable file with a wrong leaf is not validated).
Actual: as above. Sections of the wrong type (`whisper: 5`, `hotkey: [1,2]`, `llm: 7` ...) are handled well.
Status: Handler side FIXED, NEEDS core - `settings.get` and the hotkey push no longer raise on a wrong-typed value (default, clamped) - `app/server/handlers/settings.py` `_as_int`/`_as_float`/`_as_bool`; verified by `tests/server/test_settings.py::test_a_stored_value_of_the_wrong_type_does_not_break_settings_get`. `Runtime._build_stack` and `utils.get_models_root` are core's (`tests/test_config_wrong_types.py` there).

### QA-RUNTIME-15  The user's words reach stderr unfiltered, and technical text reaches the user
Severity: S3
Status: FIXED - stderr filter is in app/server/__main__.py (handlers/shell area, present in tree); file failures no longer carry the prefix (TranscriptionError rebuilt in subprocess_backend, user_reason in backends/base.py); verified by tests/backends/test_transcription_errors_across_the_pipe.py
Where: `app/server/__main__.py` (`logging.basicConfig(stream=sys.stderr)` has no `_NoSensitiveToFile`-style filter); `app/server/runtime.py:_RingHandler`; `files.py` message.
Observations:
1. The "Transcribed: <first 77 chars>" line (tagged `sensitive`) is correctly kept out of app.log (0 hits) but is printed on stderr, which Electron keeps (60-line tail shown in the "backend exited" error, printed to the console with `L2T_DEV`). The same preview is in `logs.list` and the `log` event; that matches the Qt Logs view by design, but it is more than the brief's "never in logs.list/events", so I flag it for a decision.
2. File failures say `Subprocess error: TranscriptionError: Could not read audio from zero.wav ...` (technical prefix reaches the screen; same for corrupt, truncated, text-renamed-.wav). A directory path answers `not_found: That file is no longer there.`
Reproduced: each seen 2+ times.
Status: FIXED for stderr and for the file message, decision left for the Logs view - the server's stderr handler now drops records tagged `sensitive` (`app/server/__main__.py`); a file failure reaches the screen as a sentence with a `code` (`files.explain_failure`, no `Subprocess error:`, exception class, graph node or build path); verified by `tests/server/test_files.py::test_failure_reasons_lose_their_plumbing` and `::test_the_failed_event_carries_the_friendly_message_and_code`. The `Transcribed:` preview stays in `logs.list` and the `log` event, as in the Qt Logs view (product decision, not changed).

---

## S4

### QA-RUNTIME-16  `models.storage.apply` does not check the folder is writable (`plan` does)
`apply {path: <read-only dir>, move: false}` -> `started`, then `storage done changed:true`; the models list turns empty and later downloads fail. 1 run.
Status: FIXED - `models.storage.apply` refuses a folder that cannot be written (`bad_path`) and the worker re-checks it; verified by `tests/server/test_models.py::test_apply_refuses_a_folder_that_cannot_be_written`.

### QA-RUNTIME-17  A history entry with an out-of-range timestamp makes `history.list` fail permanently
Status: FIXED - history entries are type-validated on load and restore (timestamp finite and in range), datetime_str never raises; verified by tests/test_history_damaged_file.py
`history.restore {entry:{timestamp:1e300,text:"x"}}` -> `restored`; then `history.list` -> `internal: timestamp out of range for platform time_t`, also after restart (it is on disk). `history.clear` recovers. A `NaN` timestamp can never be deleted (`nan != nan`). The same restore accepts a 3 MB text and an empty text. Needs a crafted call or a hand-edited jsonl. 2 runs.
Status: FIXED in the handler, core has the loader - `history.restore` refuses an entry with a non-finite or out-of-range timestamp, empty or oversized text, a bad duration or over-long fields (`bad_params`, field `entry`); `history.delete` refuses a NaN id; `history.list` skips an entry that cannot be shown instead of failing; verified by `tests/server/test_history.py::test_restore_refuses_an_entry_that_could_not_be_shown_or_found_again` (12 cases) and `::test_one_entry_that_cannot_be_shown_does_not_hide_the_others`.

### QA-RUNTIME-18  Junk values accepted or mis-clamped
`presets.update {timeout_s: 0|-1|"abc"}` stores 20, not 1 as the contract says (`1..600`); `max_tokens: Infinity` -> `internal: cannot convert float infinity to integer`; `models.inference.set {language: "xx"|5|["ru"]}` stores `xx`, `'5'`, `"['ru']"` (not checked against the language list; the effect on a Whisper load was not measured); `models.hf_token.set {token: "\u0000"}` -> `internal: embedded null byte` after the value was already saved to config (`huggingface.token: "\0"`). 1 run each.
Status: FIXED - `presets.update` refuses non-numbers and non-finite numbers and clamps 0/-1 to 1 (contract) instead of storing the default; `models.inference.set` refuses an unknown language and non-numeric `beam_size`/`temperature`; `models.hf_token.set` refuses a NUL, spaces and non-ASCII before saving; verified by `tests/server/test_presets.py::test_junk_in_any_field_is_refused_with_the_field_named`, `::test_numbers_outside_the_range_are_clamped_not_replaced_by_the_default`, `tests/server/test_models.py::test_inference_settings_that_would_be_silently_replaced_are_refused` and `::test_a_token_that_cannot_be_one_is_refused_before_it_is_saved`.

### QA-RUNTIME-19  Deeply nested JSON body drops the connection
`POST /rpc` with `params` nested 50 000 deep (or 100 000 `[`) -> no response (`RemoteDisconnected`); `RecursionError` in `json.loads` is not in the `except (ValueError, ...)`. The server survives. Needs the token. 2 runs.
Status: FIXED - `RecursionError` is a 400 `bad_request` (`app/server/httpd.py`); verified by `tests/server/test_hardening.py::test_a_deeply_nested_body_is_a_400_not_a_dropped_connection` and live (100000-deep body: `HTTP Error 400`, server alive).

### QA-RUNTIME-20  Reserved or destructive OS shortcuts are accepted as hotkeys
`cmd+q`, `cmd+w`, `cmd+c` (as Cancel), `alt+f4`, `ctrl+alt+delete` all validate and save. 1 run.
Status: WON'T FIX (this pass) - a refusal needs a new user-facing sentence, which must also be added to the Qt catalogue (`app/i18n/app_ru.ts`) and the renderer's `ru.json`, both outside this area; `hotkey_rules.py` is shared with the Qt view. Cheap follow-up: a `RESERVED` set per platform in `check_hotkey` plus the two translations.

### QA-RUNTIME-21  Relative paths are written wherever the runtime's working directory is
`files.save_text {path:"rel_out.txt"}` and `{path:"../escape_out.txt"}` succeed relative to the process cwd. 1 run.
Status: FIXED - a relative path is `bad_path` for `files.save_text`, `history.export` and `files.transcribe` (`app/server/safe_paths.py`); verified by `tests/server/test_safe_paths.py::test_a_relative_path_is_never_written_to_the_working_directory` and live (`rel_out.txt` not created in the cwd).

### QA-RUNTIME-22  `recording.toggle` with no model is a silent no-op
Status: FIXED (core) - StateManager.toggle_recording with no model reports a failed outcome with the way out. NEEDS handlers - recording.toggle should return an error code
Fresh profile (model not on disk): `recording.toggle` -> `{state:"idle"}` with no error code; only a log line says "Model is not ready yet". Same for `recording.stop` (`stopped:false`). 1 run.
Status: FIXED - an idle `recording.toggle` with no model ready answers `not_ready` with the sentence for the situation (`app/server/handlers/core.py` `not_ready_message`); verified by `tests/server/test_core_handlers.py::test_starting_without_a_model_is_refused_with_the_reason`. The hotkey path does not go through this method (core).

### QA-RUNTIME-23  The LLM key is returned in clear and the dev log location ignores the scratch directory
`app.snapshot.config.llm.api_key` and every `presets.*` state carry the key in clear (by contract), while the HF token is carefully never returned; the two credentials are treated differently. Separately, in dev the log folder and history file come from the source tree (`<repo>/logs`), not the working directory, so parallel dev runtimes share one history file. Observation, not a repro of harm.
Status: FIXED for the key, NEEDS core for the dev paths - no reply and no `app.snapshot` carries `api_key` (replaced by `api_key_set`, `token_set`) - `app/server/redact.py`; verified by `tests/server/test_presets.py::test_no_reply_carries_the_key_only_a_flag`, `tests/server/test_core_handlers.py::test_the_snapshot_carries_flags_instead_of_credentials` and live (`sk-PLANTED...` not in any reply or snapshot). The dev log/history location is core's (QA-JOURNEYS-12).

---

## Covered, no defect

- Transport: empty/array/string/null/number body, non-UTF-8, bad JSON, params of wrong type (400 / `bad_params`), 3.9 MB body ok, 5 MB refused, missing/wrong token, token in query for POST, bad/empty/look-alike Host (403), `Content-Type: text/plain` accepted, chunked and short-body requests, unknown paths (404), `/health`. CORS preflight reflects any Origin but no token is ever given to a page.
- Fuzz of all 60 methods with 16 junk values for 24 parameter names each (about 23 000 calls): no crash, no hang; only `hf_token.set` with NUL gave `internal` (QA-RUNTIME-18).
- 400 idle SSE subscribers with a tiny receive buffer while recording: RPC latency unchanged (2 ms), threads and descriptors return to baseline when they close; quit with stuck subscribers is immediate.
- Quit via `app.quit` while recording, while processing, during an LLM request that hangs; SIGTERM while recording; SIGINT idle; stdin close; SIGKILL then a second start (stale lock reclaimed): exit code 0 within 0.6 to 2 s, no orphan worker (checked with `ps` per descendant pid). Second instance with the lock: `{"ready":false,"error":"already_running"}`, exit 3. Port in use: exit 1, workers cleaned up. Startup to `ready`: 0.4 to 0.8 s.
- Corrupt config: binary, YAML list, scalar, tab-indented are quarantined to `config.yaml.corrupt-N` and the app starts on defaults; empty, null, wrong-typed sections, unknown keys, bad `llm.profiles`, huge numbers start fine.
- LLM fallback to raw text: HTTP 401, 500, empty content, HTML login page, `null`, non-string content, non-UTF-8 body, truncated body, redirect, refused connection, port 99999, `file://` URL. API key never in app.log/logs.list/events/RPC errors (planted `sk-FAKEKEY-9f8e7d6c`: 0 hits in all five, only in config.yaml and presets state), HF token the same.
- History: 200 concurrent restores, concurrent delete/restore of the same ids (memory and disk equal, no duplicates, order kept), clear during a dictation, `max_entries` cap, history disabled (dictation still delivers, writes refused with `history_disabled`), export to unwritable/directory/system file (`write_failed`, nothing truncated).
- File transcription: zero-byte, corrupt, text renamed `.wav`, truncated, unsupported extension with and without `strict`, directory, missing, `/dev/null`, `/etc/passwd`, `.mp3`, `.flac`, stereo 44.1 kHz, silence, unicode and spaces in the path, two files at once, a file while a dictation runs. All end in `file.done` or `file.failed` with the right path.
- Recording state machine: 30 concurrent toggles and 20 rapid toggles end idle; `devices.test` refused while recording; `models.select/download/delete/storage` refused or handled during `model_loading`; five concurrent deletes of one model give one `started` and four `busy`; concurrent `presets.create` (20) gives unique ids, memory equals disk; concurrent `settings.set` memory equals disk; `max_duration` auto-stop delivers.
- Settings bounds: `max_duration` 0..3600, `min_hold` 0..2, theme/palette/language sets, `text_scale` clamp, booleans strict, unknown keys, hotkey validation for empty, modifiers only, unicode, extra `+`, push-to-talk solo keys.

## Not tested, and why

- Real global hotkeys (the keys are shared with the user's other apps and parallel runtimes) and auto-paste (`pasted` / `failed` outcomes would type into the user's open applications; only `copied` was exercised with `clipboard.auto_paste=false`).
- Real model downloads and any model other than `vosk-ru-small` (rule: no downloads); so Whisper and Parakeet inference settings were only checked at the RPC level, and whether other cards fail on long audio (QA-RUNTIME-3) is unknown.
- `permissions.request/open_settings` and `models.storage.open` (open System Settings and Finder on the user's machine); `devices.test` result events (3 s of real microphone, run once only through fuzz).
- A microphone unplugged during a recording; cross-volume storage moves; Windows and Linux; GPU providers; a real LLM provider; the 300 s default `max_duration` end to end; memory behaviour on very large files (the only 1-hour file failed in the model, QA-RUNTIME-3).
- The Electron shell and renderer (other areas).
