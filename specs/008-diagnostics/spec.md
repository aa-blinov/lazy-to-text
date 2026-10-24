# Feature Specification: Diagnostics (Logs View, Log Pipeline, Crash Survival)

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "Baseline description of what the application already does to let a user see what the app is doing, to keep secrets and dictated words out of the log file, and to stay quitable when the microphone wedges."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See what the app is doing, in order (Priority: P1)

A user whose model misbehaves, or whose dictation did not land, opens the Logs page from the sidebar and reads a live, ordered stream of what the app did. Each line shows a time, a level, the source, and the message. Errors and warnings stand out from routine lines without reading them, and lines the app addressed to the user ("Recording started!", "Delivery sent") are brighter than the app's own bookkeeping.

**Why this priority**: The Logs view is the only diagnostic surface a user has, including for the inference worker, which runs in a process they cannot attach to. Without it a failure is invisible.

**Independent Test**: Launch the app, trigger a dictation, open Logs, and confirm lines appear in order with level-dependent colouring and a visible difference between user-facing and bookkeeping lines.

**Acceptance Scenarios**:

1. **Given** the app has just launched and nothing has been logged to the view yet, **When** the user opens Logs, **Then** an empty state titled "No entries yet" explains that entries appear within a second of launch.
2. **Given** the app logs a record, **When** it reaches the view, **Then** it is appended as one wrapped, read-only line made of timestamp, bracketed level, logger name with a trailing colon, and message, in that visual rank (message brightest, then level, then source, then timestamp).
3. **Given** a record at INFO or DEBUG level that carries no user-message tag, **When** it is rendered, **Then** its message is muted; **Given** the same record carries the tag, **Then** its message is at full primary brightness.
4. **Given** a WARNING, ERROR or CRITICAL record with no tag, **When** it is rendered, **Then** its message is NOT muted (a problem is never receded).
5. **Given** the user switches theme between light and dark, **When** new lines are drawn, **Then** their colours come from the active palette at paint time (not from the palette that was active at import).
6. **Given** a multi-line message (for example a traceback forwarded from the worker), **When** it is rendered, **Then** it is shown in full in the same record and long lines wrap at any character instead of requiring horizontal scrolling.

---

### User Story 2 - Find the line that matters: search and network-noise filter (Priority: P1)

The user types in a search box to narrow the stream, and by default does not see HTTP chatter from model downloads. A checkbox brings that chatter back when it is needed.

**Why this priority**: A model load produces a flood of network lines that bury the actual diagnosis; filtering is what makes the view readable.

**Independent Test**: Append records from `httpx` and `app.*` loggers; confirm only the app one is visible until the network toggle is ticked; then type a query and confirm only matching records remain.

**Acceptance Scenarios**:

1. **Given** records from the loggers `httpx`, `httpcore`, `urllib3`, `huggingface_hub`, `requests`, `asyncio` (or any sub-logger such as `httpx._client`), **When** "Show network logs" is unticked (default), **Then** they are kept in the buffer but not displayed.
2. **Given** the toggle is ticked, **When** it changes, **Then** the whole buffer is replayed with the new filter, so previously hidden records appear in their original order.
3. **Given** the user types a query, **When** 200 ms pass after the last keystroke, **Then** the buffer is replayed once showing only records whose level, logger name, or message contains the query (case-insensitive, whitespace-trimmed). Rapid keystrokes produce a single re-render.
4. **Given** a query that matches nothing, **When** results are shown, **Then** the stream area is empty but the "No entries yet" empty state is NOT shown, because the buffer is not empty.
5. **Given** the user presses the window's Find accelerator while Logs is the current page, **When** the accelerator fires, **Then** keyboard focus moves to the log search field.
6. **Given** a non-app logger name (anything not starting with `app.`) or a noisy logger, **When** it is rendered, **Then** its source is drawn muted; app loggers are drawn in the secondary ink.

---

