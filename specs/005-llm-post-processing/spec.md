# Feature Specification: LLM Post-Processing (Presets)

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: User description: "Describe the existing optional step that rewrites dictated text with a language model before it is pasted: modes, custom wording, providers, named presets, privacy line, the fall-back-to-raw contract, and the speed controls added in 0.1.21."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Tidy a dictation with a local model (Priority: P1)

A user who has a local Ollama daemon runs the app, opens the "Post-processing" screen, names a model, ticks "Rewrite dictated text before it is pasted", and dictates. The text that reaches the focused window is the recogniser's output after a language model added punctuation, capitals and paragraph breaks and dropped filler words. Nothing leaves the machine.

**Why this priority**: This is the feature. Everything else (providers, presets, speed controls) is a way of configuring this one step. Local-first is the default so that ticking the box without reading cannot send words away.

**Independent Test**: With a stub HTTP server on loopback that answers the Ollama chat shape, enable the switch, set a model name, run one dictation, and check that the delivered text is the server's reply and that the history entry holds the same text.

**Acceptance Scenarios**:

1. **Given** a fresh install, **When** the user opens the Post-processing screen, **Then** the switch is off, the provider is "Ollama (this computer)", the server is the loopback address on port 11434, the model is empty, the mode is "Clean up", and the privacy line says the text does not leave the machine.
2. **Given** the switch is on, a model is named, and the server answers, **When** a dictation finishes recognition, **Then** the reply replaces the recognised text before delivery, and the log says which preset ran, which provider and model, how long it took, and how many characters went in and came out (no words).
3. **Given** the switch is on but the model field is empty, **When** a dictation finishes, **Then** the step is skipped without any request and the recognised text is delivered unchanged.
4. **Given** the switch is off, **When** a dictation finishes, **Then** no request is made, whatever the other fields hold.

---

### User Story 2 - A failure never costs the user's words (Priority: P1)

The post-processing server is not running, answers an error, times out, or returns nothing usable. The user still gets their dictation, in its raw recognised form, and the app says in the Logs view and in the log what happened.

**Why this priority**: The product contract is that the words reach the window. An optional step must not break it (constitution, principle II).

**Independent Test**: Make the stub server refuse the connection, return HTTP 500, return `200` with empty text, return a non-JSON page, and sleep past the timeout; in each case the delivered text equals the recognised text and a warning is logged.

**Acceptance Scenarios**:

1. **Given** the server is unreachable, **When** a dictation finishes, **Then** the raw text is delivered and a warning "Post-processing failed (...) - delivering the raw transcription instead" is shown in the Logs view and written to the log, naming the failure class without any user words.
2. **Given** the server replies with an empty or whitespace-only text, **When** a dictation finishes, **Then** this counts as a failure, the raw text is delivered, and an empty paste never replaces the user's words.
3. **Given** the server replies with something that is not JSON, or JSON without the expected text field, **When** a dictation finishes, **Then** the step fails with a message naming the shape problem and the raw text is delivered.
4. **Given** the server does not answer within the preset's timeout, **When** the timeout expires, **Then** the step fails as unreachable and the raw text is delivered.

---

### User Story 3 - Choose what the step does (Priority: P2)

The user picks one of three language-preserving transformations, or writes their own instruction.

**Why this priority**: The first transformation is enough to ship; the others and the custom wording are refinements.

**Independent Test**: Select each mode and inspect the system message of the outgoing request; write a custom instruction and check it is sent together with the shared rules.

**Acceptance Scenarios**:

1. **Given** the mode picker, **When** the user opens it, **Then** it offers "Clean up", "Make concise" and "Formal prose" and nothing else.
2. **Given** a mode is selected and "Own wording" is empty, **When** a dictation runs, **Then** the system message is that mode's instruction followed by the shared rules.
3. **Given** "Own wording" holds text, **When** a dictation runs, **Then** the system message is the user's text followed by the same shared rules, so numbers stay digits and the language is never changed regardless of what the user wrote.
4. **Given** "Own wording" holds only whitespace, **When** a dictation runs, **Then** it is treated as empty and the mode's own instruction is used.
5. **Given** any mode, **When** a Russian dictation is processed, **Then** the instruction asks for the answer in the dictation's language, digits for numbers, typographic marks, removal of only accidental repetition, and plain text with no preamble.

---

### User Story 4 - Use a cloud or custom provider knowingly (Priority: P2)

The user selects a cloud service or a custom OpenAI-compatible server and supplies an API key. The screen says in words that the dictated text and the key go to a remote server.

