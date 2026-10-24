# Feature Specification: File Transcription (Transcribe view)

> **Note (spec 011):** this spec was written against the former Qt interface. The Electron interface (spec 010) replaced it and the Qt code was removed (spec 011). The behaviour described here is still the behaviour spec of the engine; mentions of `app/gui` below name files that no longer exist, and the equivalent lives in the Electron renderer (`desktop/renderer`) and the runtime (`app/server`).

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "Describe what the application already does when a user gives it an audio or video file and wants text back: the Transcribe screen, the decoder, long-file handling, the editable transcript, copy and save, the per-run preset picker, and opening files from the operating system."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a file into text (Priority: P1)

A user has a recording (a voice memo, a meeting, a video) and wants the words. They open the Transcribe screen, drop the file on it or choose it with Browse, wait while the window stays usable, and read the transcript.

**Why this priority**: This is the whole purpose of the screen. Everything else on it exists to make this result easier to take away.

**Independent Test**: With a model loaded, drop one supported file on the screen and confirm that a transcript appears, the drop zone collapses to a line naming the file, and Copy and Save appear.

**Acceptance Scenarios**:

1. **Given** the screen is empty and a model is ready, **When** the user drops a supported file on it, **Then** the screen enters a busy state naming the file and its size, shows "Working. The window stays usable.", and later shows the transcript.
2. **Given** the screen is empty, **When** the user clicks Browse and picks a file, **Then** the same run starts as for a drop.
3. **Given** a transcript has arrived, **When** it is shown, **Then** the file line reads as size, processing time and word count, separated by a middle dot.
4. **Given** a run is in progress, **When** the user switches to another screen and back, **Then** the application has stayed responsive throughout and the result is shown when it lands.

---

### User Story 2 - Correct and take the text away (Priority: P1)

The user reads the transcript, fixes a misheard word in place, then copies it to the clipboard or saves it as a text file.

**Why this priority**: The text ends up in someone else's document; making the user leave the screen to fix one word defeats the point.

**Independent Test**: Produce a transcript, edit a word, click Copy, and confirm the clipboard holds the edited text and the file line shows "Edited".

**Acceptance Scenarios**:

1. **Given** a transcript has arrived, **When** the user types in it, **Then** the text changes, the word count follows, and the file line gains an "Edited" note.
2. **Given** the text has been edited, **When** the user restores it to exactly what the model returned, **Then** the "Edited" note disappears.
3. **Given** edited text, **When** the user clicks Copy, **Then** the clipboard receives the text currently on screen, not the original model output, and a short "Copied to clipboard." confirmation appears and fades by itself.
4. **Given** a transcript, **When** the user clicks "Save .txt", **Then** a save dialog opens suggesting the source file's name with a `.txt` extension in the source file's folder, and confirming writes the current on-screen text as UTF-8 and shows "Saved: <path>".
5. **Given** a save that fails at the file system, **When** it fails, **Then** the screen shows "Save failed: <reason>" and keeps the text.

---

### User Story 3 - Long and unusual files work (Priority: P1)

The user drops an hour-long recording, an MP3, a phone video, or a WAV at an unusual sample rate, and still gets a transcript.

**Why this priority**: Real recordings are rarely short WAVs; a feature that handles only those is not a file-transcription feature.

**Independent Test**: Feed the backend audio longer than one chunk and confirm it is processed in several windows and joined; feed an MP3 and confirm it is decoded through the fallback decoder.

**Acceptance Scenarios**:

1. **Given** a file of a lossless or OGG-family format, **When** it is transcribed, **Then** it is decoded in-process without launching an external program.
2. **Given** a file the in-process decoder rejects (MP3, M4A, AAC, WMA, WebM, MOV, MKV and other containers), **When** it is transcribed, **Then** it is decoded by the bundled ffmpeg and the audio track of a video file is used.
3. **Given** audio longer than the model can take in one pass, **When** it is transcribed, **Then** it is cut into fixed-length windows, each is recognised, empty windows are skipped, and the pieces are joined with a single space.
4. **Given** stereo audio or any sample rate other than 16 kHz, **When** it is decoded, **Then** it is mixed to mono and resampled to 16 kHz before recognition.

---