### User Story 3 - Clear the view, with a confirmation, without touching the file (Priority: P2)

The user empties the on-screen buffer. The action names what it destroys, asks first, and leaves the log file on disk alone.

**Why this priority**: Destructive and one click from the search box; it must be deliberate, but is not needed for diagnosis.

**Independent Test**: Append records, click "Clear logs", cancel, confirm nothing changed; click again and accept, confirm the buffer and view are empty and the empty state returns.

**Acceptance Scenarios**:

1. **Given** the buffer holds N records, **When** the user clicks "Clear logs", **Then** a confirmation titled "Clear logs?" states the number of buffered lines (with correct plural forms in the active language) and that the file on disk is not touched, with buttons "Clear logs" and "Keep logs".
2. **Given** the user chooses "Keep logs", **When** the dialog closes, **Then** the buffer and the view are unchanged.
3. **Given** the user confirms, **When** the dialog closes, **Then** the buffer, the rendered text, and the stream are emptied and the empty state is shown.
4. **Given** the buffer is empty, **When** the user clicks "Clear logs", **Then** nothing happens and no dialog appears.
5. **Given** a search hides every record, **When** the user clicks "Clear logs", **Then** the confirmation still appears, because hidden records are still buffered.
6. **Given** the button, **When** it is shown, **Then** it carries the danger role and a tooltip saying it empties the log buffer and does not touch the log file; the warning is also carried by its label and the confirmation, not by colour alone.

---

### User Story 4 - A log file that is useful and bounded, and never holds secrets or dictated text (Priority: P1)

The app also writes `app.log` to disk. It is rotated, so it cannot grow without bound; it never contains credentials; and it never contains what the user dictated, although the Logs view may show it.

**Why this priority**: The file persists on disk, is not cleared by "Clear history", and is the thing a user attaches to a bug report. Privacy by default is a constitutional principle.

**Independent Test**: Dictate a phrase, save a token, then read `app.log`: the "Transcribed" line is absent, the token appears only as `<set>`/`<empty>`.

**Acceptance Scenarios**:

1. **Given** a successful transcription, **When** the app logs the "Transcribed: ..." preview, **Then** the Logs view shows it and `app.log` does not.
2. **Given** an ordinary record (no sensitive tag, or the tag explicitly false), **When** it is logged, **Then** it reaches both the view and the file.
3. **Given** the user pastes or clears a Hugging Face token, **When** the settings change is logged, **Then** both old and new values appear only as `<set>` or `<empty>`, never as the token.
4. **Given** the user saves a post-processing profile whose structure contains an `api_key` (or `token`, `password`, `secret`) at any depth, **When** the change is logged, **Then** the structure is preserved (profile names, providers, ids remain readable) and each credential value is replaced by `<set>` or `<empty>`.
5. **Given** a non-secret setting changes, **When** the change is logged, **Then** the line reads `Updated setting <section>.<key>: <old> -> <new>` with the values visible.
6. **Given** the file reaches its size cap, **When** rotation is enabled, **Then** it rolls over and keeps a bounded number of backups.

---

### User Story 5 - A second launch that is refused still leaves a trace (Priority: P2)

When the single-instance gate refuses to start the app, the refusal is written to `app.log`, because there is otherwise no window, no Dock icon and no console to show it.

**Why this priority**: A refusal that writes nothing is indistinguishable from the app never having been launched.

**Independent Test**: Hold the instance lock, start a second instance, and find a line in `app.log` naming the refusal.

**Acceptance Scenarios**:

1. **Given** the file handler is installed before the single-instance gate runs, **When** a second instance is refused, **Then** its refusal is recorded in `app.log`.
2. **Given** the file handler is installed twice for the same path, **When** the second install runs, **Then** no second handler is attached and lines are not duplicated.

---

### User Story 6 - A wedged microphone never turns into an app that cannot quit (Priority: P1)

