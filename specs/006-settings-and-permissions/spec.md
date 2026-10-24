# Feature Specification: Settings and Permissions

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: Baseline description of the existing Settings screen (microphone, hotkeys, clipboard, appearance, storage, Hugging Face token), the macOS permission banners, the version footer and the About dialog, as the application ships today.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Change how a dictation is triggered and see at once whether the binding is usable (Priority: P1)

A user opens Settings, picks a recording mode (two keys, one toggle key, push to talk), types a hotkey, and the application applies it to the running listener without a restart. A binding the application cannot register is refused in words next to the field and is never written to disk.

**Why this priority**: The hotkey is the entry point of the product. A binding that saves but cannot register leaves a dictation app with no way to start, and the only trace is a log line.

**Independent Test**: Open Settings, type `ctrl+` into Start, leave the field. A reason appears under the field, the border is marked invalid, and `config.yaml` still holds the previous value. Type `ctrl+f8`, leave the field; the reason disappears and the value is persisted and live.

**Acceptance Scenarios**:

1. **Given** the mode is "Two keys", **When** the user types a valid combination into Start and leaves the field, **Then** the value is persisted and pushed to the live hotkey listener.
2. **Given** a field holds text that does not validate, **When** the field loses focus, **Then** an inline reason appears under it, the field is marked invalid, the field's accessible description carries the reason, and the previously valid value (or the platform default if none was ever valid) is what is persisted for that field.
3. **Given** one field is invalid, **When** the user toggles an unrelated control such as Auto-paste, **Then** the unrelated control still saves.
4. **Given** mode "One key: press to start and stop", **When** the user edits Start, **Then** Stop mirrors Start live and Cancel is persisted as empty.
5. **Given** mode "Push to talk: hold to record", **When** the user types `right_cmd` (macOS) or `right_alt` (Windows/Linux) into the Push-to-talk key field, **Then** it is accepted as a solo modifier, which is refused in every other mode.
6. **Given** the user switches from Two keys to Toggle and back, **When** they return to Two keys, **Then** the Stop value they had before is restored.

---

### User Story 2 - Pick and verify the microphone (Priority: P1)

A user chooses an input device, presses "Test microphone", speaks for three seconds and is told in plain words whether the level is fine, too quiet or silent.

**Why this priority**: An empty recording looks like a broken product; the test separates "wrong device or no permission" from "recogniser problem".

**Independent Test**: With a working input, press Test; a meter shows the live level for 3 seconds and the result line reads "Looks good." With a muted input the line reads "No sound detected. Check the selected microphone."

**Acceptance Scenarios**:

1. **Given** the app is idle, **When** the user presses "Test microphone", **Then** the button is disabled, a meter is shown, and the label reads "Listening... speak now (3 s)".
2. **Given** the test finished with peak below the silence threshold, **Then** the result is the "No sound detected" message in the "bad" style; between the silence and quiet thresholds it is the "Very quiet" message in the "warn" style; above, "Looks good." in the "good" style. The result's tooltip carries the raw peak and rms.
3. **Given** a recording or transcription is in progress, **When** the user presses Test, **Then** the test is refused with "wait until current operation finishes" and the microphone is not opened.
4. **Given** the test cannot run (no recording stack, no recorder, device error), **Then** the line reads "Test failed: <reason>" in the "bad" style and the meter is hidden.
5. **Given** a device is picked in the dropdown, **Then** the choice is persisted and applied to the recorder immediately.

---

### User Story 3 - Understand and fix a missing macOS permission (Priority: P1)

On macOS, a user whose hotkeys do not fire, whose recordings come back empty, or whose text is copied but not pasted sees a banner that names the exact System Settings pane and carries one button that fixes it.

**Why this priority**: Both failures are silent at the OS level (no error, no events, silent audio). Without a banner the app looks broken for a reason the user cannot find.

**Independent Test**: On a build without Accessibility access, open Settings: the Hotkeys card shows a banner and a "Grant access" button. After granting, returning to the window hides the banner and re-creates the hotkey listener without a restart.

