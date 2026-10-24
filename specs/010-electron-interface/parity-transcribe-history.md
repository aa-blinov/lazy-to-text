# Parity: Transcribe and History (Qt screens vs the Electron screens)

Reference: `app/gui/views/transcribe_view.py`, `history_view.py`,
`controllers/_transcribe_mixin.py`, `_history_mixin.py`, and the file-related
parts of `recording_controller.py` and `app_controller.py`. Renderer:
`views/Transcribe.svelte`, `views/History.svelte`, `lib/transcribe.js`,
`lib/history.js`, `components/transcribe/DropOverlay.svelte`.

## Transcribe

| Qt control, state or message | Electron |
| --- | --- |
| Title "Transcribe", subtitle "Turn an audio or video file into text you can edit." | `PageHeader`, same strings |
| Browse… (primary while empty, secondary once there is text; disabled while busy) | `Button` in the header, same rule |
| Invitation page: dashed zone, "Drop an audio or video file here", example formats MP3, WAV, M4A, MP4, MKV, full list as tooltip | Same; the whole zone is also a button that opens Browse (addition) |
| File identity page: name line and detail line, zone keeps dashed border | Same, with a file icon and a spinner while busy |
| Drop highlight while an accepted drag is over the zone | Zone highlight plus a window-wide overlay (drop anywhere, addition) |
| Drag accepted only if it carries a local file with a supported extension; refused while busy | Refused while busy. Extension is checked on drop (a browser cannot read file names during a drag), and an unsupported drop shows "That file type is not supported." instead of a silent no-drop cursor. Deliberate difference |
| Only the first supported local file of a drop is used | Same (`pickDropped`) |
| Browse dialog "Choose an audio or video file", filter "Audio / video" plus "All files" | `window.l2t.dialog.openFile`, same title and filters; extensions come from `files.formats` (one list shared with Qt through `app/audio_formats.py`) |
| Busy: file name, "Transcribing…" with size, status "Working. The window stays usable.", transcript read-only and empty, Browse disabled | Same. The detail line also shows live elapsed time from `file.progress` (addition) |
| Done: detail line size, processing time, word count, "Edited" separated by a middle dot | Same; word count pluralised for English and Russian from the shared catalogue |
| Processing time kept growing with every edit (measured against the clock each time) | Frozen when the result lands. Deliberate difference: it is a fact about the run |
| Word count and "Edited" follow typing; "Edited" disappears when the text equals the model output | Same (`describeFile`, baseline kept in the store) |
| Copy / Save .txt hidden, not disabled, while there is no text | Same |
| Copy copies the text on screen; "Copied to clipboard." fades after a few seconds | Same, 4 s, on the status line |
| Save: suggested `<stem>.txt` in the source folder or `transcript.txt`; filters Text and All files; UTF-8; "Saved: <path>" / "Save failed: <reason>" (sticky) | `dialog.saveFile` then `files.save_text`; same messages |
| Status line kinds busy, done, warning, error with distinct colours; errors and warnings sticky; courtesy note transient; dismissing clears the kind | `Notice` with tone info/success/warning/danger; dismiss button on every status |
| Error: file name kept, detail "Failed", status "Error: <message>" | Same |
| "That file is no longer there." for an OS open of a missing file, previous identity kept | Same (`not_found` handling keeps the previous path) |
| Empty result: the Qt controller turns it into the failure "The model heard no speech in this file."; the view's own warning path (detail "No speech recognised in that file.", sticky warning suggesting another model) is never reached | The warning path is reached: `file.done` with empty text shows it. Deliberate difference, more helpful than an error and the same distinct outcome (FR-021) |
| Transcript empty state "No transcript yet" with hint, no hotkey | Same `EmptyState` |
| Transcript editable after a result, read-only while busy and on error | A textarea exists only with text; busy and error show the empty state, so it is never editable then |
| Not ready / no backend / unsupported / no stack messages | Raised by `files.transcribe` with the same wording, shown on the status line |
| Stale result filtered by path | `file.*` events carry the path; mismatches are dropped |
| File runs not written to History, no delivery step | Same (the handler never touches either) |
| Preset strip: "Preset for this file" checkbox and picker, visible with 2 or more presets, picker shows pinned else default, stale override falls back to default, choosing a row ticks the box, filling announces nothing | Same, over `presets.get` and `presets.set_override`; refreshed on the `presets` event so an edit on the post-processing screen shows here live |
| Override never written to config, held by the state manager | Same |
| Checkbox in an unstyled holder (macOS spacing bug) | Not applicable: the kit checkbox and layout are not Qt-styled |
| OS file open (Finder, Open With, launch argument): window forward, run starts | `window.l2t.onFileOpen` (forwarded by the main process) navigates to Transcribe, shows the window and starts a non-strict run |
| Launch argument filtering, `file://` decoding, Info.plist types | Main process, outside this slice |
| Language re-render | `$t` is a store; every string follows the language |

