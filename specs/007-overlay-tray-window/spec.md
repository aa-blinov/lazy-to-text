# Feature Specification: Overlay, Tray and Window Shell

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: Baseline description of the existing Qt interface shell: the always-on-top recording capsule that also carries each dictation's delivery result, the system tray icon and menu, the top bar (model pill, cancel-load, resource gauges), the sidebar (navigation, engine and status chip, live input level), window chrome and state restore, the single-instance lock, close-to-tray, and the macOS application and Window menus.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See that the app is listening, then see what happened to the words (Priority: P1)

A user presses the dictation hotkey while working inside another application. A small capsule appears in the bottom-right corner of the screen they are looking at and says the app is recording. When they stop, the capsule says the app is transcribing, then says what happened to the text (a paste was sent, the text is on the clipboard, or delivery failed) with the text itself on one line, and goes away by itself.

**Why this priority**: The user is looking at their document, not at this app. The capsule is the only feedback that reaches them mid-sentence, and it answers the one question a dictation tool must answer: "did it go in?".

**Independent Test**: With the main window hidden, drive the state machine through recording, processing and a delivery report. The capsule appears, changes copy per state, shows the delivered text, and hides after its visibility period.

**Acceptance Scenarios**:

1. **Given** the capsule is hidden, **When** the state becomes `recording`, **Then** the capsule shows the title "Recording" and the body "Speak now" with the recording dot colour, anchored to the bottom-right of the user's current screen.
2. **Given** the capsule shows `recording`, **When** the state becomes `processing`, **Then** the title reads "Processing", the body reads "Transcribing speech", and the capsule does not move or disappear in between.
3. **Given** the pipeline reports a delivery of outcome `pasted`, **When** the capsule receives it, **Then** the title reads "Paste sent" (never "Pasted"), the body shows the delivered text collapsed to one line, and the capsule stays up for a fixed period before hiding.
4. **Given** the outcome is `copied` and a paste shortcut is supplied, **When** the capsule shows it, **Then** the title reads "Copied - press <shortcut>" (the em dash form used by the interface); without a shortcut it reads "Copied".
5. **Given** the outcome is `failed`, **When** the capsule shows it, **Then** the title reads "Delivery failed" and the body reads "Nothing was pasted. The reason is in Logs." and the dictated text is not shown.
6. **Given** a delivery confirmation is on screen, **When** the state machine reaches `idle` milliseconds later, **Then** the capsule stays up until the confirmation period ends.
7. **Given** a delivery confirmation is on screen, **When** a new recording starts, **Then** the confirmation timer is cancelled and the capsule shows the recording state.

---

### User Story 2 - The capsule stays put and stays visible (Priority: P1)

A user dictates while another display is in use, the app is hidden, another app is full-screen, or monitors are plugged and unplugged. The capsule still appears where they are looking, does not jump during a dictation, and never ends up off every screen.

**Why this priority**: A feedback surface that appears on the wrong display, or not at all, is indistinguishable from a broken app.

**Independent Test**: Place the cursor on a secondary display, start a dictation, move the cursor during it, then remove the anchor screen; the capsule follows the cursor's screen at the start only and re-anchors only when its screen disappears.

**Acceptance Scenarios**:

1. **Given** the cursor is on display B, **When** a dictation starts, **Then** the capsule appears at the bottom-right of display B's available area, with a fixed margin from the edges.
2. **Given** the capsule is up, **When** the user moves the mouse to another display during the dictation, **Then** the capsule stays on its original screen until it goes down.
3. **Given** the capsule is up, **When** its anchor screen is removed or a screen is added, **Then** the capsule is placed again; if the anchor is gone it falls back to the user's screen, then the primary screen.
4. **Given** the cursor is outside every screen (layout being rebuilt), **When** the capsule needs a screen, **Then** the primary screen is used and nothing raises.
5. **Given** another application is full-screen on macOS, **When** the capsule appears, **Then** it floats over that full-screen Space without taking keyboard focus, and re-orders itself onto the active Space when the user switches Spaces while it is up.
6. **Given** the app lives hidden in the tray on macOS, **When** the capsule appears, **Then** the app is un-hidden without being activated so the capsule is on screen and the user's focus stays where they are dictating.
7. **Given** a dictation passes from recording to processing, **When** the state machine runs, **Then** it does not dip through `idle`, so the capsule is not hidden and re-anchored mid-dictation.