**Why this priority**: Cloud models are the common alternative to a local one, but they are opt-in and must be honest about privacy.

**Independent Test**: Select each provider and verify that the server field is filled with its published address, that the privacy line flips between its two states as the address changes, and that the request shape and headers match the provider's dialect.

**Acceptance Scenarios**:

1. **Given** the provider picker, **When** it is opened, **Then** it lists, in order: Ollama (this computer), LM Studio (this computer), OpenAI, OpenRouter, Groq, DeepSeek, Together AI, Mistral, xAI (Grok), Cerebras, NVIDIA NIM, and "Custom OpenAI-compatible server...".
2. **Given** the server field is empty or holds an address that some provider supplied by default, **When** the user picks another provider, **Then** the field is rewritten to that provider's address; **and given** the user typed an address of their own, **Then** it is never overwritten, and picking Custom never rewrites it either.
3. **Given** the address points to a non-loopback host, **When** it is typed, **Then** the privacy line immediately (before the field loses focus) says "Runs on a remote server: the dictated text is sent there, along with the key."; for loopback, `localhost` or `0.0.0.0` it says the text does not leave and no key is needed.
4. **Given** an OpenAI-shaped provider with a key, **When** a request is sent, **Then** it is a POST to the base address plus `/chat/completions` with a bearer authorization header; **and given** Ollama, **Then** it is a POST to `/api/chat` with no authorization header and no streaming.
5. **Given** a config that names a cloud provider but no address, **When** a dictation runs, **Then** the provider's own address is used, never loopback (so a key is not sent to the user's own machine under the wrong assumption).
6. **Given** a config that names a provider this build does not know, **When** the editor opens it, **Then** the picker shows "Custom", never Ollama, and requests use the OpenAI shape.

---

### User Story 5 - Keep several presets and switch between them (Priority: P2)

The user keeps named bundles (for example "Work", "Letters", "Quick notes"): each holds provider, server, model, key, mode, own wording, reasoning effort, max tokens and timeout. One is the default; the Transcribe screen can pin another one.

**Why this priority**: Switching between a local model and a cloud model, or between wordings, would otherwise mean re-editing a form each time.

**Independent Test**: Create a preset, duplicate it, make it default, delete it, and check that the stored list, the default id, and the dictation pipeline follow each step.

**Acceptance Scenarios**:

1. **Given** an install from before presets existed (flat settings only), **When** the app starts, **Then** one preset named "Default" holding exactly those settings is written to the list, with the flat settings unchanged, and the screen opens on it.
2. **Given** the "Preset" card, **When** the user presses "New preset", **Then** a copy of the first preset named "<name> copy" with a fresh id is added and opened for editing.
3. **Given** a preset is open, **When** the user presses "Duplicate", **Then** a copy named "<name> copy" is added, including its API key, and the original stays open.
4. **Given** several presets, **When** the user presses "Delete", **Then** the open preset is removed and, if it was the default, the first remaining one becomes the default.
5. **Given** exactly one preset, **When** the screen is shown, **Then** Delete is disabled with a tooltip saying it is the only preset and to add another first.
6. **Given** a preset that is not the default, **When** the user presses "Use this one by default", **Then** it becomes the default and the button turns into a disabled "In use by default" with a tooltip saying so.
7. **Given** two or more presets, **When** the user opens the Transcribe screen, **Then** a "Preset for this file" checkbox and a preset dropdown are shown; ticking it (or picking a row, which ticks it) pins that preset for dictations without changing the default; unticking it returns to the default.
8. **Given** a pinned preset that has been deleted, **When** a dictation runs, **Then** the default preset runs and the dictation is not lost; the Transcribe dropdown shows the default, not an arbitrary first row.

---

### User Story 6 - Make a slow reasoning model fast enough for dictation (Priority: P3)

Added in 0.1.21. A reasoning model can spend seconds thinking before it tidies one sentence. The user sets a lower reasoning effort, caps the reply length, and sets a timeout, each per preset.

**Why this priority**: A refinement for users of reasoning models; the step works without it.

**Independent Test**: Set each speed control, capture the outgoing request, and check that the corresponding field is present only when the control is set.

**Acceptance Scenarios**:

1. **Given** the "Reasoning effort" picker, **When** opened, **Then** it offers "Provider default", "Off (fastest)", "Minimal", "Low", "Medium", "High", with "Provider default" the default.
2. **Given** effort is "Provider default", max tokens is "Provider default" (0), **When** a request is built, **Then** neither field appears in the request body, so a server that does not know them is never sent them.
3. **Given** an OpenAI-shaped provider and an effort, **When** a request is built, **Then** the body carries `reasoning_effort` with that value.
4. **Given** the Ollama provider and an effort, **When** a request is built, **Then** "Off" is sent as thinking disabled, "Minimal" as the "low" level, and "Low", "Medium", "High" as their own level.
5. **Given** a max-tokens cap, **When** a request is built for the OpenAI provider itself, **Then** the cap is sent as `max_completion_tokens`; for every other OpenAI-shaped provider as `max_tokens`; for Ollama as `num_predict` inside the options.
6. **Given** the "Timeout" control, **When** the user edits it, **Then** values from 1 to 600 seconds are accepted and the default is 20 seconds.

---

### User Story 7 - Credentials stay out of the log (Priority: P2)

The user's API keys, in every preset, are never written to `app.log`, not when saved, cleared or listed inside the preset list.

**Why this priority**: The log file is shown in the Logs view and nothing scrubs it afterwards; a leaked key there is a leaked credential.

**Independent Test**: Save a preset with a key and read the log output of the config change; the key never appears, in any nesting.

**Acceptance Scenarios**:

1. **Given** a preset with a key is saved, **When** the setting change is logged, **Then** the key value is replaced by a placeholder at any depth of the structure.
2. **Given** a failing request, **When** the failure is logged, **Then** the message contains the failure class and the address (with any `user:password@` prefix removed) but never the key, the response body, or the dictated text.
3. **Given** a preset with a key, **When** the user presses "Clear", **Then** the field is emptied, the stored key is removed from that preset (not from whichever preset is active), and the button disables until a new key is typed.

---

### Edge Cases

- A config value of the wrong type (for example a timeout of "fast", a negative token count, an effort of "turbo") falls back to the default of that field and never raises; a dictation is never stopped by a hand-edited config.
- A mode id this build does not know resolves to "Clean up".
- Two presets with the same id: the first wins and the second is unreachable by id.
- A preset with no name is shown by its id; the Name field falls back to the id on commit.
- An empty `profiles` list on disk falls back to the one implicit preset built from the flat settings; the "No presets left" notice (post-processing returns to its own settings, which use a local model on this computer) is shown only when the editor has no preset at all.
- A server reply larger than 2 MiB is refused as "too large to be text".
- HTTP error from the server: the message states the status code only, never the body (a proxy might echo the dictation).
- A connection failure names the Python-level failure class (for example connection refused), never the underlying message.
- The master switch on with a model that is not yet reachable on first launch of the daemon: the dictation waits up to the timeout, then falls back to raw text.
- A preset edit commits on focus-out of text fields and immediately for pickers and spin boxes, not per keystroke; the privacy line tracks the address per keystroke.
- When the preset list is repopulated (language switch, controller reload), the editor does not emit edits.
- A language switch relabels providers, modes and effort rows while keeping item ids and positions.

## Requirements *(mandatory)*

### Functional Requirements

**Switch and defaults**

- **FR-001**: Post-processing MUST be off on a fresh install and MUST be switched by a single global checkbox "Rewrite dictated text before it is pasted" on the Post-processing screen; the switch MUST NOT be part of any preset.
- **FR-002**: Defaults MUST be: provider Ollama, address `http://127.0.0.1:11434`, empty model, empty key, mode "clean", timeout 20 s, reasoning effort empty (provider default), max tokens 0 (no cap), no preset list and empty default-preset id.
- **FR-003**: The step MUST run only when it is enabled AND the resolved preset names a non-blank model; otherwise the recognised text MUST be delivered unchanged without any request.
- **FR-004**: The step MUST run after recognition and after the tray shows the processing state, and before delivery to the clipboard, so that the wait is visible.
- **FR-005**: The text recorded in History for a dictation MUST be the delivered (post-processed) text, without the trailing non-breaking space appended for delivery.

**Failure contract**

- **FR-006**: On any failure of the step the system MUST deliver the original recognised text and MUST report the fallback in the Logs view and in the log at warning level.
- **FR-007**: An empty, whitespace-only, non-string or missing reply text MUST be a failure, never delivered as an empty result.
- **FR-008**: Failures MUST be classified: "not reachable" (connection, DNS, timeout, OS errors; the log message names the address and the failure class) is distinct from "the model answered badly" (HTTP status, not JSON, wrong shape, too large, no text).
- **FR-009**: No failure message, log line or config-change record MAY contain the API key, the response body, the dictated text or the post-processed text. The post-processing success log MUST carry only the preset name, provider, model, duration and character counts.
- **FR-010**: Any `user:password@` prefix in an address MUST be removed before the address is quoted in a failure message.

