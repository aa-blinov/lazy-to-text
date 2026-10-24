# Feature Specification: Electron Interface on @monos/ui

**Feature Branch**: `010-electron-interface`

**Created**: 2026-10-24

**Status**: In progress

**Input**: User description: "Make an alternative interface entirely on https://github.com/aa-blinov/monos-ui and Electron, for Windows, Linux and macOS. Move all the functionality, including the popups, in the new style, and make the screens more convenient. Debug it."

## Summary

The application gets a second front end: an Electron window drawn with the
`@monos/ui` kit (warm paper, one 6px radius, text buttons, six themes in
light and dark). It is an alternative, not a replacement: the Qt interface
keeps working and both are served by one domain stack. The Electron
interface talks to a headless Python runtime (`app/server`) that owns the
microphone, the hotkeys, the models, the clipboard and the configuration.
Everything the Qt interface does (baseline specs 001 to 008) is available
in the Electron interface, with the omissions listed under Assumptions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dictate with the new interface (Priority: P1)

A user starts the Electron app. The runtime comes up, the model that was
active last time loads, and the global hotkeys work as before. They press
the start hotkey, speak, press stop, and the words arrive in the window
they were typing in. The capsule at the bottom of the screen shows that
the app is listening, then what happened to the words.

**Why this priority**: Dictation is the product. An interface that cannot
dictate is a mock-up.

**Independent Test**: With a model on disk, start the app, press the start
hotkey, speak, press stop. The text is pasted or copied and the capsule
reports which. The same test passes with the main window closed to the tray.

**Acceptance Scenarios**:

1. **Given** the app is running and the model is ready, **When** the user presses the start hotkey, **Then** the capsule appears on the screen under the pointer with a live level, and the tray icon shows recording.
2. **Given** a recording, **When** the user stops it, **Then** the capsule shows processing, then the delivery outcome (`pasted`, `copied` or `failed`) with the same wording rules as spec 001, then goes away; the confirmation is not cut short by the state returning to idle.
3. **Given** the capsule is visible, **When** the dictation moves from recording to processing, **Then** the capsule stays on the same display and does not move.
4. **Given** the main window is closed and a tray is available, **When** the user dictates, **Then** dictation works exactly as with the window open.
5. **Given** another copy of the application (Qt or Electron) holds the single-instance lock, **When** the Electron app starts, **Then** it says so and exits without opening a second engine on the microphone.

---

### User Story 2 - Choose and manage models (Priority: P1)

A user opens Models, sees every model in the catalogue with what it is
good for, downloads one, watches the progress, selects it, and cancels a
load that is taking too long.

**Why this priority**: Without a model nothing works, and a first run has
none.

**Independent Test**: On an empty models directory, the first-run screen
offers the recommended model; downloading it shows progress and ends in a
ready model; Models shows it as active.

**Acceptance Scenarios**:

1. **Given** no model on disk, **When** the app starts, **Then** the first-run screen is shown instead of the normal shell, offering the recommended model (spec 002).
2. **Given** a model that is not downloaded, **When** the user chooses Download, **Then** progress with bytes and elapsed time is shown and the model becomes selectable when it finishes.
3. **Given** a load in progress, **When** the user chooses Cancel, **Then** the load is abandoned and the previous active model is restored.
4. **Given** a downloaded model, **When** the user deletes it, **Then** they confirm first and the card returns to the not-downloaded state.
5. **Given** a model with its own inference settings, **When** the user edits them, **Then** they are saved per model and pushed to the running backend.

---

### User Story 3 - Transcribe a file (Priority: P2)

A user drops an audio or video file on the window (or opens one, or opens
one from the OS), watches it transcribe, edits the text and copies it.

**Why this priority**: The second main way to use the product; shares the
model and the backend with dictation.

**Independent Test**: Drop an audio file with a ready model; the
transcript appears, is editable, and `Edited` appears once changed.

**Acceptance Scenarios**:

1. **Given** a ready model, **When** the user drops a supported file anywhere on the window, **Then** it is transcribed and the transcript is shown with the file's identity line.
2. **Given** an unsupported or unreadable file, **When** it is dropped, **Then** the error says what went wrong (not "no speech detected") and the drop zone returns.
3. **Given** a transcript, **When** the user edits it, **Then** `Edited` is shown and Copy copies what is on screen.
4. **Given** the app is launched by opening a file in the OS, **When** the window is up, **Then** that file is transcribed.

---

### User Story 4 - Review history (Priority: P2)

A user opens History, searches and filters past dictations, copies one,
deletes one, exports all to a text file, or clears everything.

**Why this priority**: History is how a lost paste is recovered.