### User Story 4 - Know what went wrong (Priority: P2)

When a file cannot be transcribed the user is told which thing failed: no model ready, an unreadable file, a model failure, or genuinely no speech.

**Why this priority**: A dictation tool that blames the user's audio for its own failure erodes trust (Constitution II).

**Independent Test**: Drop a file with a supported extension that is not audio and confirm the error names the file and says it could not be read, rather than saying no speech was found.

**Acceptance Scenarios**:

1. **Given** the model is still loading, **When** a file is dropped, **Then** the screen shows an error saying the model is not ready yet and to wait for it to finish loading.
2. **Given** a file neither decoder can read, **When** it is transcribed, **Then** the error says audio could not be read from that file name.
3. **Given** inference raises an error, **When** it surfaces, **Then** the error says the model failed while transcribing that file and includes the reason.
4. **Given** the model returned no text, **When** the run ends, **Then** the user is told the model heard no speech in the file, which is a different message from the two above.
5. **Given** any failure, **When** it is shown, **Then** the message stays until another action replaces it.

---

### User Story 5 - Open a file from the operating system (Priority: P2)

The user double-clicks an audio file in Finder, uses "Open With", or launches the application with a file path, and the application comes to the front and transcribes it.

**Why this priority**: Dragging into a window is the affordance a first-time user thinks of last.

**Independent Test**: Simulate an operating-system file-open request for an existing file and confirm the window is shown and a run starts; repeat with a missing file and confirm an error on the screen.

**Acceptance Scenarios**:

1. **Given** the application is running in the tray, **When** the system asks it to open an existing file, **Then** the window is brought forward and the file is transcribed.
2. **Given** a file-open request naming a file that does not exist, **When** it arrives, **Then** the window is brought forward and the screen shows "That file is no longer there."
3. **Given** the application is launched with a file path argument, **When** the window has appeared, **Then** that file is announced for transcription after the first-run decision has been applied.
4. **Given** a launch argument that begins with a dash or names a directory or a path that does not exist, **When** arguments are scanned, **Then** it is ignored.

---

### User Story 6 - Choose a post-processing preset for one run (Priority: P3)

When more than one post-processing preset exists, the user picks one on this screen and ticks "Preset for this file" to use it instead of the default.

**Why this priority**: Choosing a preset at the moment of use is the reason presets exist, but the screen works fully without it.

**Independent Test**: With two presets, tick the box and confirm the override is announced with the shown preset's id; untick and confirm it is cleared.

**Acceptance Scenarios**:

1. **Given** at most one preset exists, **When** the screen is shown, **Then** the picker and its checkbox are hidden.
2. **Given** two or more presets, **When** the screen is shown, **Then** the picker lists them by name, showing the default preset, with the checkbox unticked.
3. **Given** the checkbox is unticked, **When** the user chooses a row in the picker, **Then** the checkbox ticks itself and the choice is announced as the override.
4. **Given** an override that names a preset that no longer exists, **When** the picker is filled, **Then** the checkbox is unticked and the picker shows the default preset rather than the first row.

---

### Edge Cases

- **A drop while busy**: dragging or dropping a file while a run is in progress is refused, and the Browse button is disabled until the run ends.
- **A drop of several files**: only the first local file with a recognised extension is taken; the rest are ignored. Batch processing is out of scope.
- **A drop that is not a local file or has an unrecognised extension**: the drag is not accepted and the drop zone does not highlight.
- **Browse dialog with "All files"**: the file chooser offers an "All files" filter, so a file with an unrecognised extension can be chosen; the extension list guards drops only, and an unreadable file is then reported as a decode error.
- **Operating-system opens are not extension-checked**: a file-open request or launch argument names any existing file; only existence is checked, and a non-audio file ends in the decode error.
- **Stale result**: if the user starts a second file while the first is running, only the result whose path equals the file now shown is rendered; the other is dropped.
- **Empty text from the recogniser**: a result of empty text is reported by the recording controller as a failure ("The model heard no speech in this file."), not rendered as an empty transcript. The view also contains a warning path for an empty result (file line "No speech recognised in that file.", a sticky warning suggesting another model, Copy and Save hidden), which the current controller does not reach.
- **Very long decode**: the external decoder is given a ceiling of ten minutes; on timeout the file is reported as unreadable.
- **Missing decoders**: if the in-process decoder is absent or rejects the file and the bundled ffmpeg is absent or fails, the file is reported as unreadable and the cause is written to the log.
- **File vanished after loading**: if the file's size cannot be read, the size is simply omitted from the line.
- **Transcription ceiling**: a single request to the worker is bounded to ten minutes; beyond that the call is reported as timed out.
- **Edit with nothing shown**: Copy and Save do nothing if the text is empty.
- **Remaining feature gaps**: word timestamps and the silence filter are not applied to file runs; the result is plain paste-ready text.

