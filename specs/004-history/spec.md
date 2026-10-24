# Feature Specification: History

> **Note (spec 011):** this spec was written against the former Qt interface. The Electron interface (spec 010) replaced it and the Qt code was removed (spec 011). The behaviour described here is still the behaviour spec of the engine; mentions of `app/gui` below name files that no longer exist, and the equivalent lives in the Electron renderer (`desktop/renderer`) and the runtime (`app/server`).

**Feature Branch**: `[none - baseline]`

**Created**: 2026-10-24

**Status**: Implemented (baseline)

**Input**: Baseline description of the existing behaviour: the local record of past dictations, its on-disk store, and the History screen that browses, copies, exports and clears it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find and re-use something I dictated earlier (Priority: P1)

After a dictation is delivered, the user can open History, see it at the top of a table (newest first), and copy its text back to the clipboard, because the first paste went to the wrong window, was overwritten, or is needed again.

**Why this priority**: This is the safety net behind the product promise that a dictation never loses the user's words. A delivered dictation that cannot be recovered later is a lost dictation.

**Independent Test**: Dictate one phrase with delivery succeeding, open History, select the top row, press Copy, paste elsewhere. The pasted text equals the dictation.

**Acceptance Scenarios**:

1. **Given** a dictation was just delivered (pasted or copied), **When** the user opens History, **Then** one new row is at the top showing time, text, model alias, language and duration.
2. **Given** History is open while a new dictation lands, **When** the entry is stored, **Then** it appears at the top without resetting the scroll position or the current selection.
3. **Given** a row is the current row, **When** the user presses Copy, Enter (in the table) or the platform Copy key, **Then** that entry's full text is placed on the clipboard.
4. **Given** nothing is selected or History is empty, **When** the user looks at Copy, **Then** the Copy button is disabled and so are the Enter and Copy-key shortcuts.

---

### User Story 2 - Search my history (Priority: P2)

The user types in the search box and the table narrows to entries whose text contains the typed string, ignoring case.

**Why this priority**: History grows to hundreds of entries; scanning is not workable without search.

**Independent Test**: With several entries, type a word present in only one; only that row remains.

**Acceptance Scenarios**:

1. **Given** a populated history, **When** the user types in the search field, **Then** filtering is applied after a short pause following the last keystroke (not on every keystroke) and matches only the Text column, case-insensitively.
2. **Given** an active search that matches nothing, **When** the result is empty, **Then** a "No matching transcriptions" state is shown (not the "nothing dictated yet" state) and the count shows "N of TOTAL entries" with the true total.
3. **Given** a search is active, **When** the user presses Escape anywhere in the view (caret in the field or in the table), **Then** the search is cleared immediately and the full list returns.

---

### User Story 3 - Read a long transcription in full (Priority: P2)

Long entries are cut off in the table. Double-clicking a row opens a modal dialog with the metadata and the complete text, with a Copy text button.

**Why this priority**: Without it a long dictation could only be read by pasting it somewhere.

**Independent Test**: Add an entry longer than the column; double-click it; the dialog shows the whole text and Copy text copies all of it.

**Acceptance Scenarios**:

1. **Given** a row, **When** the user double-clicks it, **Then** the "Transcription details" dialog opens showing Time, Model, Language and Duration chips and the full text in a read-only box.
2. **Given** the dialog is open, **When** the user presses Copy text, **Then** the full text is on the clipboard; **When** Close, **Then** the dialog closes.
3. **Given** the pointer rests on a Text cell, **When** the tooltip appears, **Then** it carries the full text; on a Model cell it carries the full model identifier (the cell itself shows the short alias).

---

### User Story 4 - Export my history to a text file (Priority: P3)

The user exports every stored entry to a plain-text file at a location they choose.

**Why this priority**: Portability and backup; not needed for day-to-day use.

**Independent Test**: With entries present, press Export, choose a path; the file exists and lists every entry.

**Acceptance Scenarios**:

1. **Given** at least one entry, **When** the user presses Export and chooses a path (default name `transcription_history.txt`, filter "Text files (*.txt)" plus "All files"), **Then** the file is written off the UI thread, the Export button reads "Exporting…" and is disabled until finished, and a "History exported" notice reports the count and path.
2. **Given** the history is empty, **When** the user presses Export, **Then** a "Nothing to export" notice appears and no file dialog opens.
3. **Given** the destination cannot be written, **When** the export finishes, **Then** an "Export failed" warning tells the user to check the destination path and permissions.
4. **Given** the user cancels the file dialog, **Then** nothing happens.
5. **Given** an export is already running, **When** Export is triggered again, **Then** the second request is ignored.

---

### User Story 5 - Clear my history for good (Priority: P3)

The user can delete every stored dictation after an explicit confirmation, and "cleared" means gone from disk.

**Why this priority**: Privacy. The history file holds the user's own words in clear text.

**Independent Test**: Press Clear history, confirm; the table shows the empty state and the history file on disk is empty.

**Acceptance Scenarios**:

1. **Given** entries exist, **When** the user presses Clear history, **Then** a confirmation "Clear history?" states how many transcriptions will be deleted and that it cannot be undone.
2. **Given** the user confirms, **Then** the in-memory list, the on-disk file and any legacy-migration backup copy are all emptied/removed, and the view shows the empty state.
3. **Given** the user declines, **Then** nothing changes.
4. **Given** the history is already empty, **When** Clear history is pressed, **Then** nothing happens and no confirmation is shown.

---

### User Story 6 - History survives restarts and upgrades (Priority: P2)

Entries persist across launches. A history written by an old release in the flat JSON format is imported once.

**Why this priority**: Losing the record on restart would defeat it; losing it on upgrade would be a silent data loss.

**Independent Test**: Add entries, construct a new manager over the same file, entries and order are identical.

**Acceptance Scenarios**:

1. **Given** entries were stored in a previous session, **When** the app starts, **Then** they are loaded newest first.
2. **Given** only a legacy `transcription_history.json` exists next to where the JSONL file would be, **When** the app starts, **Then** its entries are imported, sorted by time, written as the JSONL file, and the legacy file is renamed with a `.bak` suffix so the import does not repeat.

---

### Edge Cases

- **Empty or whitespace-only text** is never stored; `add_entry` returns without writing.
- **Delivery failed** (text reached neither the clipboard nor the window): the dictation is not added to History. A failed keystroke with a successful copy still counts as delivered and is stored.
- **Stored text** is the text after optional LLM post-processing (what was delivered), trimmed, without the trailing non-breaking space the delivery step appends.
- **Entry cap**: when the number of entries exceeds `max_entries`, the oldest are dropped from memory immediately; on disk the file is compacted when it has accumulated more than a fixed slack of stale lines beyond the cap, and on load when it holds more lines than are kept.
- **Corrupt lines** in the JSONL file are skipped with a warning; the rest load. An unreadable file yields an empty history and an error log, not a crash.
- **Corrupt legacy file** (unreadable, not a JSON array, non-object items, invalid items): unusable items are skipped; a non-array top level skips migration entirely.
- **Failed write**: append, compact and clear failures are logged and swallowed; a failed compaction removes its staging file so a second full copy of the user's words does not linger.
- **Clear** must also delete the `.json.bak` migration backup; failing to delete it must not stop the real clear.
- **Search while entries arrive**: the new entry respects the active filter; the "entries" count reflects shown versus total.
- **Entry with empty text** (can exist in a file) is not copyable: Copy stays disabled and the clipboard is never overwritten with an empty string.
- **Window first shown before any entries were set**: the view must not fail (an event handler that indexes not-yet-computed column widths once killed the process).
- **Font or text-scale change** re-fits column widths without raising.
- **Very long history** (cap-sized): dragging the window to resize must stay responsive; column widths are measured once per data change, not per resize step.
- **History disabled** (`history.enabled` false): no history manager exists, nothing is stored, and the History screen shows the empty state with no working Clear or Export (those signals are not connected); Copy still works for rows if any were set.
- **File transcriptions** done in the Transcribe view are not added to History (only live dictations are); the screen subtitle says "dictation and transcription" but see Assumptions.
- **UI language**: headers, buttons, states and the count are translated (en/ru); the count uses plural forms; the model column shows the short alias and the language column shows the stored language code or `auto`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST record one history entry for each dictation whose text was delivered, with timestamp, text, audio duration in seconds, model identifier and language (`auto` when none is set).
- **FR-002**: System MUST NOT record an entry when the final text is empty or only whitespace, nor when delivery outcome was "failed".
- **FR-003**: System MUST store the text that was delivered (after any LLM step), trimmed, and MUST NOT include the delivery-only trailing non-breaking space.
- **FR-004**: System MUST persist entries in a JSON Lines file (one JSON object per line, oldest first on disk) in the app's log directory, named `transcription_history.jsonl`, and expose them newest first.
- **FR-005**: Adding an entry MUST be a single-line append and MUST NOT rewrite the whole file.
- **FR-006**: Removing an entry or compacting MUST rewrite the file atomically (temporary file then replace) so a crash mid-write cannot corrupt the real file.
- **FR-007**: System MUST cap the number of entries at `history.max_entries` (default 1000), keeping the newest, and MUST trim an oversized file on load.
- **FR-008**: System MUST skip invalid lines on load without discarding valid ones.
- **FR-009**: System MUST import a legacy flat-JSON history exactly once when no JSONL file exists, then rename the legacy file to `<name>.json.bak`.
- **FR-010**: Clearing history MUST empty the file and delete the legacy `.bak` copy; the confirmation MUST state the count and that the action is irreversible.
- **FR-011**: The History screen MUST show a table with columns Time, Text, Model, Language, Duration; rows read-only, single-select, whole-row selection.
- **FR-012**: Time MUST be formatted as `HH:MM:SS DD.MM.YYYY`; Duration as seconds with one decimal and an `s` suffix; Model as its short registry alias, falling back to the raw identifier when unregistered.
- **FR-013**: The screen MUST show one of three states: the table, "Nothing dictated yet" (with the user's current start hotkey as a key cap) when there are no entries at all, or "No matching transcriptions" (with an "Esc to clear" cue) when a search matches nothing while entries exist.
- **FR-014**: The empty state's hotkey cap MUST reflect the user's configured start hotkey and update when it changes.
- **FR-015**: Search MUST be case-insensitive over the Text column only, debounced, and cleared immediately by Escape from anywhere in the view.
- **FR-016**: A count label MUST read "N entry/entries" when unfiltered, and "shown of N entries" when filtered, using correct plural forms per language.
- **FR-017**: Copy (button, Enter in the table, platform Copy key) MUST act on the current row, MUST be disabled when there is no copyable row, and the Copy key MUST NOT take over from a text field that has focus.
- **FR-018**: Double-clicking a row MUST open a modal detail dialog with metadata and full read-only text, Copy text and Close.
- **FR-019**: Export MUST write a human-readable text file (title header, then per entry: date, duration, model with language, text, separator), run off the UI thread, disable the Export button while running, and report success with count and path or failure with guidance.
- **FR-020**: Export of an empty history MUST be refused with a notice and no file dialog.
- **FR-021**: A newly stored entry MUST be inserted into a visible table without resetting scroll or selection, and the oldest row MUST be removed from the view when the cap is exceeded.
- **FR-022**: Column widths MUST be fitted to content (Time, Model, Language, Duration) with the Text column taking the remaining width and a minimum share of the table; widths MUST NOT be user-draggable and MUST NOT cause a horizontal scrollbar at large text scales.
- **FR-023**: The sidebar History page MUST be reachable and the window Find accelerator MUST focus its search field.
- **FR-024**: When `history.enabled` is false, System MUST NOT create or write the history file.
- **FR-025**: The user's dictation text MUST NOT be written to `app.log` by the history path (only the transient Logs-view preview is allowed elsewhere); History is the clearable store.

### Key Entities *(include if feature involves data)*

- **Transcription entry**: timestamp (epoch seconds), text, duration (seconds of audio), model (canonical identifier), language (code or `auto`). Derived: formatted date string, short text (50 characters, ellipsised).
- **History store**: ordered collection (newest first in memory, oldest first on disk) bounded by `max_entries`; backed by one JSONL file; may have a staging file during compaction and a legacy `.json.bak` after migration.
- **History view state**: search text, current row, export-busy flag, one of three display states.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A delivered dictation is visible at the top of History without reopening the window or restarting the app.
- **SC-002**: After clearing, no file in the app's data directories contains the previous dictations' text (history file empty, no `.bak`, no `.tmp`).
- **SC-003**: Restarting the app yields the same entries in the same order, up to `max_entries`.
- **SC-004**: With a history at its cap, a keystroke in the search field does not freeze the UI and a window resize does not re-measure the data per step.
- **SC-005**: Every control on the screen (search, Copy, Export, Clear history, table, detail dialog, Escape) is reachable and operable by keyboard.

## Assumptions

- A single process owns the history file (the app enforces a single instance).
- There is no UI for `history.enabled` or `history.max_entries`; both are edited in `config.yaml` and read at start-up, so a change takes effect on the next launch. An earlier `auto_cleanup_days` option was removed because nothing used it; there is no time-based deletion.
- There is no per-entry delete in the UI (`remove_entry` exists in the store but no control calls it).
- File transcriptions are not stored in History; only live dictations are. The screen's subtitle ("Every dictation and transcription") is wider than that behaviour.
- Entries are stored in clear text; protecting the file is the operating system's job.
- Language shown is the one set on the backend at the time of the dictation (or `auto`), not a detected language.

## Where it lives

- `app/history_manager.py` - `TranscriptionEntry`, `HistoryManager`: JSONL persistence, cap, compaction, legacy migration, clear, text export.
- `app/state_manager.py` - creates the manager from `history.enabled` / `history.max_entries` (file in the logs directory), adds the entry after delivery, calls the update callback.
- `app/config_manager.py` - `DEFAULT_CONFIG["history"]` (`enabled`, `max_entries`), `get_history_config`.
- `app/utils.py` - `get_project_logs_path` (directory of the history file).
- `app/gui/controllers/_history_mixin.py` - wires the view: load, clear confirmation, threaded export, copy, prepend on update.
- `app/gui/controllers/recording_controller.py` - forwards the pipeline's history callback as the `history_updated` Qt signal.
- `app/gui/views/history_view.py` - `HistoryTableModel`, `HistoryDetailDialog`, `HistoryView` (search, states, shortcuts, column fitting).
- `app/gui/main_window.py` - hosts the view, Find accelerator via `focus_search`.
- `app/gui/widgets/empty_state.py`, `page_header.py` - empty-state and header widgets.
- Tests: `tests/test_history_manager.py`, `tests/gui/test_history_view.py`, `tests/gui/test_app_controller.py` (history wiring, export, clear), `tests/test_state_manager_delivery.py`.
