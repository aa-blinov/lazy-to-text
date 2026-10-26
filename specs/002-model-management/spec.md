# Feature Specification: Model Management

> **Note (spec 011):** this spec was written against the former Qt interface. The Electron interface (spec 010) replaced it and the Qt code was removed (spec 011). The behaviour described here is still the behaviour spec of the engine; mentions of `app/gui` below name files that no longer exist, and the equivalent lives in the Electron renderer (`desktop/renderer`) and the runtime (`app/server`).

> **Note (spec 012):** the Models list also carries one card that is not a speech model, the diarization model (download and delete only); see `specs/012-file-diarization/`.

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "The existing application's model catalogue, download, selection, deletion, per-model inference settings, execution-provider handling, first-run onboarding, model storage location, Hugging Face token and engine indicator, described as built."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - First run: get to a working dictation (Priority: P1)

A person who has just installed the app, with no model on disk, sees a dedicated setup screen instead of the application. It has three steps: choose, download, learn the key. Step 1 shows a single card for the app's recommended model with a one-sentence pitch and a Download button on the card itself. Step 2 shows a real progress bar, bytes done of bytes total, and elapsed seconds. Step 3 shows the configured start and stop hotkeys as key caps and a "Start dictating" button.

**Why this priority**: Without a model there is nothing to dictate with. Every other capability depends on a model being present and loaded.

**Independent Test**: Launch with an empty models folder and an `onboarding.complete` of false. The setup screen is shown with the sidebar and top bar hidden. Press Download, wait for the download, and the screen advances to the key step; pressing "Start dictating" shows the normal window and persists `onboarding.complete = true`.

**Acceptance Scenarios**:

1. **Given** no model weights on disk and `onboarding.complete` false, **When** the app starts, **Then** the first-run screen is in front, the sidebar and top bar are hidden, and navigation shortcuts do not change the page.
2. **Given** the first-run screen on step 1, **When** the user presses Download on the recommended card, **Then** the screen moves to step 2, the header reads "Downloading <model name>" with the download size, and the same model-switch code path as the Models view runs (the card, the top bar and the config are updated exactly as for a catalogue selection).
3. **Given** step 2 with a known total size, **When** progress events arrive, **Then** the bar shows a percentage and the line shows "<pct>% of ..." with megabytes, followed by elapsed seconds; **and when** the backend has not reported a total yet, **Then** the bar is indeterminate and the line shows bytes downloaded so far.
4. **Given** step 2, **When** the model state returns to idle, **Then** the screen checks the disk: if the weights are present it advances to step 3, if not it shows "The download did not finish." with the hint "Nothing was saved. Press the key on the card to try again." and the bar resets to zero.
5. **Given** step 3, **When** the user presses "Start dictating", **Then** the first-run screen is removed, the sidebar and top bar appear, and `onboarding.complete` is written as true exactly once.
6. **Given** step 1, **When** the user clicks "See all models instead", **Then** first-run mode ends for the session and the Models page is selected so any model can be picked there.

---

### User Story 2 - Browse the catalogue and choose a model (Priority: P1)

On the Models page the user sees one card per supported model, with name, aliases, size, measured accuracy and speed, languages and a description. The recommended card is first, the others follow by download size. They can search, filter by language or family, and sort. Selecting a card makes it the active model: it is downloaded if absent, loaded, and becomes the model used for every dictation.

**Why this priority**: Choosing and switching models is the core control of the product's accuracy, speed and language coverage.

**Independent Test**: Open the Models page. Type a query, pick a language filter, and change the sort order; the visible cards change accordingly. Press Select on a downloaded card; it becomes Active, the top bar pill shows the model, and the choice is stored in `whisper.model`.

**Acceptance Scenarios**:

1. **Given** the Models page, **When** it first opens, **Then** cards appear in catalogue order: the recommended model first, then by ascending download size.
2. **Given** a search query, **When** the user stops typing for a short debounce interval, **Then** only cards whose alias, canonical id, display name, description, languages or family contain the query (case-insensitive) remain visible.
3. **Given** no card matches the filters, **When** the filter is applied, **Then** an empty state "No models match your filters" with a hint to clear the search or pick a different family is shown instead of the list.
4. **Given** a card that is not cached, **When** the user views it, **Then** its primary button reads "Download"; **and** for a cached card it reads "Select".
5. **Given** a card, **When** the user clicks its family chip, **Then** only cards of that family are shown and the chip stays checked; clicking it again clears the family filter.
6. **Given** the sort control, **When** the user picks "Most accurate first", **Then** cards are ordered by ascending measured word error rate with unmeasured models last; "Smallest first" orders by download size; "Recommended order" restores the catalogue order.
7. **Given** a card, **When** the user expands "Show more", **Then** the full description replaces the three-line clamp and the control reads "Show less".

---

### User Story 3 - Switch model safely, watch it load, cancel (Priority: P1)

Selecting a model starts a background switch. The card shows "Loading..." with download percentage while weights arrive; the top bar shows "Loading: <alias>" with percentage or elapsed seconds and a Cancel button. The user can cancel; the app then returns to the previously active model.

**Why this priority**: A mis-picked 2 GB model must never trap the user, and a model switch must never freeze the window or lose the previous working selection.

**Independent Test**: Select an undownloaded model, press Cancel in the top bar before it finishes; the previously active card, top bar pill and `whisper.model` value come back.

**Acceptance Scenarios**:

1. **Given** an idle app with an active model, **When** the user selects another card, **Then** `whisper.model` and `whisper.compute_type` are written, the new card is marked active with a "Loading..." pill immediately, and the top bar shows the loading state before the backend reports it.
2. **Given** a load in progress, **When** the user presses Cancel, **Then** the backend abandons the load, the previous card is restored as active (or none if there was none), `whisper.model` and `whisper.compute_type` are rolled back to their previous values, and the top bar returns to the previous model.
3. **Given** a cancel that arrives after the load has already finished, **When** it is processed, **Then** nothing is rolled back and the new model stays active.
4. **Given** the app is recording, **When** a model change is requested, **Then** the recording is cancelled first and the switch proceeds; **given** a transcription is in progress, **Then** the switch is queued until it completes; **given** a load is already running, **Then** a second request is refused.
5. **Given** a load or recording or processing is running, **When** the user looks at the Models page, **Then** every Select/Download button is disabled (the page is locked whenever the state is not idle).
6. **Given** the model is cached, **When** it loads, **Then** the card pill shows plain "Loading..." (elapsed seconds appear only in the top bar); **and given** it is downloading, **Then** the pill shows a percentage when a total is known, otherwise bytes so far.

---

### User Story 4 - Delete a downloaded model (Priority: P2)

For a model that is on disk, is not active and is not loading, the card offers Delete. The user confirms, the weights are removed, and the card returns to "Download".

**Why this priority**: Model weights are large; users need to reclaim disk without leaving the app.

**Independent Test**: With a downloaded inactive model, press Delete, confirm, and verify the card flips to Download and the Storage size shrinks.

**Acceptance Scenarios**:

1. **Given** a cached inactive card, **When** the user presses Delete, **Then** a confirmation dialog "Delete cached model?" names the model and its size and warns that it must be downloaded again.
2. **Given** several aliases sharing one canonical repository, **When** deleting one, **Then** the dialog lists the sibling aliases that will also flip to "Download".
3. **Given** confirmation, **When** deletion runs, **Then** the button reads "Deleting..." and is disabled until the worker thread finishes, the window stays responsive, and afterwards all cards re-check the disk and the Storage size is recomputed.
4. **Given** a deletion that returns failure, **When** it finishes, **Then** a warning "Delete failed" is shown with the error text when there is one.
5. **Given** the active card or a card while loading, **Then** Delete is not shown.