## Requirements *(mandatory)*

### Functional Requirements

**Screen and states**

- **FR-001**: The Transcribe screen MUST present exactly four states: idle (nothing loaded), busy (a run in progress), done (a result shown, possibly empty), and error.
- **FR-002**: While idle, the screen MUST show an invitation: a dashed drop zone with the prompt "Drop an audio or video file here" and a one-line list of example formats (MP3, WAV, M4A, MP4, MKV). The full supported list MUST be available as a tooltip on the prompt and on the example line.
- **FR-003**: Every format named in the example line MUST be one the screen actually accepts.
- **FR-004**: Once a file is loaded, the drop zone MUST collapse to two lines (file name, then detail) and keep its dashed border and its role as a drop target; the transcript MUST take the remaining space.
- **FR-005**: The header MUST carry the title "Transcribe", the subtitle "Turn an audio or video file into text you can edit.", and a Browse button. Browse MUST be the primary-styled control while the screen has no text and secondary once Copy and Save are visible, so only one accent-filled control exists at a time.
- **FR-006**: Copy and Save MUST be hidden, not disabled, while there is no text to take away.
- **FR-007**: While no transcript exists, the transcript area MUST show an empty state titled "No transcript yet" with the hint that the text appears once a file is dropped, ready to edit. It MUST NOT mention dictation or a hotkey: dictated words never appear on this screen.

**Input**

- **FR-008**: Users MUST be able to supply a file by dropping it on the screen or by Browse, which opens a file chooser titled "Choose an audio or video file" with an "Audio / video" filter built from the supported extensions and an "All files" alternative.
- **FR-009**: The supported extensions MUST be: wav, flac, ogg, oga, opus, aiff, aif, mp3, m4a, aac, wma, amr, ac3, alac, mp4, mov, webm, mkv, avi, flv, 3gp, m4v, wmv, ts. Matching MUST be case-insensitive.
- **FR-010**: A drag MUST be accepted only if it carries at least one local file with a supported extension. During busy state, drags and drops MUST be refused.
- **FR-011**: While a drag is accepted over the screen the drop zone MUST show an active highlight, and it MUST return to normal when the drag leaves or the drop completes.
- **FR-012**: Only one file is handled per run; when several are dropped, the first supported local file is used.

**Run**

- **FR-013**: On a pick, the screen MUST enter the busy state immediately: name the file, show "Transcribing…" with its size, clear any previous text, make the transcript read-only, disable Browse, and show the busy status line "Working. The window stays usable."
- **FR-014**: Transcription MUST run off the interface thread so the window stays usable.
- **FR-015**: A run MUST fail with a clear message, without starting work, when the backend is absent ("Backend unavailable."), the model is not ready ("Model isn't ready yet — wait for it to finish loading."), the backend cannot transcribe files ("This backend doesn't support file transcription."), the recording stack is not initialised, or the build has no file-transcription support.
- **FR-016**: The system MUST decode through two tiers: an in-process decoder for the lossless/OGG family first, then a bundled ffmpeg for everything else, including the audio track of video containers. The external decoder MUST be run without a console window on Windows, without reading standard input, and with a ten-minute ceiling.
- **FR-017**: Decoded audio MUST be mono, 16 kHz, 32-bit float before recognition; stereo MUST be averaged to mono; other rates MUST be resampled with the same algorithm as the microphone path.
- **FR-018**: Audio longer than the fixed chunk length MUST be recognised in consecutive chunks of that length, empty chunks skipped, and results joined with one space. The result MUST be empty only when every chunk was empty. The chunk length is the one the dictation path uses; its value is defined in `app/backends/onnx_backend.py`.
- **FR-019**: A file run MUST use the active model and the user-selected language for models that take one. It MUST NOT apply word timestamps or the silence filter.
- **FR-020**: A decode failure MUST be reported as a decode failure naming the file, and an inference failure MUST be reported as a model failure naming the file and the reason. Neither may be reported as "no speech".
- **FR-021**: "No speech heard" MUST be a distinct outcome, reported with its own message, and MUST NOT blank the screen's file identity.
- **FR-022**: A result that arrives for a file other than the one currently shown MUST be ignored.
- **FR-023**: File runs MUST NOT be written to History and MUST NOT go through the dictation delivery step (paste or clipboard).