**Acceptance Scenarios**:

1. **Given** hotkey-listening access is not granted, **When** Settings is shown, **Then** the Hotkeys card shows the Accessibility banner.
2. **Given** that banner, **When** the user clicks "Grant access", **Then** macOS is asked for access, and if it answers "no" without a prompt, the Accessibility pane of System Settings is opened so the click is never a no-op; the banners are re-evaluated 250 ms later.
3. **Given** microphone status "not determined", **Then** the Audio input card shows a banner with "Grant access", which triggers the system prompt; on completion (delivered on the GUI thread) the banner is re-evaluated.
4. **Given** microphone status "denied" or "restricted", **Then** the banner says the microphone is blocked and its button reads "Open Settings", opening the Microphone pane.
5. **Given** auto-paste is on and keystroke posting is not allowed, **Then** the Clipboard card shows a banner saying text can still be copied but Cmd+V will not reach the focused window, with an "Allow auto-paste access" button.
6. **Given** a permission changes from not granted to granted, **Then** the view announces a permissions change and the application re-enumerates microphones and restarts the hotkey listener.
7. **Given** the platform is not macOS, **Then** none of the three banners is ever shown.

---

### User Story 4 - Choose look and language (Priority: P2)

A user picks text size, theme (follow system, light, dark) and interface language (English, Russian). Each takes effect immediately and survives a restart.

**Why this priority**: Accessibility and comfort; not required to dictate.

**Independent Test**: Choose Dark; the window repaints at once without a restart. Restart; it is still Dark. Choose "Русский"; every label changes at once.

**Acceptance Scenarios**:

1. **Given** the Theme combo, **When** the user picks Light, **Then** the stylesheet is rebuilt and the whole window repaints, and the stored value is `light`.
2. **Given** the stored theme is `system`, **When** the app starts, **Then** it paints in whatever the operating system prefers, and the stored value stays `system` (it is not frozen to the resolved colour).
3. **Given** a text size of 150%, **Then** every text size in the app is multiplied while radii and spacing keep their size.
4. **Given** the Language combo, **When** the user picks Russian, **Then** every translated string, including combo items and banners, is re-read without a restart; the language names are always shown in their own language.
5. **Given** an unrecognised stored theme or language, **Then** the app falls back to `system` / `en` rather than refusing to start.

---

### User Story 5 - Control where models live and the Hugging Face token (Priority: P2)

A user sees where model weights are stored and how much space they take, moves the folder (optionally taking existing weights along), resets it, opens it in the file manager, and stores an optional Hugging Face token for gated models.

**Why this priority**: Weights are large and drives fill up; a token is needed for exactly the gated downloads.

**Independent Test**: Press "Change...", pick a folder; with cached weights present a three-way Move / Leave / Cancel question appears; afterwards the path label shows the new folder and new downloads land there.

**Acceptance Scenarios**:

1. **Given** the default location, **Then** the label shows the resolved path followed by "(default)" and "Reset storage" is disabled.
2. **Given** a custom location with cached weights at the old one, **When** the user picks a new folder, **Then** they are asked Move / Leave / Cancel; Cancel changes nothing, Leave switches the folder and leaves weights behind, Move relocates them first.
3. **Given** the user picks the folder already in use, **Then** nothing happens.
4. **Given** a long storage operation, **Then** Change, Open folder and Reset storage are all disabled until it finishes.
5. **Given** the token field is edited and loses focus, **Then** the token is persisted, exported to the live environment for the next download, and model cards re-evaluate their gated-model warnings.
6. **Given** a stored token, **When** the user presses "Clear token", **Then** the field empties, the environment variables are removed, and the button disables itself (it is enabled only when the field has text).

---

### User Story 6 - See which build this is (Priority: P3)

The window always shows its version at the bottom of Settings, and an About dialog shows the same version with a link to the project.

**Why this priority**: Every bug report starts with "which build".