**Independent Test**: After two dictations, History lists both newest
first; searching for a word shows only the matching entry.

**Acceptance Scenarios**:

1. **Given** history enabled, **When** a dictation finishes, **Then** the entry appears without reopening the screen.
2. **Given** entries, **When** the user types in the search field, **Then** the list narrows as they type.
3. **Given** entries, **When** the user chooses Export, **Then** a save dialog opens and a text file is written.
4. **Given** entries, **When** the user clears history, **Then** they confirm first.

---

### User Story 5 - Post-process with a language model (Priority: P2)

A user opens Post-processing, ticks the switch in the language-model
settings, picks a provider, a model and what it should do, sets reasoning
effort, a token cap and a timeout, and the next dictation is rewritten
before it is pasted. If the model fails, the original text is delivered.

**Why this priority**: The newest feature (spec 005) and the reason the
speed controls exist.

**Independent Test**: With an unreachable server configured, dictation
still delivers the raw text and the Logs say why.

**Acceptance Scenarios**:

1. **Given** the settings card, **When** the user looks for the post-processing switch, **Then** it is in the language-model card with the other settings, not in a card of its own.
2. **Given** several presets, **When** the user picks one, **Then** the editor shows its fields; the preset picker is always visible and there is no control that folds it away.
3. **Given** a cloud endpoint, **When** the user edits the address, **Then** the line saying the text leaves the computer appears as they type.
4. **Given** a failing model, **When** a dictation finishes, **Then** the raw text is delivered and a user-facing log line names the failure.

---

### User Story 6 - Settings, permissions and diagnostics (Priority: P2)

A user changes hotkeys, recording mode, microphone, language and theme,
sees what the OS still has to grant, tests the microphone, and reads the
logs when something is wrong.

**Why this priority**: Parity with spec 006 and 008; without it the app
cannot be configured away from the defaults.

**Independent Test**: Rebinding the start hotkey takes effect without a
restart; the Logs screen shows the line that says so.

**Acceptance Scenarios**:

1. **Given** Settings, **When** the user captures a new hotkey, **Then** an invalid or conflicting binding is refused with the reason (spec 006 rules) and a valid one is applied live.
2. **Given** macOS without Accessibility, **When** Settings is shown, **Then** a banner offers to open the right pane; no restart is required after granting.
3. **Given** a microphone test, **When** the user starts it, **Then** a live level is shown and a result (peak, loudness class) at the end.
4. **Given** the Logs screen, **When** records arrive, **Then** they are coloured by level, filterable, and user-facing lines are distinguished from bookkeeping.

---

### User Story 7 - Look and feel (Priority: P3)

A user picks a light, dark or system theme and one of the kit's six
palettes, and the whole interface, including the capsule, follows.

**Why this priority**: The point of using the kit.

**Independent Test**: Switching the theme restyles every screen with no
reload and no component showing a colour of its own.

**Acceptance Scenarios**:

1. **Given** the system theme, **When** the OS switches between light and dark, **Then** the interface follows without a restart.
2. **Given** a palette choice, **When** it changes, **Then** every screen and the capsule use it.
3. **Given** Russian is selected, **When** any screen is shown, **Then** every string that has a Russian translation in the Qt catalogue is shown in Russian.

---

### Edge Cases