---

### User Story 3 - Use the tray to bring the app back or quit (Priority: P1)

A user closes the main window. The app keeps running with a tray (menu-bar) icon that reflects what the app is doing. They can restore the window or quit from there.

**Why this priority**: The app is meant to live in the background so hotkeys work; closing the window must not end dictation, and quitting must be a deliberate, discoverable action.

**Independent Test**: Close the window with a tray present; the process keeps running and the window is hidden. Choose "Show window" and the window returns; choose "Quit" and the process exits.

**Acceptance Scenarios**:

1. **Given** a system tray is available, **When** the user clicks the window's close button, **Then** the window is hidden, the app keeps running, and its geometry is saved first.
2. **Given** no system tray is available, **When** the user closes the window, **Then** the app quits (close-to-tray is not enabled and a warning is logged at startup).
3. **Given** the window is hidden, **When** the user left-clicks or double-clicks the tray icon on Windows or Linux, **Then** the window is shown, raised and activated; right-click opens the menu.
4. **Given** macOS, **When** the user clicks the menu-bar icon, **Then** only the menu opens; the window does not appear until "Show window" is chosen.
5. **Given** the tray menu, **When** the user chooses "Quit", **Then** the window closes for real, the event loop ends and the tray icon is hidden on exit.
6. **Given** the backend state changes, **When** it becomes `idle`, `recording`, `processing` or `model_loading`, **Then** the tray icon image and tooltip change to match.

---

### User Story 4 - Know which model is active, loading, or missing, and cancel a stuck load (Priority: P2)

A user glances at the top bar to see which model is current, watches a model load with progress, and cancels a load they started by mistake.

**Why this priority**: Model loads can take a long time. The user needs a visible state and an exit.

**Independent Test**: Set an active model name, then switch the topbar to `model_loading` with progress and elapsed counters; the pill changes variant and the Cancel button appears and emits a cancel request.

**Acceptance Scenarios**:

1. **Given** no model is set, **When** the window is shown, **Then** the pill reads "No model" and the resource gauges are hidden.
2. **Given** a model is active, **When** the topbar is idle, **Then** the pill reads "Current model: <name>" and the resource gauges are visible.
3. **Given** the state becomes `model_loading`, **When** progress is known, **Then** the pill reads "Loading: <name>" followed by a percentage (capped at 99) or, when the total is unknown, a byte size; with neither, an elapsed-seconds counter once it exceeds zero.
4. **Given** the pill is loading, **When** the counter gains a digit, **Then** the pill does not change width.
5. **Given** the pill is loading, **When** the user presses Cancel, **Then** a cancel-load request is emitted; the button is visible only in the loading state.
6. **Given** the loading state ends, **When** the topbar returns to idle, **Then** progress and elapsed counters are cleared and the pill returns to active or empty.

---

### User Story 5 - Read system load and live microphone level (Priority: P2)

A user sees CPU, RAM and (when present) GPU and VRAM usage while a model is loaded, and a live input-level bar while recording.

**Why this priority**: Answers "did this model fit and is the machine saturated?" and "is the microphone picking me up?".

**Independent Test**: Push a metrics dictionary with and without GPU keys into the resource widget; blocks appear or collapse. Push levels into the level meter and watch the colour thresholds.

**Acceptance Scenarios**:

1. **Given** a metrics sample without GPU keys, **When** it is pushed, **Then** only CPU and RAM blocks are drawn.
2. **Given** a sample with GPU utilisation and VRAM totals, **When** pushed, **Then** GPU and VRAM blocks are added after CPU and RAM.
3. **Given** a bar value, **When** it is below 60 percent it is drawn in the success colour, below 85 in warning, otherwise in danger.
4. **Given** the state is `recording`, **When** the level meter receives amplitudes, **Then** the bar rises instantly and decays smoothly; in any other state it is reset to zero.
5. **Given** a level in [0,1], **When** it is below 0.5 the fill is success-coloured, below 0.85 warning-coloured, otherwise danger-coloured.

---

### User Story 6 - Navigate between screens and see backend status (Priority: P2)

A user switches between Models, Transcribe, History, Logs, Post-processing and Settings from a left sidebar, and sees the execution provider and recording status at its foot.