**Independent Test**: Open Settings; the footer reads "Lazy to Text <version>", where `<version>` equals the version declared in `pyproject.toml`.

**Acceptance Scenarios**:

1. **Given** any scroll position, **Then** the version footer is visible and its text can be selected and copied.
2. **Given** a macOS menu bar, **When** the user chooses About Lazy to Text, **Then** a dialog with the app icon, the version and the project link opens.

---

### Edge Cases

- A hand-edited `ui.text_scale` outside the supported band is clamped to 0.85..1.75; a value that is not one of the five presets snaps to the nearest preset in the combo (a stored 0.9 shows 100%).
- A legacy config in which Start equals Stop and `mode` is `two_keys` is shown as Toggle mode.
- An invalid `mode` value shows Two keys.
- A config with an unregisterable hotkey loaded from disk: the field is marked invalid at load, and the first refusal falls back to the last value that passed validation in this session, or the platform default when none did.
- In Push-to-talk mode the Start, Stop and Cancel fields are read-only and styled muted; stale invalid markers on muted fields are cleared so no noise appears on inactive fields.
- Cancel is optional: empty means "no cancel hotkey"; in Toggle and Push-to-talk modes Cancel is persisted empty while the on-screen text is kept so switching back restores it.
- A device list that fails to enumerate shows only "System default".
- Device names are long: the popup is wider than the combo, without forcing a horizontal scrollbar on the page.
- A mic-test late tick after the result is shown must not repaint the frozen meter.
- Switching language while a mic-test result or a storage path is on screen re-renders those runtime strings in the new language.
- On a non-macOS platform the "Mute other sounds while recording" control does not exist at all.
- At text scale 175% the permission banner button never takes more than half the row, and the Settings page must not gain a horizontal scrollbar.
- The Hugging Face token is a credential: it is shown masked and is never written to the log in either direction.

## Requirements *(mandatory)*

### Functional Requirements

**Page structure**

- **FR-001**: The Settings screen MUST show a page header ("Settings", with a one-line purpose) and a row of jump links to the six cards in this order: Audio input, Hotkeys, Clipboard, Appearance, Storage, Hugging Face. Each link scrolls its card into view. The row wraps instead of cutting a link.
- **FR-002**: The card stack MUST scroll; the header, jump links and version footer MUST stay outside the scrolling area so the footer is always visible.
- **FR-003**: There MUST be no Save button. Each edit persists when committed: on focus loss for text fields, on change for combos, on toggle for checkboxes.
- **FR-004**: There MUST be no global "reset everything" control. Reset affordances are per card: "Reset hotkeys", "Reset storage", "Clear token".
- **FR-005**: Programmatic population of the screen from config MUST NOT cause a save.

**Audio input card**

- **FR-006**: The card MUST show a Microphone dropdown whose first entry is "System default" followed by every input device as `[index] name`, preselecting the configured device (system default when none).
- **FR-007**: A device change MUST persist to `audio.device` and be applied to the live recorder.
- **FR-008**: A "Test microphone" button MUST record three seconds, show a live level meter during the test and a frozen peak after it, and report one of three verdicts (silent, very quiet, good) in plain words with raw peak/rms only in a tooltip.
- **FR-009**: The test button MUST hand focus to the device dropdown before it disables itself so the cursor does not land inside a hotkey field.
- **FR-010**: A test MUST NOT start while the recording state is anything but idle, nor while another test is running.
- **FR-011**: On macOS only, a checkbox "Mute other sounds while recording" MUST persist `audio.mute_output_on_record` (default off). Where the platform cannot mute the output the checkbox MUST NOT be created.
- **FR-012**: On every platform, a checkbox "Skip silence (silero VAD)" MUST persist `audio.vad_enabled` (default off) and push the value to the live backend off the GUI thread. Its tooltip MUST say the first use downloads a small model.
- **FR-013**: On macOS, when microphone status is not determined, denied or restricted, a banner MUST be shown in this card (see Permission banners).

**Hotkeys card**