**Transcript**

- **FR-024**: The transcript MUST be editable once a result has arrived and read-only while busy and on error.
- **FR-025**: The screen MUST remember what the model returned and show "Edited" in the file line exactly when the on-screen text differs from it; restoring the text MUST remove the note.
- **FR-026**: The file line MUST read, in order and where available, the file size, the processing time, the word count and "Edited", separated by a middle dot. Audio duration MUST NOT be shown, because the decode happens in the worker and the interface would be guessing.
- **FR-027**: The word count MUST be pluralised for English and Russian, and MUST move as the user edits.
- **FR-028**: Processing time MUST be shown in milliseconds below one second, seconds with one decimal below one minute, and minutes:seconds above.
- **FR-029**: File size MUST be shown in B, KB, MB or GB, in 1024 steps.
- **FR-030**: Copy MUST copy the text currently on screen and then show "Copied to clipboard." for a few seconds. Save MUST suggest `<source stem>.txt` in the source folder (or `transcript.txt` with no source), offer "Text (*.txt)" and "All files", write UTF-8, and report "Saved: <path>" or "Save failed: <reason>".

**Status line**

- **FR-031**: Anything that is not the file identity (busy note, failure, courtesy note, empty-result warning) MUST appear on a separate transient status line, so that "Copied" never overwrites the record of which file is shown.
- **FR-032**: Status kinds (busy, done, warning, error) MUST be visibly distinct in colour. Errors and warnings MUST stay until replaced; the Copied/Saved courtesy note MUST disappear by itself after a few seconds; dismissing a status MUST also clear the kind it wore.
- **FR-033**: A failure MUST show the file name, the file line "Failed", and a status line "Error: <message>".

**Per-run preset**

- **FR-034**: The screen MUST offer a preset picker and a checkbox labelled "Preset for this file" (tooltip: use the chosen preset for the next dictation only, without changing the default), shown only when two or more presets exist. The screen displays preset names it is given and MUST NOT hold its own opinion of what a preset is.
- **FR-035**: The picker MUST show the pinned preset if the override is live, else the default preset. A stale override MUST fall back to the default and untick the checkbox.
- **FR-036**: Ticking the checkbox MUST announce the shown preset as the override; unticking MUST announce an empty override. Choosing a row while the checkbox is unticked MUST tick it. Filling the picker programmatically MUST NOT announce anything.
- **FR-037**: The override MUST NOT be written to `config.yaml`. It is held by the state manager and applies to the next dictation's post-processing.
- **FR-038**: The checkbox MUST sit in a plain, unstyled holder so that a styled checkbox does not lose its layout spacing on macOS (Constitution IV).

**Operating-system file opens**

- **FR-039**: On macOS the application MUST accept a Finder "open" request for a file and announce each named path; the payload MUST be treated as a single path string or a list, never walked character by character, and `file://` URLs MUST be converted to local paths, with non-local URLs dropped. Paths MUST be made absolute.
- **FR-040**: A launch with file arguments MUST announce each existing regular file once the event loop next turns, after the first-run decision, and MUST ignore arguments that begin with a dash, directories, and paths that do not exist.
- **FR-041**: When the system asks to open a file the application MUST bring its window forward, including from the tray or a minimised state, before work starts, and MUST log the open; a missing file MUST log a warning and show "That file is no longer there." on the Transcribe screen.
- **FR-042**: The macOS bundle MUST declare audio and video document types (role Editor, alternate handler rank) and export the application's own audio and video type identifiers so Finder offers it for "Open With".
- **FR-043**: The file-open signal MUST be connected exactly once to the controller.