**Why this priority**: The sidebar is the app's only navigation.

**Independent Test**: Select each sidebar row and verify the matching view is current; narrow the window and verify the sidebar collapses to icons with tooltips.

**Acceptance Scenarios**:

1. **Given** the window is wide, **When** it is shown, **Then** the sidebar lists, in order, Models, Transcribe, History, Logs, Post-processing, Settings, each with an icon; the first is selected.
2. **Given** the window is narrower than the compact threshold, **When** it is resized, **Then** the sidebar shows icons only (names in tooltips), the status chip is hidden, and the topbar gutter follows the sidebar's width.
3. **Given** a model loaded on an accelerator, **When** the engine pill is refreshed, **Then** it reads the provider name in the accent state; CPU or no model reads as muted ("-" placeholder when none).
4. **Given** the keyboard, **When** the user presses Ctrl+1 to Ctrl+6 (Cmd on macOS), **Then** the matching screen is selected from anywhere.
5. **Given** the sidebar list has keyboard focus, **When** a row is selected, **Then** its fill lifts to the focus colour so focus is visible.

---

### User Story 7 - Launch behaviour: one copy, files from the OS, remembered window (Priority: P2)

A user launches the app twice, double-clicks an audio file in Finder, or reopens the app after moving it to another monitor.

**Why this priority**: These are the moments when the desktop, not the user, drives the app.

**Independent Test**: Take the single-instance lock in one process and start another; the second exits. Post a file-open event; the Transcribe flow starts. Save geometry on a screen then remove that screen; the window is centred.

**Acceptance Scenarios**:

1. **Given** one copy is running, **When** a second is started, **Then** it logs that it is a second copy, shows a warning dialog ("Another copy of Lazy to Text is already running. Use its system tray icon to bring it back, or quit it first.") and exits without opening a window.
2. **Given** the OS delivers a file-open request (macOS event, or a command-line path), **When** the window receives it, **Then** the window is brought forward (un-minimised if needed) and the file is transcribed; if the file no longer exists the Transcribe view shows "That file is no longer there."
3. **Given** a saved geometry and screen name, **When** the app starts and that screen is present, **Then** the window is restored in place.
4. **Given** the saved screen is gone, **When** the app starts, **Then** the size is kept and the window is centred on the primary screen, clamped to the work area where possible.
5. **Given** the window is hidden to tray, **When** the user clicks the Dock icon on macOS, **Then** the window is restored.

---

### User Story 8 - App menu with About, Settings and Quit (Priority: P3)

A user opens the application menu to read the version, open Settings, or quit; on macOS these appear under the Apple-logo application menu.

**Why this priority**: Platform convention, and the only keyboard route to quit.

**Independent Test**: Trigger each menu action; About shows version, Settings selects the Settings screen and reveals a hidden window, Quit exits regardless of close-to-tray.

**Acceptance Scenarios**:

1. **Given** the menu bar, **When** the user chooses About, **Then** a dialog shows the app icon, "Lazy to Text <version>", a short description and the repository link.
2. **Given** the window is hidden, **When** Ctrl+, (Cmd+, on macOS) is pressed, **Then** the window is shown and raised and the Settings screen is selected.
3. **Given** close-to-tray is on, **When** Ctrl+Q (Cmd+Q) or Quit is chosen, **Then** the app really quits.
4. **Given** the Window menu, **When** opened, **Then** it offers Minimize, Zoom (maximise or restore) and one entry per screen with its Ctrl+N shortcut.
5. **Given** a searchable view is current, **When** the platform Find shortcut is pressed, **Then** that view's search field is focused; on other views Find is disabled.

---

### Edge Cases