- **FR-014**: The card MUST offer a Recording mode combo with exactly three entries, stored as `two_keys`, `toggle`, `push_to_talk` and labelled "Two keys (Start + Stop)", "One key: press to start and stop", "Push to talk: hold to record".
- **FR-015**: The card MUST offer text fields: Start recording, Stop recording, Push-to-talk key (visible only in Push to talk), Cancel recording, each with a placeholder example taken from the platform default. The Cancel placeholder says empty turns it off.
- **FR-016**: Field availability per mode MUST be: Two keys - Start, Stop, Cancel active, PTT hidden; Toggle - Start active, Stop shows Start's value and is read-only, Cancel read-only and persisted empty, PTT hidden; Push to talk - PTT key active, Start, Stop and Cancel read-only, Cancel persisted empty.
- **FR-017**: A hotkey MUST be a `+`-separated list of recognised modifiers (`ctrl`/`control`, `shift`, `alt`/`option`, `cmd`/`command`/`win`/`windows`/`super`) followed by exactly one key that is a letter, a digit, `f1`..`f24`, or one of `space enter esc tab backspace delete insert home end page_up page_down up down left right` (aliases `return`, `escape`, `pageup`, `pagedown`, `del` accepted). Comparison is case-insensitive.
- **FR-018**: A key other than F1..F24 MUST have at least one modifier, otherwise it is refused (a lone `a` or `space` would swallow typing system-wide).
- **FR-019**: A solo modifier is permitted only in Push to talk and only from the per-platform list (right-side Cmd/Win/Super/Option/Alt/Shift/Ctrl and their aliases; `fn` on non-Windows platforms; Windows additionally accepts `right_window` and `right_menu`).
- **FR-020**: Validation MUST name the specific problem: empty hotkey; empty part around `+`; duplicate modifier; unrecognised modifier; final token is a modifier; unrecognised key; missing modifier. Cancel MAY be empty.
- **FR-021**: Cross-field conflicts MUST be refused only when each field parses individually: in Two keys, Stop equal to Start (message points to Toggle mode) and Cancel equal to Stop; in every mode, Cancel equal to Start.
- **FR-022**: A refusal MUST be shown as an inline reason under the field, a marked-invalid state, a tooltip and an accessible description; it MUST NOT depend on the tooltip alone.
- **FR-023**: A field that fails validation MUST NOT be persisted. The persisted value for it MUST be the last value that held while valid in this session, else the shipped platform default. Other fields in the same save MUST still persist.
- **FR-024**: Entering Toggle MUST snapshot the Stop value; leaving it MUST restore the snapshot.
- **FR-025**: Saving MUST write `hotkey.mode`, `hotkey.start_recording_hotkey`, `hotkey.stop_recording_hotkey`, `hotkey.cancel_recording_hotkey`, `hotkey.push_to_talk_key` and push them to the running listener in one batch; a listener failure MUST be logged and MUST NOT lose the saved config.
- **FR-026**: "Reset hotkeys" MUST restore mode, Start, Stop, Cancel and PTT key to the shipped platform defaults, leaving auto-paste, storage and token untouched, and update the empty-state key caps in other screens.
- **FR-027**: Shipped defaults are platform specific: macOS `ctrl+f8` / `ctrl+f9` / `ctrl+f10` and push-to-talk `right_cmd`; Windows and Linux `ctrl+f2` / `ctrl+f3` / `ctrl+f6` and push-to-talk `right_alt`. The push-to-talk minimum hold stays at its config value (`hotkey.push_to_talk_min_hold_seconds`) and has no control on this screen.
- **FR-028**: A hint under the card MUST say Cancel discards the current buffer instead of transcribing.
- **FR-029**: On macOS, in Push to talk with a solo modifier key, the generic "global hotkeys won't fire" banner MUST be suppressed.

**Clipboard card**

- **FR-030**: The card MUST offer "Auto-paste into the focused window", persisting `clipboard.auto_paste` (default on) and pushing it to the live clipboard manager.
- **FR-031**: The post-event banner MUST be visible only on macOS, only while auto-paste is on, and only when keystroke posting is known to be shut.