**Modes and wording**

- **FR-011**: Exactly three modes MUST exist: "Clean up" (default; punctuation, capitals, paragraphs, drops filler and false starts, keeps every word that was meant), "Make concise" (same facts in fewer words), "Formal prose" (formal register, no salutation or sign-off, nothing added).
- **FR-012**: Every mode, and every custom wording, MUST carry the shared rules: answer in the dictation's language (never translate), write numbers as digits, use real typographic marks while keeping hyphens inside words, remove only accidental repetition, return plain text with no preamble, markdown or enclosing quotes.
- **FR-013**: A preset with non-blank "Own wording" MUST send that text plus the shared rules instead of the mode's instruction; a blank one MUST use the mode.
- **FR-014**: The screen MUST say, under the controls, that numbers are written as digits and nothing is translated, and that an own wording replaces the mode but not those two rules.
- **FR-015**: No mode requires an extra parameter such as a target language; adding translation later requires adding its field with it. [Deliberate constraint of the baseline]

**Providers and wire format**

- **FR-016**: The provider list and default addresses MUST be as in User Story 4; the wire dialect MUST follow the provider (Ollama dialect for Ollama only, OpenAI-compatible for all others, including unknown ids).
- **FR-017**: Requests MUST contain one system message and one user message holding the dictation, and no temperature for OpenAI-shaped providers (reasoning models answer 400 to any value but their default); Ollama requests MUST set temperature 0 and no streaming.
- **FR-018**: A bearer authorization header MUST be sent only for OpenAI-shaped providers with a non-empty key.
- **FR-019**: Whether an address is local MUST be derived from the address itself (loopback addresses, `localhost`, `0.0.0.0` are local; any other host, including unresolvable names and a blank host, is remote), not from the provider choice.
- **FR-020**: A reply MUST be read from `choices[0].message.content` for OpenAI-shaped providers and from `message.content` for Ollama, and the reply MUST be stripped of surrounding whitespace.
- **FR-021**: A provider-switch MUST NOT rewrite a server address the user typed, and Custom MUST NOT rewrite any address.

**Speed controls (0.1.21)**

- **FR-022**: Each preset MUST store a reasoning effort (empty, none, minimal, low, medium, high), a max-token cap (0 to 32768, 0 meaning none) and a timeout (1 to 600 s). Out-of-range values MUST be clamped, junk MUST fall back to the default.
- **FR-023**: An unset effort and an unset cap MUST be absent from the request. A set effort and cap MUST be mapped per provider as in User Story 6.
- **FR-024**: The max-token spin box MUST show "Provider default" at 0 and step by 64.

**Presets**

- **FR-025**: A preset MUST hold: id, name, provider, address, model, API key, mode, own wording, reasoning effort, max tokens, timeout.
- **FR-026**: One preset MUST always exist when the editor is populated from a real config: on startup, if the list is empty or absent, the implicit preset built from the flat settings MUST be written as the first preset, with the flat settings left untouched.
- **FR-027**: The flat settings MUST be mirrored from the default preset whenever a preset is edited, made default, deleted or its key cleared (when it is the default), so that older code paths and the stored file agree.
- **FR-028**: The last preset MUST NOT be deletable (button disabled and the handler refuses).
- **FR-029**: New presets MUST get an id not already taken (numbered suffix, never a collision) and start as a copy of the first preset; duplicates MUST be a copy of the open preset including its key.
- **FR-030**: Editing a preset MUST write the whole preset, not a field, and the editor MUST NOT emit anything while it is being populated.
- **FR-031**: The default preset MUST be recorded as a stored id; a stale or empty id MUST resolve to the first preset.
- **FR-032**: The per-run pin chosen on the Transcribe screen MUST NOT be written to the config and MUST fall back to the default preset when its id no longer exists. [See Assumptions: its scope]
- **FR-033**: The Transcribe preset strip MUST be hidden when there is only one preset.

**Screen**