Additions (FR-013): drop anywhere on the window with an overlay, from any
screen; click the invitation to browse; live elapsed time while busy.

## History

| Qt control, state or message | Electron |
| --- | --- |
| Title "History", subtitle "Every dictation and transcription, newest first." | Same |
| Table columns Time, Text, Model, Language, Duration; newest first | Kit `Table`, same columns; time as `HH:MM:SS DD.MM.YYYY`, duration with one decimal and `s`, model as alias with the full id as tooltip |
| Whole-row single selection, column widths fitted to content | Omitted: no row selection model; each row carries its own Copy and Delete buttons and the text cell opens the details. The table lays itself out |
| Search "Search transcriptions…", debounced, Text column only, case-insensitive | Filters as you type (no debounce needed at this size), same scope |
| Escape clears the search from anywhere in the view | Same (window key handler while the view is open); Find accelerator focuses the search (Cmd/Ctrl+F) |
| Count "N entries" / "shown of N entries" with plural forms | Same |
| Three states: table, "Nothing dictated yet" with the start hotkey cap, "No matching transcriptions" with "Esc to clear" | Same, `EmptyState` with `Kbd` |
| Copy button (also Enter and the platform Copy key on the current row); disabled with no copyable row | Per-row Copy button, disabled for empty text. Enter and Copy-key shortcuts omitted with the row selection |
| Double-click a row opens "Transcription details" with Time, Model, Language, Duration chips, full read-only text, "Copy text", "Close" | Clicking the text opens the same modal; adds a Delete button |
| Tooltip with the full text on the Text cell and the full model id on the Model cell | `title` attributes |
| Export: save dialog, default `transcription_history.txt`, off the UI thread, button "Exporting…" while running, notices | `dialog.saveFile`, `history.export`, button loading state and "Exporting…", toasts "History exported" / "Export failed" |
| Export of an empty history: "Nothing to export" notice | Export and Clear are disabled while there are no entries; the runtime still refuses with `empty` |
| Clear history: confirmation with the count and "cannot be undone"; empties file and legacy backup | Native confirm (`dialog.confirm`), kit `AlertDialog` when not in Electron; `history.clear` |
| New dictation appears at the top without resetting scroll or selection | `history` event reloads the list; the keyed table keeps the rest of the DOM in place |
| `history.enabled` false: empty state, no working Clear or Export | Same, plus a notice saying history is turned off |
| Delete one entry (`remove_entry` existed, no control) | New: per-row Delete, applied at once, with an Undo toast |

### Undo, designed honestly

The entry is deleted from memory and from disk when the button is pressed,
because a delete that waits for an undo window is a delete a quit or a crash
silently drops, and the file holds the user's own words in clear text. The
runtime returns the deleted entry; the toast keeps it for 8 seconds and Undo
calls `history.restore`, a second write that puts the entry back at the place
its timestamp belongs. Restore is refused when the entry is already present
or the entry cap would drop it at once. Quitting during the window loses the
undo, never the deletion.

`HistoryManager` gained `remove_by_timestamp` and `restore_entry`, and a lock
around add, remove, restore and clear: the dictation pipeline adds entries on
its own thread while request threads delete, and an index taken before an
insert points at the wrong row after it. The Qt tests are unchanged and green.