- **Unknown delivery outcome**: anything other than `pasted`, `copied`, `failed` is ignored; the capsule does not change.
- **Very long or multi-line text**: the body is collapsed to a single line and cut with an ellipsis at a width cap or the screen's available width minus margins, whichever is smaller; the full text is in History and the accessible description carries the whole text.
- **Empty text on a non-failure outcome**: the body reads "Copied to clipboard".
- **Language switch while up**: the capsule re-renders its copy in the new language and resizes; because the corner is a function of its size, it is placed again in the same corner.
- **Anchor screen deleted by the toolkit before the removal signal**: the capsule falls back to the user's screen instead of raising.
- **Dock icon on macOS**: shown only while the main window is visible and the capsule is not; accessory mode otherwise, so the capsule can float over full-screen apps. A failed policy switch is logged and never interrupts recording.
- **Mouse and focus**: the capsule is transparent to mouse events and never takes focus.
- **Tray not available**: the app logs a warning, runs without a tray, and quits on last window close.
- **Tray icon on macOS**: template (monochrome) icons that the system tints; a missing icon asset yields an empty icon rather than a failure.
- **Tray state outside the vocabulary**: setting an unknown state raises; the same applies to the topbar and status chip.
- **No `psutil` installed**: the sampler returns an empty sample and the widget keeps its last values.
- **No NVIDIA driver / NVML failure**: GPU keys are absent and the GPU blocks are not drawn; a failing GPU sample drops the GPU keys for that tick only.
- **Saved geometry blob is empty, undecodable or shorter than a valid blob**: ignored; the window opens at its default size.
- **File-open event payload shapes**: the OS may deliver a plain string, a list, or a `file://` URL; all are normalised to absolute local paths. A string is never iterated character by character.
- **First-run screen active**: sidebar and topbar are hidden and navigation is ignored until a model is ready.
- **Window minimised when closing**: geometry is not recorded.
- **A window on Windows**: the title bar is requested dark or light to match the palette in force when the window is built.

## Requirements *(mandatory)*

### Functional Requirements

**Recording capsule**

- **FR-001**: The system MUST show a frameless, always-on-top, non-focus-taking, mouse-transparent capsule for the `recording` and `processing` states and for each delivery outcome, and hide it on `idle`.
- **FR-002**: The capsule MUST carry, per state, a title, a one-line body, a state dot whose colour is bound to the state (recording, processing, pasted, copied, failed), and an accessible name and description that carry the state in words.
- **FR-003**: The capsule MUST keep one fixed height in every state, and size its width to its text, within a width cap and the screen's available width.
- **FR-004**: Delivery titles MUST name the outcome in the past tense, MUST NOT claim the target app pasted ("Paste sent", never "Pasted"), and a failed delivery MUST show the reason pointer instead of the text.
- **FR-005**: A delivery confirmation MUST be held for a fixed visibility period, MUST survive the `idle` state that follows it, and MUST be replaced by a new `recording` or `processing` state.
- **FR-006**: The capsule MUST be anchored once per appearance to the screen the user is looking at (cursor screen, else primary), MUST stay there for the whole appearance, and MUST be placed again when the display layout changes or its text size changes.
- **FR-007**: The capsule MUST be placed in the bottom-right corner of the anchor screen's available area with a fixed margin.
- **FR-008**: On macOS the capsule MUST float over full-screen apps and on all Spaces, MUST re-order itself when the active Space changes, MUST wake a hidden application without activating it, and MUST write its window state (hidden, policy, level, visible, on-active-space, screen) to the log on each appearance.
- **FR-009**: The state machine MUST go from recording to processing without passing through `idle`, so the capsule is not hidden between them.
- **FR-010**: All capsule copy MUST be translatable and re-read on every language switch; the shortcut and delivered text are shown as given.
- **FR-011**: The capsule MUST announce show/hide to the main window so the Dock icon can follow it.

**Tray**

- **FR-012**: The system MUST create a tray icon when the platform has a tray, with a menu of "Show window" and "Quit", and MUST translate both on language change.
- **FR-013**: The tray icon MUST have exactly four states (idle, recording, processing, model_loading) with distinct images (model_loading shares the processing image) and a one-line tooltip per state, "Lazy to Text: idle", "...: recording", "...: transcribing", "...: loading model".
- **FR-014**: On Windows and Linux a left click or double click MUST show the window; on macOS a click MUST only open the menu.
- **FR-015**: With a tray present, closing the window MUST hide it to the tray, MUST keep the application alive and save the window state; "Quit" and the app menu Quit MUST end the process for real.
- **FR-016**: On exit the tray icon MUST be hidden.

**Top bar**