- **FR-034**: The Post-processing screen MUST contain, top to bottom: a "Language model" card (intro line with the privacy statement, master switch, shared note, Name, Provider, Server, Model, API key with a "Clear" button, "What it does", Reasoning effort, Max tokens, Timeout, Own wording with its hint, privacy line) and a "Preset" card (Choose, Used by default, New preset / Duplicate / Delete), plus the empty-state notice when no preset exists.
- **FR-035**: The API key field MUST mask its value.
- **FR-036**: The "Clear" button MUST be enabled only while the key field is non-empty.
- **FR-037**: All labels, the provider and mode names, the effort rows, the hints and tooltips MUST be available in English and Russian and follow the interface language live.
- **FR-038**: The sidebar entry for the screen MUST be labelled "Post-processing".

### Key Entities

- **Settings section `llm`**: global switch `enabled`; the flat mirror of the default preset (`provider`, `model`, `base_url`, `api_key`, `mode`, `timeout_s`, `reasoning_effort`, `max_tokens`); `profiles` (list of presets; the config key keeps the old name) and `active_profile` (id of the default).
- **Preset**: one named bundle as in FR-025. Frozen value; read per dictation.
- **Mode**: id, label, description, instruction. Three exist.
- **Provider**: id, label, default address, dialect.
- **Request settings**: the preset resolved for one dictation, plus the finished system instruction.
- **Failure kinds**: unreachable versus bad answer.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every failure class in User Story 2, the text delivered equals the recognised text and a user-visible warning is recorded, in 100% of cases covered by the suite.
- **SC-002**: A fresh install makes no network request on dictation until the user has ticked the switch and named a model.
- **SC-003**: After saving presets with keys in any number of presets, a search of the log for any key value finds nothing.
- **SC-004**: With effort and cap unset, the request body contains none of the speed-control fields, for both dialects.
- **SC-005**: A config file written by a build before presets existed loads and dictates identically, with no manual migration.
- **SC-006**: A user can create, edit, make default and delete a preset from the Post-processing screen alone, and can pin a different one from the Transcribe screen, without restarting.

## Assumptions

- Speech recognition remains local; only the already-recognised text can reach the network, and only when the user enabled the step and pointed it at a non-loopback address.
- Calls use the standard library's HTTP client, not a new dependency; there is no streaming, no retries, and a single request per dictation.
- A reply is plain text; markdown or structured output from a model is not interpreted.
- The pin on the Transcribe screen is held in memory for the session. It is applied to dictations made by the hotkey pipeline; it is not read by file transcription, which does not run this step at all. The tooltip text ("for the next dictation only") and the code (the pin persists until unticked) differ; this baseline records the code behaviour.
- The Settings screen carries no copy of the switch or a preset-in-use line; the Post-processing screen is the only editor.
- Model names in the placeholder ("qwen3:8b, or gpt-5.4-mini") are examples; the app does not validate or list models.

## Where it lives

- `app/llm/__init__.py`: public surface of the package.
- `app/llm/client.py`: request building per dialect, `complete`, reply extraction, request settings and clamps, speed-control normalisation, address sanitising.
- `app/llm/errors.py`: failure kinds (`LLMError`, `LLMUnavailable`).
- `app/llm/modes.py`: the three modes, the shared rules and the shared note.
- `app/llm/providers.py`: provider list, default addresses, dialect, `is_local_url`, known-default set.
- `app/llm/profiles.py`: the `Profile` value, legacy flat-key resolution, default and override resolution, flat mirror, id generation.
- `app/state_manager.py`: `_postprocess_with_llm` (fall-back contract, logging), the pipeline hook after recognition, `set_profile_override`.
- `app/config_manager.py`: `DEFAULT_CONFIG["llm"]`, credential redaction (`_REDACTED_SETTINGS`, nested scrubber).
- `app/gui/views/presets_view.py`: the Post-processing screen.
- `app/gui/controllers/app_controller.py`: preset handlers (create, duplicate, delete, activate, key reset, first-preset materialisation, switch handler, override handler).
- `app/gui/views/transcribe_view.py`: the "Preset for this file" strip.
- `app/gui/widgets/sidebar.py`: sidebar entry. `app/gui/main_window.py`: hosts the view.
- `app/i18n/app_ru.ts`: Russian strings.
- `CHANGELOG.md` (0.1.21): speed controls, switch moved into the settings card, preset picker always shown.
- Tests: `tests/test_llm_client.py`, `tests/test_llm_providers.py`, `tests/test_llm_profiles.py`, `tests/test_llm_pipeline.py`, `tests/test_config_hardening.py`, `tests/gui/test_presets_view.py`, `tests/gui/test_presets_controller.py`, `tests/gui/test_transcribe_view.py`.
