# Parity: Logs (Qt `logs_view.py`, `log_bridge.py` vs `views/Logs.svelte`)

Reference: `app/gui/views/logs_view.py`, `app/gui/log_bridge.py`, spec 008.
Renderer: `views/Logs.svelte`, `components/logs/{model,store}.js`. Runtime:
`logs.list` and the `log` event (`_RingHandler` in `app/server/runtime.py`).

| Qt control, state or message | Electron |
| --- | --- |
| Title "Logs", subtitle "What the app is doing, in order. Useful when a model misbehaves." | `PageHeader`, same strings |
| Search field "Search logs…", debounced 200 ms, matches level, logger and message case-insensitively, trimmed, from the buffer | `SearchField`, same debounce and haystack (`visibleRecords`), tested |
| Checkbox "Show network logs" with its tooltip; hides `httpx`, `httpcore`, `urllib3`, `huggingface_hub`, `requests`, `asyncio` by top-level package | `Switch` with the same label and tooltip; same list |
| Button "Clear logs" (danger), confirmation "Clear logs?" / "Keep logs", empties the buffer and view only | `Button` plus `AlertDialog` with the same wording; empties the view only. The cut survives leaving the screen: it is a floor on record ids |
| Colour by level: DEBUG muted, INFO accent, WARNING warning, ERROR/CRITICAL danger | Level word in `text-ink-faint`, `text-accent-text`, `text-warning-text`, `text-danger-text` (status words use the AA text roles) |
| Rank of a line: message, level, module, timestamp; own `app.` loggers brighter than libraries | Same: time and library names faint, own loggers soft, message by the rule below |
| Lines addressed to the user (`user_message`) brighter than bookkeeping at INFO and below; a warning or error never recedes | Same rule (`messageClass`), plus a left border in the accent on user-facing lines so the distinction does not rest on colour alone |
| Wrap to width, no horizontal scroll | Wraps; newlines inside a message (tracebacks) are preserved |
| Empty state "No entries yet" with its hint | `EmptyState`, same strings |
| Buffer capped (1000 lines) | The runtime ring (2000) is the source; the view keeps up to 2000 |
| Per-keystroke work bounded (`setUpdatesEnabled`) | Keyed list; filtering recomputed once per debounce |
| Find accelerator focuses the search | The search field is reachable by keyboard; a global Find shortcut belongs to the shell and is not added here |
| (not in Qt) | **Added:** level filter (All, Info, Warnings, Errors) |
| (not in Qt) | **Added:** logger filter, built from the loggers seen, own loggers first |
| (not in Qt) | **Added:** "Messages for you" chip showing only user-facing lines |
| (not in Qt) | **Added:** Copy puts exactly the visible lines on the clipboard (`window.l2t.clipboard`) |
| (not in Qt) | **Added:** "Show log file" reveals the log file (`window.l2t.shell.showItemInFolder`), offered only where the bridge exists |
| (not in Qt) | **Added:** follow the newest line, paused by scrolling up and resumed by scrolling back or with the switch; "N of M lines" count |

## Runtime fix found on the way

The ring's formatter had no `%(asctime)s`, so `time` was always empty and the
screen could not show when a line happened. The record's own creation time is
used now (`app/server/runtime.py`, tested in `tests/server/test_log_ring.py`).

## Recorded, not fixed

- A record forwarded from the inference worker is re-emitted by the parent as a
  plain message, so a `user_message` or `sensitive` tag set in the worker is
  lost (spec 008, inconsistency 5). The Electron Logs screen therefore shows
  worker lines as bookkeeping. Fixing it means carrying the tags through the
  worker pipe, which touches `subprocess_backend.py` and is not trivial.
- `app.log` filtering of sensitive records is unchanged and out of this screen.