---

### User Story 5 - Tune the active model (Priority: P2)

The active card reveals an inline "Inference settings" panel for models that have knobs. Whisper-family cards show language, VAD filter, beam size, temperature and initial prompt. Parakeet-family cards show a single "Include word + segment timestamps in output" checkbox. GigaAM-family cards (including T-One and Vosk) have no panel.

**Why this priority**: Language choice on a multilingual model changes whether it works at all for the user; the rest are convenience.

**Independent Test**: Activate a Whisper card, choose a language, and dictate; the choice is stored under `model_overrides.<alias>` and applied without restart. Restart the app and the panel shows the saved values.

**Acceptance Scenarios**:

1. **Given** the active Whisper card, **When** the user changes any field, **Then** the new values are persisted under `model_overrides.<alias>` and pushed live to the backend; for a non-active card nothing is pushed.
2. **Given** a card becomes active, **When** the page loads, **Then** the panel is pre-filled from the saved per-alias values without writing them back.
3. **Given** the language list, **Then** it offers Auto-detect, Russian, English, Spanish, French, German, Chinese, Japanese, Korean, Arabic, Hindi, Portuguese, Italian, Polish, Dutch, Turkish and Ukrainian; an unknown stored code shows Auto-detect.
4. **Given** the numeric fields, **Then** beam size is limited to 1-20 and temperature to 0.0-1.0 in steps of 0.1, with no spin buttons, and values read from config outside those bounds or of the wrong type are clamped or reset to defaults.
5. **Given** a model that declares a default source language for "auto" (Whisper Base and Canary 1B v2 default to Russian), **When** the language is left on Auto-detect, **Then** that default language is passed to the model; an explicit user choice always wins; other models keep true auto-detect.

---

### User Story 6 - Know which engine is running (Priority: P3)

The sidebar status widget shows an ENGINE pill with the ONNX Runtime execution provider the loaded model is actually using. It shows "Loading..." while a model loads and a dash when none is loaded. If an accelerator fails, the model runs on CPU and the pill says CPU.

**Why this priority**: Users judge speed by whether the GPU or the Neural Engine is in use; a pill that reports the requested provider rather than the real one would mislead them.

**Independent Test**: Load a model that is flagged CPU-only and confirm the pill shows CPU; load an accelerator-capable model on supporting hardware and confirm CoreML/CUDA.

**Acceptance Scenarios**:

1. **Given** no model loaded, **Then** the pill reads a dash; **given** a load in progress, **Then** it reads "Loading..."; **given** ready, **Then** it reads the real provider (CUDA, CoreML, CPU, TensorRT, DirectML, ROCm, Azure or the raw name).
2. **Given** an accelerator provider, **Then** the pill uses the accent colour; **given** CPU, **Then** the neutral colour, so a fallback is visible at a glance.
3. **Given** a model that is known to fail on accelerators, **When** it loads, **Then** the CPU provider is used directly without first waiting for an accelerator attempt to fail.

---

### User Story 7 - Choose where the weights live, and supply a Hugging Face token (Priority: P3)

In Settings, the Storage card shows the resolved models folder, whether it is the default, the size used, and offers Change..., Reset storage and Open folder. The Hugging Face card takes an optional API token and a Clear token button.

**Why this priority**: Large downloads must be placeable on another drive; a token is an escape hatch for gated repositories.

**Independent Test**: Press Change..., choose a folder containing no models, and verify new downloads land there; press Reset storage and verify the default is restored.

**Acceptance Scenarios**:

1. **Given** the Storage card, **Then** it shows the resolved path with "(default)" when `storage.models_dir` is empty, the used size (computing... while measured on a worker thread), and Reset storage is disabled while on the default.
2. **Given** Change... and a different folder with existing weights in the old root, **When** the folder is chosen, **Then** the user is asked Move / Leave / Cancel; Cancel changes nothing, Move relocates the `hub` folder in the background, Leave keeps old weights in place and only redirects new downloads.
3. **Given** a change is applied, **Then** `storage.models_dir` is saved, the live environment root is updated, every card re-checks its cache state, and a summary dialog states what moved and that new downloads land at the new location.
4. **Given** a storage change is in progress, **Then** further Change/Reset requests are ignored.
5. **Given** a token pasted and focus leaving the field, **Then** the token is stored in `huggingface.token`, mirrored into the process environment (`HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN`), and never written to the log; **given** Clear token, **Then** the field is emptied and the environment variables removed. Clear token is disabled while the field is empty.

---

### User Story 8 - Resume with what the user last chose (Priority: P2)

At launch the app loads the model the user last selected if its weights are present. If they are not, it loads the first model found on disk in catalogue order and writes that choice to config, so dictation works without a manual step.

**Why this priority**: A restart that leaves the user with "recording does nothing" is a regression of the core promise.

**Independent Test**: Delete the active model's folder outside the app, relaunch with another model downloaded, and confirm the other model loads and config is updated.

**Acceptance Scenarios**:

1. **Given** `whisper.model` names a cached model, **When** the app starts, **Then** that model loads in the background and its card is marked active.
2. **Given** `whisper.model` names a model that is not on disk but another is, **When** the app starts, **Then** the first cached model in catalogue order loads, `whisper.model` and `whisper.compute_type` are rewritten, and the log explains the swap.
3. **Given** `whisper.model` names an alias that is not in the registry, **When** the app starts, **Then** no card is marked active and a warning is logged; the stored value is not silently remapped.
4. **Given** nothing on disk, **When** the app starts, **Then** nothing loads and the first-run decision is made (see User Story 1).
5. **Given** the model is on disk, **Then** the first-run screen is never shown, regardless of the `onboarding.complete` flag (existing installs predate the flag).

---

### Edge Cases

- A partial download leaves only metadata files; a model counts as present only when at least one `.onnx` file exists in its cache snapshot, so a failed download never triggers auto-load or the "Select" state.
- A model that binds an execution provider at session creation and then throws on the first inference must not be reported as ready: one second of silence is run through the model before `ready` is published, and failure on an accelerator triggers a reload on CPU; failure on CPU is reported as an error.
- An accelerator failure at load is retried on CPU automatically; a load that fails after the user cancelled it is not reported as a model failure and is not retried.
- Cancel then immediately re-select must not start a second concurrent load: a retry is refused while the abandoned load thread is still unwinding.
- A load abandoned by Cancel must never publish its result into the live backend.
- If a precision-specific file (for example int8) is not in the on-disk copy, the loader is not handed a sealed directory that lacks it, so a precision switch downloads instead of failing with "file not found".
- A config naming a retired repository id leaves the model inactive with a logged warning and is never remapped to a different model.
- Download progress with an unknown total uses the catalogue size as a fallback total so percentages can be shown; the fallback is cleared when the state returns to idle so a later small download does not inherit it.
- Switching models inside one family re-points the existing inner backend; switching family rebuilds it, and the old session is destroyed on a background thread so the window never stalls.
- Selecting a model that is already active is a no-op.
- A model switch while another is loading is refused; while a transcription is in progress it is queued.
- The model catalogue holds the model's display name and description in English; they are translated at display time and a language switch re-renders cards, the first-run header and the progress text.
- A config with an unreadable or partial `model_overrides.<alias>` entry falls back to defaults for each bad field.
- Closing the app while a load is parked inside native code must not hang the quit; the process exits without waiting for it.

## Requirements *(mandatory)*

### Functional Requirements

**Catalogue**