- The runtime process dies while the window is open: the window says so, offers Restart, and loses nothing the runtime had already written to disk.
- The runtime is slow to start (a cold Windows spawn): the window opens with a loading state rather than staying blank.
- A model load blocks interpreter exit: the runtime leaves without waiting (spec 008) so the lock is released.
- The window is closed while a dictation is processing: the dictation completes and is delivered.
- Two displays, one in full-screen: the capsule appears on the display under the pointer and over the full-screen app.
- A page in the window tries to navigate away or open a window: refused; web links open in the OS browser.
- A renderer that stops reading events (hidden, suspended) does not make the runtime's memory grow.
- Linux without a system tray: closing the window quits.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a headless runtime that builds the same domain stack as the Qt application without importing Qt, and exposes it over a loopback channel protected by a per-launch token and a Host-header check.
- **FR-002**: The runtime MUST publish state changes, engine, resource figures, download progress, input level, delivery outcomes, history changes and log records as events, and replay the latest state to a newly connected window.
- **FR-003**: The Electron shell MUST start the runtime as a child process, read its readiness line, hand the connection to the renderer through a narrow preload bridge, and stop the runtime on quit, escalating if it does not exit.
- **FR-004**: The renderer MUST be built with `@monos/ui` components and tokens; it MUST NOT define a colour, a radius or a font of its own.
- **FR-005**: Every screen in specs 001 to 008 MUST exist in the Electron interface, or be recorded under Assumptions as a deliberate omission.
- **FR-006**: The capsule MUST be a separate transparent, always-on-top, click-through window that never takes focus, appears on the display under the pointer, stays there for the whole dictation, and shows the delivery outcome for a short time after idle returns.
- **FR-007**: The tray (or menu-bar) icon MUST reflect the runtime state, offer Show window and Quit, and keep the app alive when the window is closed; without a tray, closing the window MUST quit.
- **FR-008**: Dialogs (open, save, choose folder, confirm) MUST be native, reached through the preload bridge; destructive actions MUST ask first.
- **FR-009**: Interface language (en, ru) and theme (light, dark, system) MUST follow `ui.language` and `ui.theme` in the shared configuration, and Russian strings MUST come from the existing Qt catalogue.
- **FR-010**: A setting changed in either interface MUST be the same setting in the other: both read and write the one `config.yaml`.
- **FR-011**: The Electron app MUST refuse to start a second engine when the Qt application or another Electron instance holds the single-instance lock.
- **FR-012**: The renderer MUST be navigable by keyboard: every screen has a shortcut (Cmd/Ctrl+1..6), focus order follows reading order, and every control has an accessible name.
- **FR-013**: Convenience over the Qt screens (the user asked for more convenient screens): a persistent status strip (state, model, engine, CPU/RAM/GPU); a search field in History and Models; model cards that can be filtered by language and sorted by size; drop-anywhere file transcription; undo for single history deletions through a toast; a hotkey capture field that records the key press instead of parsing typed text; settings grouped with in-page anchors; confirmations only for destructive actions, status as toasts.
- **FR-014**: Installable artifacts MUST exist for Windows (installer and portable), macOS (dmg or zip) and Linux (AppImage and deb), each carrying the runtime, built by CI from the locked dependency set.
- **FR-015**: Platform rules from the Qt application (microphone and Accessibility permissions on macOS, the hardened-runtime entitlements, the patched PortAudio) MUST be carried by the Electron macOS build.
- **FR-016**: Nothing the runtime logs or the interface stores may contain the user's words or a credential outside the places the Qt application already allows.

### Key Entities

- **Runtime**: the headless process; owns config, backend, state manager, hotkey listener, history and the event bus.
- **Connection**: `{port, token}`, created per launch, held by the Electron main process and given to renderers on request.
- **Event**: a named JSON payload from the runtime; some are sticky.
- **View**: one screen, a Svelte component that reads shared stores and calls RPC methods.
- **Capsule**: the overlay window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a model on disk dictates a sentence from the tray state using only hotkeys, with the same delivery outcomes as the Qt interface.
- **SC-002**: Every user-facing control listed in specs 001 to 008 is found in the Electron interface or in the omissions list; a checklist in the tasks file is ticked per screen.
- **SC-003**: The renderer contains no literal colour (checked by a test), and its screens render in all twelve theme and mode pairs.
- **SC-004**: The runtime test suite and the renderer test suite pass in CI on all three operating systems; the Qt suite is unchanged and passes.
- **SC-005**: Application start to a usable window, on a machine with a cached model, is not slower than the Qt interface by more than a second, measured with the same procedure.
- **SC-006**: Each platform produces an installable artifact that starts, shows the shell and reaches a ready runtime.

## Assumptions

- The Qt interface stays and is not removed by this feature; users choose which to run.
- Omitted on purpose: the Windows CUDA variant of the runtime is not packaged in the first Electron release; the in-app "restart to apply" flow of Qt is replaced by live apply everywhere it was possible.
- `@monos/ui` is consumed from its GitHub repository until it is published on npm.
- Hotkeys, auto-paste, audio feedback, microphone capture and model inference stay in Python; Electron's own global shortcuts are not used.
- Linux hotkeys and paste depend on the platform packages the runtime already uses (pynput, pyautogui); Wayland limitations are the same as the Qt interface's and are documented, not worked around.
- The Electron interface is verified on macOS in this change; Windows and Linux are verified by CI builds and the cross-platform tests, and any behaviour that cannot be checked there is listed in the plan under Known Gaps.

## Where it lives

- `app/server/`: the runtime (`runtime.py`), channel (`httpd.py`), event bus (`events.py`), method registry (`rpc.py`) and `handlers/`.
- `app/bootstrap.py`, `app/resource_sampler.py`: Qt-free startup and sampling shared with the Qt entry point.
- `desktop/electron/`: main process, preload, window and tray management, the runtime launcher.
- `desktop/renderer/`: Vite + Svelte renderer, `src/views/` for screens, `src/lib/` for the client and stores.
- `specs/010-electron-interface/`: this spec, the plan, the tasks and the RPC contracts.