**Localisation**

- **FR-044**: Every visible string on the screen MUST be translatable (English and Russian) and re-render on a language change.

### Key Entities

- **Source file**: one local audio or video file, identified by absolute path; its name, size and extension are shown; it is never modified.
- **Run**: one transcription of one source file; has a start time, a state (busy, done, error), and a result text or a failure message.
- **Transcript**: the text on screen; has a baseline (what the model returned) and a current value (what the user sees); the difference between them is "Edited".
- **Preset override**: an optional preset id held for the next dictation only; never persisted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from a dropped supported file to editable text on screen without any additional step, and the window never blocks while they wait.
- **SC-002**: For every supported extension, a valid file is either transcribed or reported with a specific cause (unreadable, model not ready, model failed, heard no speech); no failure is reported as "no speech".
- **SC-003**: A recording of arbitrary length is transcribed without being given to the model in one piece; the longest single input the model receives is the chunk length.
- **SC-004**: Copy always delivers exactly the text on screen, including edits.
- **SC-005**: A double-click, "Open With" or launch argument for an existing file results in a visible window with a run in progress; for a missing file, in a visible window with an explanation.
- **SC-006**: Every format the screen names in its hint is accepted; narrowing support without updating the hint fails the test suite.
- **SC-007**: Per-format throughput and decode timings are not claimed here; if published, they live in `README.md`.

## Assumptions

- A model is loaded; there is no automatic wait. Dropping a file before the model is ready produces the "not ready" error and the user retries.
- One file at a time; batch processing, diarisation and per-segment timestamps are out of scope until the backend supports them.
- The bundled ffmpeg (from `imageio-ffmpeg`) is present in installed builds; running from a broken environment without it limits support to the in-process decoder's formats.
- Post-processing of file transcripts by a language model is not part of this feature; the preset picker on this screen configures the next dictation (see 005-llm-post-processing).
- The unrecognised-extension drop guard and the Info.plist type lists are independent, and the latter claims fewer extensions than the screen accepts; Finder "Open With" therefore offers the app for a narrower set than a drop does.

## Where it lives

Source:

- `app/gui/views/transcribe_view.py` - the screen: states, drop zone, extension list, size/time formatting, edited baseline, Copy, Save, status line, preset strip.
- `app/gui/controllers/_transcribe_mixin.py` - wires the view to the recording controller, filters stale results by path, raises the not-initialised errors.
- `app/gui/controllers/recording_controller.py` - `transcribe_file_async`: readiness and capability checks, worker thread, `file_transcribed` / `file_transcription_failed` signals, empty-result failure.
- `app/gui/controllers/app_controller.py` - `_on_file_opened_by_os`, preset-override wiring (`_on_preset_override_changed`), feeding the picker (`set_profiles`).
- `app/gui/main_window.py` - `QFileOpenEvent` handling, `_paths_from_file_open`, `queue_file_open`, `open_paths_from_argv`, `file_open_requested` signal.
- `app/gui/app.py` - announces launch arguments after `window.show()`.
- `app/backends/onnx_backend.py` - `transcribe_file`, `_decode_audio_file`, soundfile and ffmpeg tiers, `_transcribe_chunked`, `_CHUNK_SAMPLES`, `_resample`.
- `app/backends/subprocess_backend.py`, `subprocess_worker.py`, `registry_backend.py`, `base.py` - carry `transcribe_file` to the worker, ten-minute request ceiling, `TranscriptionError`.
- `app/state_manager.py` - `set_profile_override`, `profile_override_id` (not persisted).
- `setup.py` - macOS `CFBundleDocumentTypes` and exported type declarations.

Tests:

- `tests/gui/test_transcribe_view.py` - states, collapse, edited flag, copy, status colours and kinds, drop hint, preset strip, checkbox holder.
- `tests/gui/test_window_state_and_file_open.py` - file-open event decoding, launch arguments, missing file, window raise, logging, single connection.
- `tests/gui/test_app_entry.py` - startup file-open announcement.
- `tests/backends/test_onnx_asr_backend.py` - `transcribe_file` readiness, chunking and joining.
- `tests/test_audio_recorder_resample.py` - keeps the two resamplers identical.