- **FR-001**: The system MUST ship a fixed registry of 16 ONNX speech models, each with a short alias, a Hugging Face repository id, a display name, download size in megabytes, VRAM estimate, speed class (fast / medium / slow), quality class (basic / good / excellent), languages, a description, a precision hint (float32 / float16 / int8), a family label for display, and an engine family (whisper / gigaam / parakeet).
- **FR-002**: The registry MUST contain these aliases: whisper-large-v3-turbo, gigaam-v3-ctc, gigaam-v3-rnnt, gigaam-multilingual-ctc, fastconformer-ru, whisper-base, parakeet-tdt-v3, t-one, vosk-ru-small, vosk-ru, canary-1b-v2, gigaam-v2, gigaam-multilingual-large-ctc, parakeet-ctc-0.6b, parakeet-rnnt-0.6b, parakeet-tdt-v2.
- **FR-003**: Exactly one model MUST be flagged as recommended (GigaAM v3 CTC), carry a one-sentence pitch, appear first in every ordered list, and be the model offered on the first-run screen; "recommended" is a claim about where to start, not about accuracy.
- **FR-004**: The default order MUST be the recommended model first and the rest by ascending download size; the first-run screen and the Models page MUST use the same order from one definition.
- **FR-005**: Accuracy and speed figures shown on cards MUST come from the single measurement table in `app/model_mapping.py`, with unmeasured models rendered blank rather than as a guess; this spec does not restate them (see `README.md` and `app/model_mapping.py`).
- **FR-006**: Each model MUST be able to declare that it bypasses accelerator providers (known to fail on them), a loader id when the engine knows it under a different name than the repository, and a default source language to apply when the user leaves the language on auto.
- **FR-007**: A model MUST NOT be added to or removed from the registry without its card measurement being present or withdrawn together; a card claiming a repository is unreachable MUST first have its repository name checked.
- **FR-008**: Each card MUST link to the model's Hugging Face page and expose a screen-reader name that includes alias, repository id and link target.

**Browsing**

- **FR-010**: The Models page MUST provide a search field (debounced), a language filter (Any language, Russian, English, Multilingual), a sort control (Recommended order, Most accurate first, Smallest first), and a family filter reachable from each card's family chip; filters combine with AND.
- **FR-011**: The Multilingual language filter MUST match cards whose languages text contains "multilingual" or "langs".
- **FR-012**: Each card MUST show a metric line with WER, RTF, download size and VRAM, each with an explanatory tooltip, and a description that is clamped to three lines on the catalogue with a Show more / Show less toggle.
- **FR-013**: Cards MUST show a "Recommended" pill when applicable and an "Active" pill on the active card that changes to "Loading..." (with percentage or bytes when downloading) while a load is running.
- **FR-014**: Keyboard focus MUST enter at most one stop per inactive card (the card is a tab stop only while active), tabbing to a card MUST scroll it into view, and the search field MUST be focusable through the window's Find shortcut.

**Selection and loading**