**Appearance card**

- **FR-032**: The card MUST offer Text size with five presets: 100% (default), 115%, 130%, 150%, 175%, persisted as `ui.text_scale`, applied at once, and applied before the first paint at startup.
- **FR-033**: The card MUST offer Theme: Follow the system (default, listed first), Light, Dark, persisted as `ui.theme`, applied at once. The stored value `system` MUST round-trip as `system`.
- **FR-034**: The card MUST offer Language: English, Russian, persisted as `ui.language` (default `en`), applied at once to every translated string including those set at runtime.
- **FR-035**: A hint MUST say changes apply immediately and that radii and spacing keep their size at any text scale.
- **FR-036**: Colours MUST come from the design tokens of the active theme, resolved where painted, so a theme switch repaints every widget.

**Storage card**

- **FR-037**: The card MUST show the resolved models folder (with "(default)" when it is the default), the space used (computed asynchronously, "..." while computing), and the buttons "Change...", "Reset storage", "Open folder", plus a hint that new downloads land in the new folder at once and old weights stay unless moved.
- **FR-038**: Changing the folder MUST ask, when cached weights exist at the old root, Move / Leave / Cancel; Cancel MUST leave config untouched; the probe and the move MUST run off the GUI thread; the final summary MUST state what moved or was skipped and why.
- **FR-039**: "Reset storage" MUST be enabled only when a custom folder is set and no storage operation is running; it MUST clear `storage.models_dir` and tell the user the default path.
- **FR-040**: "Open folder" MUST create the folder if missing and open it in the OS file manager; a failure MUST be reported in a dialog.
- **FR-041**: A storage change MUST take effect for new downloads without a restart and MUST refresh the Models screen's cache state.

**Hugging Face card**

- **FR-042**: The card MUST offer a masked token field with a clear-in-field button and a "Clear token" button enabled only when the field has text; the hint explains the token is optional, is needed for gated or private models, and links to the Hugging Face token page.
- **FR-043**: The token MUST persist to `huggingface.token`, be mirrored into `HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN` in the live environment (removed when empty), and MUST NOT appear in `app.log`.

**Permissions**

- **FR-044**: Three macOS banners (microphone, hotkey listening, auto-paste keystrokes) MUST re-evaluate whenever the Settings screen becomes visible and whenever the window is activated, so a grant made in System Settings is picked up on return with no restart.
- **FR-045**: Each banner MUST show one paragraph naming the exact System Settings pane and one action button capped at half the banner width; the two buttons that share the visible label "Grant access" MUST differ in accessible name and description.
- **FR-046**: Hotkey-listening and keystroke-posting access MUST be treated as separate gates; keystroke posting is considered available when either of its two paths is open.

**Version and About**

- **FR-047**: The footer MUST read "Lazy to Text <version>" with the version taken from the runtime metadata of the installed build and MUST agree with the version declared in the source tree.
- **FR-048**: The About dialog (macOS App menu, `AboutRole`) MUST show the app icon, the version, a one-paragraph description of the local engines and accelerators, and a link to the project.
- **FR-049**: `Cmd+,` / `Ctrl+,` MUST open Settings from anywhere in the application.

### Key Entities