- **FR-017**: The top bar MUST show a model pill with three variants (empty "No model", loading "Loading: <name> [counter]", active "Current model: <name>").
- **FR-018**: The loading counter MUST prefer percentage, then size, then elapsed seconds, and the pill MUST hold a width that fits the widest counter.
- **FR-019**: A Cancel button MUST be visible exactly while the pill is loading and MUST emit a cancel-load request.
- **FR-020**: The resource gauges MUST be visible whenever the pill is not empty and hidden when no model is set.
- **FR-021**: The resource gauge MUST draw CPU and RAM, plus GPU and VRAM when the host reports them, each as a label, a value and a bar coloured by load; its tooltip and accessible description MUST carry the same numbers as text.
- **FR-022**: Resource samples MUST be taken on a timer with a floor on the interval, one sample immediately at start, and none may break the UI if the sampling library or GPU library is missing.
- **FR-023**: Colours of every painted widget (gauges, level meter) MUST be resolved at paint time from the active palette, so a theme switch recolours them.

**Sidebar and status**

- **FR-024**: The sidebar MUST list six screens, in this order: Models, Transcribe, History, Logs, Post-processing, Settings; the persisted key for Settings remains the historical name.
- **FR-025**: The sidebar MUST be at least a base width, widen to fit its longest translated label, switch to an icons-only rail with tooltips when the window is narrow, and tell the top bar its width so the divider lines up.
- **FR-026**: The sidebar MUST show a status chip with the engine (execution provider) and the recording state, plus a live level bar; the state labels are Idle, Loading model..., Recording, Processing, and the engine placeholder is shown while no model is loaded.
- **FR-027**: Accelerator providers (CUDA, CoreML, TensorRT, DirectML, ROCm, Azure) MUST be shown in the accent state; CPU in the muted state, so a fallback to CPU is visible.
- **FR-028**: The level meter MUST rise at once to a louder sample and decay on quieter ones; it MUST be zero outside the `recording` state, and it MUST be updated by polling at a rate capped at the display's refresh and no more than 60 Hz.
- **FR-029**: The engine pill MUST follow the backend's actual provider and be refreshed periodically and on state changes.
- **FR-030**: The selected row MUST remain distinguishable under keyboard focus; hover MUST tint the icon.

**Window and launch**

- **FR-031**: The main window MUST open at a default size with a minimum size, remember its position and screen between launches, and restore it only if that screen still exists; otherwise it MUST keep the size and centre on the primary screen, clamped to the work area.
- **FR-032**: The window MUST emit its state when hidden or closed, except while minimised.
- **FR-033**: The system MUST allow only one running copy; a second copy MUST log its refusal, tell the user, and exit with no window.
- **FR-034**: The system MUST accept files from the OS (macOS file-open event, and command-line paths on every platform), normalise them to absolute local paths, bring the window forward, and start a transcription; a launch with a path MUST not transcribe behind the first-run screen.
- **FR-035**: The window MUST provide Find (platform shortcut) on views that can take it.
- **FR-036**: The application menu MUST provide About, Settings (Ctrl/Cmd+,), Quit (Ctrl/Cmd+Q), and a Window menu with Minimize, Zoom and a numbered entry per screen (Ctrl/Cmd+1..N); on macOS they appear in the standard application menu.
- **FR-037**: On macOS the Dock icon MUST be present only while the main window is visible and the capsule is not; a Dock click while the window is hidden MUST restore the window.
- **FR-038**: On Windows the title bar MUST be requested in the mode matching the palette in force when the window is built; failure MUST be silent.
- **FR-039**: A first-run state MUST hide the sidebar and topbar and show only the first-run page, and MUST restore them when a model becomes ready.

### Key Entities

- **Overlay state**: `idle`, `recording`, `processing`, or a delivery outcome (`pasted`, `copied`, `failed`) with a title, a body and a screen anchor.
- **Delivery report**: outcome, optional paste shortcut, delivered text.
- **Tray state**: idle, recording, processing, model_loading.
- **Model pill state**: empty, loading, active; with display name, progress text, elapsed seconds.
- **Resource sample**: CPU percent; RAM used, total and percent; optional GPU utilisation, VRAM used and total.
- **Window state**: opaque geometry blob plus screen name, persisted under the `window` config section (`geometry`, `screen`).
- **Navigation item**: key, label, icon.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a dictation with the main window hidden, the user sees a recording indicator, a processing indicator and a delivery result without touching the app, and every dictation ends with exactly one of three outcome titles.
- **SC-002**: The capsule never appears on a screen the user is not looking at, never moves during one dictation, and never ends up off every screen after a display change.
- **SC-003**: Closing the window never stops hotkeys from working when a tray exists, and quitting is possible from the tray, the app menu and the keyboard.
- **SC-004**: A second launch never opens a second window and always leaves a line in the log.
- **SC-005**: A saved window position is never restored onto a screen that is no longer present.
- **SC-006**: Every on-screen string of the capsule, tray and sidebar changes language without a restart.
- **SC-007**: Figures for the speed of these surfaces are not stated here; see `README.md`.