- **FR-020**: Selecting a card MUST write `whisper.model` (the alias) and `whisper.compute_type` (the card's precision hint) to config, mark the card active, push the card's saved inference settings to the backend, update the top bar pill (using the short alias), and request the backend change on the next event-loop tick.
- **FR-021**: The backend change MUST run on a worker thread so the UI thread never waits on session teardown or creation.
- **FR-022**: The model state MUST be one of idle, recording, processing, model_loading; while the state is not idle the Models page MUST be locked and Select/Download/Delete disabled.
- **FR-023**: A model change requested during recording MUST cancel the recording first; during processing MUST be queued until the transcription ends; during loading MUST be refused with a user-visible log line.
- **FR-024**: Cancel MUST be offered in the top bar while a load runs; on a successful cancel the system MUST restore the previous active card, top bar pill, `whisper.model` and `whisper.compute_type`; if there was no previous model, `whisper.model` MUST be written as an empty string.
- **FR-025**: A cancel that finds no load in progress MUST NOT roll anything back.
- **FR-026**: A watcher MUST poll the backend until it reports ready, error or stopped; it MUST log a heartbeat about every 30 seconds and give up after 30 minutes with a warning, in all cases clearing the loading flag. Ready and error MUST each log a user-visible line.
- **FR-027**: The backend MUST publish `ready` only after a probe inference succeeds (see Edge Cases).
- **FR-028**: Weights MUST be considered present only when a `.onnx` file exists in a cache snapshot of the model's repository.
- **FR-029**: Cache state on each card MUST be computed on a worker thread; results of superseded checks MUST be discarded; all cards MUST re-check after a download finishes (state returns to idle), after a deletion, and after any storage change.

**Deletion**

- **FR-030**: Delete MUST be visible only when the model is present, not active, not loading, and MUST ask for confirmation naming the model and size, warning about shared repositories, and run off the UI thread.
- **FR-031**: Deleting MUST remove the whole repository cache directory for the model's repository in one operation so the cache state never reads as partially deleted; a failure MUST be reported to the user and logged.

**Inference settings**

- **FR-040**: Whisper-family cards MUST expose language, VAD filter, beam size (1-20), temperature (0.0-1.0), and initial prompt (multi-line); Parakeet-family cards MUST expose a single timestamps checkbox; GigaAM-family cards MUST expose none.
- **FR-041**: Settings MUST be persisted per alias under `model_overrides.<alias>` and loaded leniently (missing or wrong-typed entries take defaults; empty strings become none).
- **FR-042**: A change on the active card MUST be applied live to the backend without a reload; a change on an inactive card MUST be stored only.
- **FR-043**: Programmatic pre-fill of the panel MUST NOT emit a change (no write-back loop).
- **FR-044**: The inference-settings panel MUST lay out in two columns when wide enough and one column otherwise, and its multi-line prompt MUST scale with the application text size.

**Execution providers**

- **FR-050**: The system MUST resolve execution providers from a device preference (`auto`, `cuda`, `coreml`, `cpu`; default `auto`): on macOS `auto` prefers CoreML with CPU fallback; on Windows and Linux `auto` uses CUDA only after a real warm-up session proves it binds to CUDA, otherwise CPU; TensorRT is never auto-selected.
- **FR-051**: Models flagged as CPU-preferring MUST load on CPU regardless of the device preference unless it is already `cpu`.
- **FR-052**: Any accelerator failure at load or at the first inference MUST fall back to a CPU load once; the reported provider MUST be the real one after fallback.
- **FR-053**: When an NVIDIA GPU is present but CUDA runtime libraries are missing, the app MUST log a single warning explaining how to enable GPU acceleration and run on CPU.
- **FR-054**: The precision hint MUST be collapsed to the engine's two states: int8 for `int8`, full precision otherwise.
- **FR-055**: Inference MUST run in a separate worker process by default, with an in-process fallback only on the macOS bundle when the worker does not come up; the interface MUST be identical either way.

**Engine pill**

- **FR-060**: The ENGINE pill MUST be refreshed on every state change and on completion of a load, and MUST show Loading... while the state is model_loading.

**First run**

- **FR-070**: First-run MUST be shown only when no model weights are on disk and `onboarding.complete` is false; a model on disk always suppresses it.
- **FR-071**: First-run MUST have exactly three steps (choose, download, hotkey); the sidebar and top bar MUST be hidden during it; navigation shortcuts MUST be ignored during it.
- **FR-072**: The step 3 hotkey line MUST be built from the configured start and stop bindings, and MUST render no cap for an unbound key.
- **FR-073**: The step 2 detail line MUST be re-rendered from stored values on every progress event and language change, and MUST carry elapsed seconds while the download runs; progress MUST be real bytes, never a timer.
- **FR-074**: Advancing from the download to the key step MUST depend on the weights being found on disk, not merely on loading having stopped.
- **FR-075**: `onboarding.complete` MUST be set by the "Start dictating" button only, and the screen MUST re-appear on the next launch while no model is on disk and the flag is unset.
- **FR-076**: The "Set up later" link MUST be available on steps 1 and 2 and MUST NOT be shown on step 3. [NEEDS CLARIFICATION: the control is built and bound to a tooltip, but no action is connected to it in the current code; see Assumptions.]

**Storage**

- **FR-080**: The models root MUST resolve to `storage.models_dir` when non-empty, otherwise a per-user default; the resolved root MUST be mirrored into the process environment before the model library is imported at startup.
- **FR-081**: The Storage card MUST show path, "(default)" marker, used size, and the three actions Change..., Reset storage (disabled on default) and Open folder; Open folder MUST create the directory if missing and use the platform file manager.
- **FR-082**: Changing the folder MUST offer Move / Leave / Cancel when the old root holds weights, MUST move only the `hub` subfolder, and MUST apply the change atomically after the move completes; the used size MUST be recomputed on a worker thread.
- **FR-083**: Size accounting MUST NOT follow symbolic links, so linked copies are not double counted.
- **FR-084**: ONNX weights MUST additionally be exposed as a flat, link-based directory under the same root so the engine can resolve external data files without escaping the model directory.

**Hugging Face token**

- **FR-090**: The token MUST be optional, masked in the field, saved on focus loss, mirrored to the process environment immediately, and described as needed only for gated or private repositories.
- **FR-091**: The token MUST NOT appear in `app.log`, in the change log, or in any dialog (it is redacted wherever settings are logged).
- **FR-092**: `config.yaml` MUST be written readable only by the owner because it can contain the token.

### Key Entities

- **Model card (ModelInfo)**: A catalogue entry: alias (stable key), repository id, display name, size, VRAM, speed, quality, languages, description, precision hint, family label, engine family, CPU-preferring flag, loader id, default source language, recommended flag, pitch.
- **Measurement**: Per-alias word error rate and real-time factor from one repeatable benchmark; the single source for every surface that quotes accuracy.
- **Active model**: The alias stored in `whisper.model`; exactly zero or one at a time; reflected by the Models page, the top bar pill and the backend.
- **Inference settings**: A per-alias value bundle (Whisper: language, VAD filter, initial prompt, beam size, temperature; Parakeet: timestamps), stored under `model_overrides.<alias>`.
- **Backend state**: stopped, loading, ready, error; plus the real execution provider after any fallback.
- **Models root**: The folder holding the Hugging Face hub cache, the flat model directories, and any moved weights.
- **Onboarding flag**: `onboarding.complete`.
- **Hugging Face token**: `huggingface.token`; a credential.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user with an empty models folder reaches a loaded, dictation-ready model through the first-run screen in three steps, and the screen offers no control that competes with the single Download button.
- **SC-002**: After any combination of select, cancel, delete, folder change and relaunch, the active card, the top bar pill, `whisper.model` and the backend's loaded model agree.
- **SC-003**: The window remains responsive (no "not responding") during model switch, model deletion, folder move and size computation.
- **SC-004**: A model that cannot run (bad accelerator binding, broken graph) is reported as an error or runs on CPU before the user's first dictation; it is never reported ready and then silent.
- **SC-005**: No credential appears in `app.log` after any sequence of token edits.
- **SC-006**: Every figure on a model card equals the figure in the single measurement table, and the configured default model is the one the documentation calls the default.
- **SC-007**: Every catalogue string is available in English and Russian, and a language switch re-renders cards, first-run text and progress without restart.

## Assumptions

- The app is ONNX-only: there is one inference engine, and all models are downloaded from Hugging Face on first use; no model is bundled with the installer.
- The language of a model's accuracy figures is Russian speech; non-Russian-only models carry their measured numbers on that corpus, and the cards say so.
- No model currently in the catalogue requires a Hugging Face token; the token control remains for private or gated repositories a user may point the app at.
- The "device" preference (`whisper.device`) and the stored precision hint (`whisper.compute_type`) are read from config but are not exposed as controls; the default device is `auto`.
- The first-run "Set up later" control currently has no effect when clicked; whether it should dismiss first-run for the session is not specified by existing behaviour.
- Per-model inference values other than language (and the Parakeet timestamps flag) are persisted and shown but are not consumed by the engine today; the spec records the controls as they exist.
- The Electron interface reaches this capability through the shared domain stack; its parity is specified separately.

## Where it lives

Source:

- `app/model_mapping.py` - the registry (`ModelInfo`, `MODELS`, `MEASURED`, `display_order`, `get_model`, `alias_for`, `canonical_for`, `model_url`).
- `app/inference_settings.py` - `InferenceSettings` (Whisper) and `ParakeetInferenceSettings` value objects with lenient loading and clamping.
- `app/backends/base.py` - backend protocol, states, `TranscriptionError`.
- `app/backends/onnx_backend.py` - loading, provider resolution, CPU fallback, post-load probe, cancel, live inference-setting updates, real-provider detection.
- `app/backends/registry_backend.py` - alias resolution, family switch, precision collapse; in-process fallback backend.
- `app/backends/subprocess_backend.py`, `app/backends/subprocess_worker.py` - the separate worker process and its command protocol.
- `app/backends/_progress.py` - download progress callback plumbing.
- `app/cuda_bootstrap.py` - NVIDIA runtime preparation on Windows.
- `app/state_manager.py` - `request_model_change`, `cancel_model_change`, loading flag, watcher thread.
- `app/bootstrap.py` - `_autoload_persisted_model`, `_should_show_first_run`, `_apply_storage_path`, `_apply_hf_token`.
- `app/utils.py` - models root resolution, cache presence checks, deletion, size accounting, flat-model directory, move helper.
- `app/config_manager.py` - `whisper`, `onboarding`, `storage`, `huggingface` sections; secret redaction; owner-only config file.
- `app/gui/views/models_view.py` - search, filter, sort, lock, empty state.
- `app/gui/widgets/model_card.py` - the card, cache check worker, pills, Delete/Select states.
- `app/gui/widgets/inference_settings_panel.py`, `app/gui/widgets/parakeet_inference_settings_panel.py` - inline settings.
- `app/gui/views/first_run_view.py` - the three-step screen.
- `app/gui/main_window.py` - `set_first_run`, navigation guard.
- `app/gui/controllers/app_controller.py` - selection, cancel and rollback, deletion, progress fan-out, inference push, engine pill, token handler.
- `app/gui/controllers/_storage_mixin.py` - Storage card behaviour.
- `app/gui/views/shortcuts_view.py` - Storage and Hugging Face cards (hosted in Settings).
- `app/gui/widgets/topbar.py`, `app/gui/widgets/recording_status_widget.py` - model pill, Cancel button, ENGINE pill.
- `app/gui/app.py`, `app/recording_factory.py` - backend construction and startup order.

Tests:

- `tests/test_model_mapping.py`, `tests/utils/test_flat_model.py`, `tests/test_utils.py`.
- `tests/backends/test_onnx_asr_backend.py`, `tests/backends/test_registry_backend.py`, `tests/backends/test_subprocess_backend.py`, `tests/backends/test_vad_switch.py`.
- `tests/test_cuda_bootstrap.py`, `tests/test_config_manager.py`, `tests/test_config_hardening.py`, `tests/test_state_manager_async_change.py`.
- `tests/gui/test_models_view.py`, `tests/gui/test_model_card.py`, `tests/gui/test_parakeet_inference_settings_panel.py`, `tests/gui/test_first_run.py`, `tests/gui/test_bootstrap.py`, `tests/gui/test_app_controller.py`, `tests/gui/test_topbar.py`, `tests/gui/test_recording_status_widget.py`, `tests/gui/test_main_window.py`.