If the audio driver stops responding while stopping a recording, the app logs where the recording thread is stuck, tries to recover, tells the user plainly if it cannot, and on quit leaves the process immediately instead of hanging with no window while holding the single-instance lock.

**Why this priority**: The recorded field failure was every dictation failing after the first, and then a process that could not be quit and blocked every later launch.

**Independent Test**: With a stub recording thread that never finishes, stop the recording and observe the abort attempt, the log lines and the refusal of the next recording; then simulate quit and observe that the process exits through the hard-exit path.

**Acceptance Scenarios**:

1. **Given** a recording thread that is still alive after the stop wait, **When** recording is stopped, **Then** the app logs a warning with the stack of the blocked thread and aborts the input stream from a helper thread so an abort that blocks cannot block the caller.
2. **Given** the abort succeeds and the thread finishes, **When** the next recording is started, **Then** it proceeds normally and an INFO line records that the thread finished after the abort.
3. **Given** the abort does not return within its time limit, **When** it is logged, **Then** an ERROR line says the abort did not return, and a second ERROR line says the thread is still alive after aborting.
4. **Given** the previous recording's thread is still alive and cannot be released, **When** the user starts another recording, **Then** it is refused and the user-facing message is "Microphone is still held by the previous recording. Restart the app."
5. **Given** a recording produced no audio chunks, **When** it is processed, **Then** the user-facing message is "No audio from the microphone. Restart the app if this keeps happening." and no transcription is attempted.
6. **Given** a model load is in flight or a recording thread is stuck when the app quits, **When** shutdown reaches the exit decision, **Then** the app logs a warning, flushes every log handler, and leaves with a hard process exit using the normal exit code, instead of waiting for interpreter finalisation.
7. **Given** the probe for a stuck thread raises or is absent, **When** shutdown asks, **Then** the app treats it as "not stuck" and exits normally.

---

### User Story 7 - Worker-process records reach the Logs view and the file (Priority: P2)

Everything the inference worker process logs, including tracebacks, appears in the same stream as the main process's records.

**Why this priority**: The worker is where model loading and inference fail, and a windowed build has no console.

**Independent Test**: Make the worker log an error with an exception; confirm the Logs view shows the message and the traceback as one record.

**Acceptance Scenarios**:

1. **Given** the worker logs a record, **When** it is forwarded, **Then** the parent re-emits it under the same logger name and level, so it reaches the Logs view and (subject to the sensitive filter) `app.log`.
2. **Given** a worker record carries exception info, **When** it is forwarded, **Then** the rendered traceback is appended to the message as extra lines of the same record.
3. **Given** Python warnings (for example deprecation warnings from model libraries), **When** they are raised, **Then** they are captured into logging instead of disappearing to a missing stderr.

---

### Edge Cases

- A record arrives while the Logs page is not the current page: it is still buffered and rendered, so opening the page shows the full recent history.
- The buffer is capped (1000 lines by default); once full, the oldest records are dropped from both the buffer and the rendered document, so memory stays bounded in a long-running session.
- A message containing HTML-like characters is escaped, never interpreted.
- A record whose handler raises while formatting is passed to the logging framework's error handler and never crashes the app.
- `logging.level` in the config is unknown or empty: the level falls back to INFO.
- `logging.file.enabled` is false: no file handler is attached and no path is returned; the Logs view still works.
- `logging.file.rotation.enabled` is false: a plain, unrotated file handler is used instead.
- The `logging` section is missing or not a mapping: defaults are used.
- A credential key is spelled in a different case (`API_KEY`): it is still scrubbed.
- A search matches nothing while the buffer is non-empty: the empty state must not claim the app logged nothing.
- The Clear button must not count only visible records; it counts the buffer.
- The older four-argument way of appending a record (no tag) keeps working and renders as bookkeeping.
- The view has exactly one way for text to enter it (a structured record); no path writes to the document without recording the record, otherwise Clear could not account for it.

## Requirements *(mandatory)*