## Assumptions

- A global hotkey starts dictation while the user is in another app, so the cursor's screen is the best available proxy for the user's attention.
- No cross-platform API reports which screen another application's foreground window is on.
- The tray is available on most desktops; where it is not, the close button quits.
- Delivery results are reported by the state machine (see `001-dictation-pipeline`); the capsule only renders them.
- Resource sampling for the Qt top bar shares one sampler with the Electron interface (see `010-electron-interface`).
- Navigation keys, labels and view contents beyond the shell belong to their own specs (`002`, `003`, `004`, `005`, `006`, `008`).
- The `system_tray` section in the default config (`enabled`, `tooltip`) exists in `DEFAULT_CONFIG` but is not read by the Qt tray.

## Where it lives

Source:

- `app/gui/widgets/recording_overlay.py` - the capsule: copy per state, delivery titles and bodies, anchoring, Space observer, accessibility.
- `app/gui/placement.py` - cursor-screen lookup and bottom-right placement, plate height and margin.
- `app/gui/mac_window.py` - native macOS behaviour for floating over full-screen apps; logs window state.
- `app/gui/dock_presence.py` - Dock icon policy rule.
- `app/gui/widgets/tray_icon.py` - tray icon, states, tooltips, menu, per-platform icons (template SVGs on macOS).
- `app/gui/controllers/_tray_mixin.py` - hide-to-tray wiring, Show and Quit handlers.
- `app/gui/widgets/topbar.py` - model pill, loading counter, Cancel button, resource gauge hosting.
- `app/gui/widgets/resource_widget.py` - painted CPU/RAM/GPU/VRAM gauge.
- `app/resource_monitor.py`, `app/resource_sampler.py` - Qt timer wrapper and Qt-free sampler (psutil, NVML).
- `app/gui/widgets/sidebar.py` - navigation list, compact rail, focus and hover treatment.
- `app/gui/widgets/recording_status_widget.py` - engine and status chip with the level bar.
- `app/gui/widgets/vu_meter.py` - painted level meter.
- `app/gui/main_window.py` - shell, view stack, first-run switch, close-to-tray, window state save/restore, file-open handling, application and Window menus, Find, About.
- `app/gui/window_chrome.py` - Windows dark title bar request.
- `app/gui/app.py` - startup: single-instance gate and refusal dialog, tray creation, resource monitor, Dock-click restore, exit sequence.
- `app/instance_manager.py` - named mutex (Windows) or file lock (elsewhere).
- `app/gui/controllers/app_controller.py` - fans state out to topbar, sidebar, overlay, tray; VU and loading timers; engine pill refresh; delivery hand-off; window state persistence; OS file-open handling.
- `app/config_manager.py` - `window` (`geometry`, `screen`) and `system_tray` defaults.

Tests:

- `tests/gui/test_recording_overlay.py`, `tests/gui/test_mac_window.py`, `tests/gui/test_dock_presence.py`
- `tests/gui/test_tray_icon.py`
- `tests/gui/test_topbar.py`, `tests/gui/test_resource_widget.py`, `tests/test_resource_monitor.py`
- `tests/gui/test_sidebar.py`, `tests/gui/test_nav_focus.py`, `tests/gui/test_nav_icons.py`, `tests/gui/test_recording_status_widget.py`, `tests/gui/test_vu_meter.py`
- `tests/gui/test_main_window.py`, `tests/gui/test_window_state_and_file_open.py`, `tests/gui/test_window_chrome.py`
- `tests/test_instance_manager.py`, `tests/gui/test_app_entry.py`, `tests/test_state_manager_overlay_anchor.py`, `tests/test_state_manager_delivery.py`
