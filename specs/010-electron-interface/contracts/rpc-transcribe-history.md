# Contract: files and history (Transcribe and History screens)

Transport and envelope: see `plan.md`. Format as `rpc-core.md`. Handlers:
`app/server/handlers/files.py`, `app/server/handlers/history.py`.

## Methods: files

| Method | Params | Result |
| --- | --- | --- |
| `files.formats` | none | `{extensions: [".wav", ...]}`: the list a drop may carry, lower case with the dot; one list shared with the Qt view (`app/audio_formats.py`) |
| `files.transcribe` | `{path, strict?}` | `{started: true, path, size}` at once; the work runs on a thread. `path` is a full path to an ordinary readable file (a relative path is `bad_path`; a folder, a pipe or a device is `not_found`) |
| `files.save_text` | `{path, text}` | `{saved: path}`; writes UTF-8 through a temporary file renamed into place, so a failure leaves the previous file |
| `files.results` | none | `{results: [Run]}`, newest first, the last 12 runs |
| `files.result` | `{path}` | `{result: Run \| null}` |
| `files.dismiss` | `{path}` | `{dismissed: bool}`: forget a run once the screen has shown it |

`Run` = `{path, status: "running"|"done"|"failed", started_at, finished_at?, elapsed,
text? (done), message? and code? (failed)}`. Every run is stored when it starts and
updated when it ends, whether or not a window is subscribed, so a result that
arrived during a reload or a reconnect is read back here instead of being lost.
A later run of the same path replaces the earlier one. The screen asks
`files.results` after it connects (and after a reconnect) and treats a `done` or
`failed` entry for the file it shows as the outcome.

### Paths that are written (`files.save_text`, `history.export`)

The path is meant to come from the save dialog, and is checked as if it had not.
A refusal is `bad_path` with `field: "path"` and a sentence in `message`:

- a full path (a relative one would land in the runtime's working directory, which
  is inside the installation when packaged), without control characters;
- a text extension: `.txt`, `.md`, `.markdown` or `.text` (case does not matter).
  A file without one, or with another (`.plist`, `.sh`), is refused. The save
  dialog's "All files" filter can still return such a name; the renderer shows the
  sentence and the user picks a text name;
- the folder exists; the target is not a link, a folder, a pipe or a device
  (an existing ordinary file is replaced);
- nothing inside the application's own places: the config folder (the files in it),
  the log folder, the models folder and the Hugging Face cache, at any depth, or
  the config or history file itself.

`write_failed` remains for the operating system's own failure; its message is the
OS reason without the path.

`strict: true` applies the extension guard of a drop; Browse and an OS open
name any existing file and a non-audio one ends in `file.failed`.

Errors of `files.transcribe` (the message is the Qt wording and is shown as written):

| Code | Message |
| --- | --- |
| `bad_extension` | That file type is not supported. (only with `strict`) |
| `bad_path` | not a full path, or control characters in it |
| `not_found` | That file is no longer there. (also: not an ordinary file, or not readable) |
| `no_stack` | the stack error, or "Recording stack isn't initialised ..." |
| `no_backend` | Backend unavailable. |
| `not_ready` | one of: "A model is still loading. Wait for it to finish." / "No speech model is installed yet. Open Models and download one." / "No model is loaded. Open Models and choose one." |
| `unsupported` | This backend doesn't support file transcription. |

`files.save_text`: `bad_params`, `bad_path`, `write_failed` (message is the OS reason).

The per-run preset is not a `files.*` method: the renderer reads the list
with `presets.get` and pins one with `presets.set_override {id}`
(`rpc-presets` contract). The pin lives in the state manager and is never
written to the config.

## Methods: history

| Method | Params | Result |
| --- | --- | --- |
| `history.list` | none | `{enabled, entries: [Entry], start_hotkey, max_entries}`, newest first. With no store: `enabled: false`, `entries: []` |
| `history.delete` | `{id}` | `{deleted: Entry, total}`. Removed from memory and from disk at once; the entry is returned so the caller can offer undo |
| `history.restore` | `{entry: Entry}` | `{restored: true, total}`. Writes the entry back at the place its timestamp belongs. `bad_params` (field `entry`) for an entry that could not be shown or found again: a timestamp that is not finite or is outside 1970-2100, empty or whitespace text, text over 200000 characters, a negative, non-finite or over-a-day duration, a model or language over 200 characters |
| `history.clear` | none | `{cleared: n}`. Empties the file and removes the legacy `.json.bak` |
| `history.export` | `{path}` | `{exported: n, path}`. Human-readable text, same format as Qt; the path rules of "Paths that are written" apply, and the file is replaced whole or not at all |

`Entry` = `{id, timestamp, text, duration, model, alias, language, datetime}`.
`id` is the timestamp: an identity that survives a new dictation landing
between a click and its request, which an index does not.

Errors: `history_disabled` (any write with no store), `not_found` (delete of
an entry that is gone), `not_restored` (already present, or the cap would
drop it), `empty` (export with nothing to export), `bad_path` (export
destination refused), `write_failed` (export destination), `bad_params`.

`history.list` leaves out an entry that cannot be shown instead of failing for the
whole list.

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `file.progress` | no | `{path, elapsed}`: when a run starts and then once a second while it runs |
| `file.done` | no (kept: `files.results`) | `{path, text, elapsed}`; `text` may be empty (heard nothing), which is a warning and not an error |
| `file.failed` | no (kept: `files.results`) | `{path, message, code, elapsed}`. `message` is a sentence for the person, never plumbing: no `Subprocess error:` or exception class, no runtime graph or build paths. `code` is `unreadable` (could not decode the file), `model_failed` (the model could not process the audio) or `failed` (anything else, the backend's text cleaned of paths); the Logs keep the full text |
| `history` | no | `{}`: emitted for a new dictation and now also after delete, restore and clear |

Every `file.*` event carries the path. A result whose path is not the file
the screen shows is dropped.
