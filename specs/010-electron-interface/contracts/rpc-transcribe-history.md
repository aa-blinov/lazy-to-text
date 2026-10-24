# Contract: files and history (Transcribe and History screens)

Transport and envelope: see `plan.md`. Format as `rpc-core.md`. Handlers:
`app/server/handlers/files.py`, `app/server/handlers/history.py`.

## Methods: files

| Method | Params | Result |
| --- | --- | --- |
| `files.formats` | none | `{extensions: [".wav", ...]}`: the list a drop may carry, lower case with the dot; one list shared with the Qt view (`app/audio_formats.py`) |
| `files.transcribe` | `{path, strict?}` | `{started: true, path, size}` at once; the work runs on a thread |
| `files.save_text` | `{path, text}` | `{saved: path}`; writes UTF-8 |

`strict: true` applies the extension guard of a drop; Browse and an OS open
name any existing file and a non-audio one ends in `file.failed`.

Errors of `files.transcribe` (the message is the Qt wording and is shown as written):

| Code | Message |
| --- | --- |
| `bad_extension` | That file type is not supported. (only with `strict`) |
| `not_found` | That file is no longer there. |
| `no_stack` | the stack error, or "Recording stack isn't initialised ..." |
| `no_backend` | Backend unavailable. |
| `not_ready` | Model isn't ready yet — wait for it to finish loading. |
| `unsupported` | This backend doesn't support file transcription. |

`files.save_text`: `bad_params`, `write_failed` (message is the OS reason).

The per-run preset is not a `files.*` method: the renderer reads the list
with `presets.get` and pins one with `presets.set_override {id}`
(`rpc-presets` contract). The pin lives in the state manager and is never
written to the config.

## Methods: history

| Method | Params | Result |
| --- | --- | --- |
| `history.list` | none | `{enabled, entries: [Entry], start_hotkey, max_entries}`, newest first. With no store: `enabled: false`, `entries: []` |
| `history.delete` | `{id}` | `{deleted: Entry, total}`. Removed from memory and from disk at once; the entry is returned so the caller can offer undo |
| `history.restore` | `{entry: Entry}` | `{restored: true, total}`. Writes the entry back at the place its timestamp belongs |
| `history.clear` | none | `{cleared: n}`. Empties the file and removes the legacy `.json.bak` |
| `history.export` | `{path}` | `{exported: n, path}`. Human-readable text, same format as Qt |

`Entry` = `{id, timestamp, text, duration, model, alias, language, datetime}`.
`id` is the timestamp: an identity that survives a new dictation landing
between a click and its request, which an index does not.

Errors: `history_disabled` (any write with no store), `not_found` (delete of
an entry that is gone), `not_restored` (already present, or the cap would
drop it), `empty` (export with nothing to export), `write_failed` (export
destination).

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `file.progress` | no | `{path, elapsed}`: when a run starts and then once a second while it runs |
| `file.done` | no | `{path, text, elapsed}`; `text` may be empty (heard nothing), which is a warning and not an error |
| `file.failed` | no | `{path, message}` |
| `history` | no | `{}`: emitted for a new dictation and now also after delete, restore and clear |

Every `file.*` event carries the path. A result whose path is not the file
the screen shows is dropped.