### Functional Requirements

**Logs view**

- **FR-001**: The system MUST provide a "Logs" page in the sidebar that renders records as read-only text, one line per record, in arrival order, with line wrapping at any character.
- **FR-002**: The page MUST show a header "Logs" with the subtitle "What the app is doing, in order. Useful when a model misbehaves."
- **FR-003**: The page MUST expose exactly three controls: a search field (placeholder "Search logs...", with a clear button), a "Show network logs" checkbox (default unchecked, with a tooltip saying it adds requests to the model server and the internet), and a "Clear logs" danger button.
- **FR-004**: Each record MUST render as timestamp (HH:MM:SS), bracketed level, logger name followed by a colon, and message, with inline colours resolved from the active theme tokens at the time of painting.
- **FR-005**: Level inks MUST be: DEBUG muted, INFO accent, WARNING warning, ERROR and CRITICAL danger, unknown levels accent.
- **FR-006**: A record tagged as addressed to the user MUST render its message at primary brightness; an untagged DEBUG or INFO record MUST render muted; an untagged WARNING or above MUST render at primary brightness.
- **FR-007**: The view MUST keep a bounded ring buffer of records (default 1000) and drop the oldest when full; the rendered document MUST be bounded by the same count.
- **FR-008**: Records from the loggers `httpx`, `httpcore`, `urllib3`, `huggingface_hub`, `requests`, `asyncio` (matched on the top-level package of the logger name) MUST be buffered but hidden unless "Show network logs" is checked.
- **FR-009**: Search MUST match case-insensitively against level, logger name and message together, MUST be debounced to a single re-render 200 ms after the last keystroke, and MUST re-render from the buffer rather than from the displayed text.
- **FR-010**: Toggling the network checkbox MUST re-render from the buffer immediately.
- **FR-011**: While the buffer is empty the page MUST show an empty state ("No entries yet" with an explanatory hint); the empty state MUST be keyed on the buffer, not on what survives the filters.
- **FR-012**: "Clear logs" MUST ask for confirmation naming the buffered line count, MUST name the outcome on both buttons ("Clear logs" / "Keep logs"), MUST do nothing when the buffer is empty, and MUST NOT modify the log file on disk.
- **FR-013**: The page MUST support focusing its search field from the window-level Find accelerator.
- **FR-014**: All visible strings of the page (title, subtitle, placeholder, checkbox label and tooltip, button label and tooltip, empty state, confirmation text with plural forms) MUST be translatable and update when the interface language changes at runtime.
- **FR-015**: The network checkbox MUST sit in a plain, unstyled holder so that on macOS it keeps its layout spacing from the neighbouring button (a styled checkbox loses it there).

**Log pipeline**