- **Settings payload**: the twelve values the view reports on every save: start, stop and cancel hotkeys, auto-paste, device, mode, push-to-talk key, mute-output, VAD, text scale, theme, language.
- **Hotkey binding**: a modifier set plus one key, or (Push to talk only) a solo right-side modifier.
- **Permission state**: per capability (listen to keys, post keys, microphone) one of granted, not determined, denied/restricted, or not applicable on this platform.
- **Last valid binding**: per hotkey field, the last text that passed validation, used as the fallback when a later edit does not.
- **Models folder**: configured path or empty for the built-in default, with the weights below it.
- **Persisted settings**: `hotkey.*`, `audio.device`, `audio.mute_output_on_record`, `audio.vad_enabled`, `clipboard.auto_paste`, `ui.text_scale`, `ui.theme`, `ui.language`, `storage.models_dir`, `huggingface.token`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A binding the application cannot register is never present in `config.yaml` after any sequence of edits in this screen.
- **SC-002**: Every refusal of a hotkey is accompanied by a visible sentence naming the cause; no refusal is communicated by colour or tooltip alone.
- **SC-003**: A change of theme, language or text size is visible in the open window without a restart, and is still in effect after one.
- **SC-004**: After granting a macOS permission in System Settings, returning to the app clears the corresponding banner without a restart.
- **SC-005**: The Settings page has no horizontal scrollbar at any text scale preset at the minimum window width.
- **SC-006**: A credential entered in this screen is never present in `app.log`.
- **SC-007**: The version shown in the footer equals the version declared in the source tree for a fresh checkout and for an installed build.

## Assumptions

- Persistence goes through the shared configuration manager and its change log; the log redacts credentials by section and key and by name at any depth.
- Hotkey registration, the recorder and the clipboard manager are provided by the dictation pipeline (spec 001); this screen only edits and pushes configuration.
- Model downloading and the gated-model warnings on model cards belong to spec 002; this screen only supplies the token and the folder.
- The post-processing switch and its provider fields live on the Post-processing screen (spec 005), not here.
- The overlay, tray, topbar and window state restore are covered by spec 007.
- macOS permission checks are no-ops on other platforms.
- Supported languages are English (source strings) and Russian (compiled catalogue); a missing or unreadable catalogue leaves the UI in English and logs a warning.

## Where it lives

- `app/gui/views/shortcuts_view.py` - the Settings view: all six cards, jump links, banners, mic-test feedback, version footer, per-field save and fallback logic.
- `app/gui/views/_hotkey_validation.py` - Qt-free hotkey vocabulary, per-field validation, cross-field conflicts, solo-modifier lists per platform.
- `app/gui/views/_section_card.py` - shared card builder with explicit form alignments.
- `app/gui/views/_accessibility_check.py`, `app/gui/views/_microphone_check.py` - thin wrappers over the macOS probes for the view.
- `app/macos_permissions.py` - listen-event and post-event access probes and requests, Accessibility pane opener.
- `app/gui/controllers/app_controller.py` - `_wire_shortcuts`, `_on_shortcuts_save`, `_on_hotkeys_reset`, mic test, HF token env mirroring, permission-change refresh.
- `app/gui/controllers/_storage_mixin.py` - folder change, move, reset, open, size probe.
- `app/system_audio.py` - platform gate and CoreAudio mute used by the mute checkbox.
- `app/gui/theme.py` - tokens, themes, text scale clamp (0.85..1.75), `apply_theme`, `apply_text_scale`, `resolve_theme`, `normalise_theme`.
- `app/language.py`, `app/i18n/app_ru.ts`, `app/i18n/app_ru.qm` - language switching, bindings, native names.
- `app/config_manager.py` - `DEFAULT_CONFIG` (`hotkey`, `audio`, `clipboard`, `ui`, `storage`, `huggingface`), per-platform hotkey defaults, credential redaction.
- `app/gui/widgets/vu_meter.py` - level meter; `app/gui/widgets/page_header.py`, `flow_layout.py`, `app/gui/focus.py` (focus hand-off).
- `app/version.py`, `app/gui/main_window.py` (`_show_about_dialog`, `_install_app_menu`) - version and About.
- Tests: `tests/gui/test_shortcuts_view.py`, `tests/gui/test_hotkey_validation.py`, `tests/gui/test_language.py`, `tests/gui/test_theme.py`, `tests/gui/test_theme_fidelity.py`, `tests/gui/test_app_controller.py`, `tests/gui/test_main_window.py`, `tests/test_macos_permissions.py`, `tests/test_system_audio.py`, `tests/test_config_hardening.py`, `tests/test_version.py`.