- **FR-016**: The system MUST forward every stdlib logging record to the Logs view as a structured tuple (time, level, logger name, message, user-message flag) and, separately, as a formatted single line for legacy listeners.
- **FR-017**: The user-message flag set by a call site MUST survive the bridge unchanged; dropping it is the defect that once made user-facing and bookkeeping lines look identical.
- **FR-018**: The file handler MUST be installed before the single-instance gate and the UI bridge attached after it, so that early records (including a refused second launch) reach the file.
- **FR-019**: The root logger level MUST come from `logging.level` in the configuration (default INFO), falling back to INFO for an unrecognised name.
- **FR-020**: The file handler MUST honour `logging.file.enabled` (default true), `logging.file.filename` (default `app.log`), and `logging.file.rotation` (`enabled` default true, `max_bytes` default 1048576, `backup_count` default 5, `encoding` default utf-8); with rotation disabled a plain file handler is used.
- **FR-021**: The log file MUST live in the per-user log directory given in CLAUDE.md (project `logs/` in development, `~/Library/Logs/LazyToText/` for the macOS bundle, `%LOCALAPPDATA%\LazyToText\Log\` for the Windows bundle) and nothing may write logs into the installation directory.
- **FR-022**: Installing the file handler MUST be idempotent per path.
- **FR-023**: Python warnings MUST be routed into logging.
- **FR-024**: Records from the inference worker process MUST be forwarded to the parent and re-emitted under the original logger name and level, with tracebacks rendered into the message.

**Privacy of the log**

- **FR-025**: A record tagged as sensitive (currently the "Transcribed: ..." preview, truncated to 80 characters) MUST reach the Logs view and MUST NOT reach `app.log`. The tag is orthogonal to the user-message flag.
- **FR-026**: No credential MUST be written to the log in any direction. The old and new values of a Hugging Face token and of the LLM `api_key` MUST be logged only as `<set>` or `<empty>`.
- **FR-027**: A credential nested at any depth under a key named `api_key`, `token`, `password` or `secret` (any case) MUST be replaced by `<set>` or `<empty>` while the surrounding structure remains readable.
- **FR-028**: Every setting change MUST be logged as `Updated setting <section>.<key>: <old> -> <new>` after redaction; an unchanged value MUST NOT write or log.
- **FR-029**: Adding a new redacted setting MUST be covered by a test that proves its value is absent from the log in both directions.

**Crash survival**

- **FR-030**: When a recording thread is alive after the stop wait (2 seconds), the system MUST log a warning including the stack where the thread is blocked, then abort the input stream from a helper thread, waiting at most 1 second for the abort and 1 second for the thread.
- **FR-031**: Outcomes MUST be distinguishable in the log: thread finished after abort (INFO), abort did not return (ERROR), thread still alive after abort (ERROR), abort raised (ERROR with the reason).
- **FR-032**: A new recording MUST be refused when the previous thread cannot be released, with the user-facing message "Microphone is still held by the previous recording. Restart the app."
- **FR-033**: A recording that yields no audio MUST report "No audio from the microphone. Restart the app if this keeps happening." as a user-facing warning and MUST return no audio.
- **FR-034**: The recorder and the recording controller MUST expose whether a recording thread is still alive after its stop, and the application's exit path MUST consult it together with "a model load is in flight".
- **FR-035**: When either is true at exit, the application MUST log a warning, flush all root log handlers, and terminate with a hard exit carrying the normal exit code. A probe that is missing or raises MUST be treated as not stuck.
- **FR-036**: The macOS build MUST ship a PortAudio built from the vendored patch that removes the CoreAudio stop deadlock (the stop listener must not re-enter CoreAudio); a build without the patch marker MUST fail the bundle tests. The hard exit in FR-035 is the second line of defence, not a replacement.
- **FR-037**: The repository MUST carry a stress canary that opens and stops streams in a loop with a swept start-to-stop phase, reports the cycle it hung on, and ends with a hard exit so that it reports rather than itself deadlocking at interpreter exit.

### Key Entities

- **Log record**: A single event with time, level, logger name, message, an optional user-message flag (addressed to the user) and an optional sensitive flag (contains the user's words).
- **Log buffer**: The bounded in-memory sequence of records held by the Logs view; the single source for re-rendering, filtering and the Clear action.
- **Log file**: The rotated on-disk `app.log` (name, level, rotation caps configurable); never contains sensitive-tagged records or credentials.
- **Logging configuration**: The `logging` section of the generated config: level, file (enabled, filename, rotation), and a console block.
- **Redacted setting**: A configuration key whose value is a credential and is shown in logs only as set or empty.
- **Stuck recording**: A recording thread that outlives its stop and still holds the input stream and the microphone.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every record the app logs while running appears in the Logs view in order, with no record accepted by the view that Clear cannot account for.
- **SC-002**: After any session, `app.log` contains zero occurrences of a dictated transcript preview and zero occurrences of a stored credential value, including credentials nested in post-processing profiles.
- **SC-003**: `app.log` size stays bounded by the configured rotation caps for the life of an install.
- **SC-004**: A user can distinguish a message addressed to them from bookkeeping, and an error from routine info, without reading the text.
- **SC-005**: With a wedged microphone, the app can always be quit and leaves no windowless process holding the single-instance lock.
- **SC-006**: A refused second launch is always visible in `app.log`.
- **SC-007**: The patched PortAudio survives the stress canary for a number of cycles published with it (see `scripts/stress_portaudio_stop.py` and CLAUDE.md), against a stock library that does not.

## Assumptions

- The Logs view reads the in-process stream only; it does not tail `app.log` and does not show records from before it was constructed.
- "Clear logs" is intentionally local: it never deletes the file. There is no in-app way to open, export or delete `app.log`.
- The `logging.console` block exists in the default configuration but nothing reads it; a windowed build has no console. See "Observed inconsistencies".
- The per-model and LLM call sites tag their own user-facing lines; this spec does not enumerate every message.
- The stuck-microphone behaviour is verified by measurement against real hardware, not by the test suite; the tests hold the artifact in place.
- Observed inconsistencies, recorded rather than fixed: (1) `logging.console` is declared but unused; (2) the comment in `state_manager.py` points the sensitive filter at `app/gui/app.py`, but it lives in `app/bootstrap.py`; (3) the worker forwards at INFO and above only (root level INFO) regardless of `logging.level`; (4) the Logs view cap is a constructor default, not a setting; (5) a record forwarded from the worker is re-emitted through the parent logger as a plain message, so a `sensitive` or `user_message` tag set inside the worker is lost.

## Where it lives

- `app/gui/views/logs_view.py` - the Logs page: record rendering, noisy-logger filter, debounced search, buffer, Clear with confirmation, empty state, `focus_search`.
- `app/gui/log_bridge.py` - `QtLogBridge` and its handler: stdlib records to Qt signals (`record_received`, `line_received`), carrying the user-message flag.
- `app/bootstrap.py` - `_install_file_logging` (level, rotation, filename, idempotence, `captureWarnings`) and `_NoSensitiveToFile` (drops sensitive-tagged records from the file only).
- `app/gui/app.py` - installs the file handler before the instance gate, attaches the bridge to the main window's Logs view, `_recording_thread_stuck` and the hard-exit path (`os._exit`) with log flush.
- `app/gui/main_window.py` - hosts `logs_view` as a stacked page; Find accelerator dispatch via `focus_search`. `app/gui/widgets/sidebar.py` - the "Logs" entry.
- `app/config_manager.py` - `DEFAULT_CONFIG["logging"]`, `_REDACTED_SETTINGS`, `_SECRET_KEYS`, `_scrub_secrets`, `_redact_for_log`, and the `Updated setting` log line in `update_user_setting`.
- `app/state_manager.py` - emits the sensitive-tagged "Transcribed:" preview.
- `app/audio_recorder.py` - `_release_stuck_recording`, `_abort_stream`, `has_stuck_recording_thread`, no-audio and held-microphone user messages.
- `app/gui/controllers/recording_controller.py` - `recording_thread_stuck`.
- `app/backends/subprocess_worker.py` / `app/backends/subprocess_backend.py` - pipe log handler in the worker (with tracebacks) and re-emission in the parent.
- `vendor/portaudio/` - the vendored CoreAudio stop-deadlock patch and README; `scripts/build_patched_portaudio.py` builds and installs it with a `.patched.json` marker; `scripts/stress_portaudio_stop.py` - the canary.
- Tests: `tests/gui/test_logs_view.py`, `tests/gui/test_log_bridge.py`, `tests/gui/test_file_logging.py`, `tests/test_config_hardening.py`, `tests/test_audio_recorder_stuck_stream.py`, `tests/gui/test_app_exit_stuck_recorder.py`, `tests/gui/test_recording_controller.py`, `tests/test_bundle_contents.py` (patched PortAudio marker), `tests/backends/test_subprocess_backend.py` (worker log forwarding).
