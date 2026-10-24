# Contract: models and first run

Transport and envelope: see `plan.md`. Handlers: `app/server/handlers/models.py` and `app/server/handlers/firstrun.py`. The reference for every side effect is `app/gui/controllers/app_controller.py` and `_storage_mixin.py`.

A **card** is one catalogue entry: `{alias, canonical, display_name, size_mb, vram_gb, speed, quality, languages, description, compute_type, family, onnx_family, recommended, pitch, url, wer, rtf, prefer_cpu, auto_language, shared_with[], inference{kind: "whisper"|"parakeet"|null, values?}}`. `wer` and `rtf` come from the one measurement table and are `null` for an unmeasured model. `display_name`, `description`, `pitch` and `languages` are English source strings; the renderer translates them with the Qt catalogue.

A **model state** is `{active, state, loading, cached{alias: bool}, deleting[], storage_busy, last_load, ready}`. `ready` is true when the backend has a model loaded; `active` follows the configuration and the disk, so a model that is on disk and configured but was never loaded reads `active` with `ready: false` and the card should offer Select (which then loads it, not `noop`). `last_load` is `{alias, outcome: "ready"|"error"|"cancelled", at}` (epoch seconds) for the last load that ended since the runtime started, else `null`: a window that was not listening when `model_load` went out reads the outcome here. `active` is the configured model while its weights are on disk or while it is the one being fetched, otherwise `null`; a failed download therefore leaves no card claiming to be loaded.

## Methods

| Method | Params | Result |
| --- | --- | --- |
| `models.list` | none | `{models: [card] in display order, languages: [{label, code}], ...model state}`. Display order is the recommended model first, then by ascending size |
| `models.state` | none | model state (a disk check per card) |
| `models.select` | `{alias}` | `{alias, noop, downloading, state}`. Writes `whisper.model` and `whisper.compute_type`, pushes the card's saved inference settings, asks the state manager to switch. Selecting the active, present, **loaded** model is `noop: true`; when it is active and present but not loaded (`ready: false`) the select loads it. `busy` while that model (or one sharing its repository) is being deleted, while the models folder is being changed, or while a load runs |
| `models.download` | `{alias}` | same as `select`; refuses a model that is already on disk with `already_cached` |
| `models.cancel_load` | none | `{cancelled, restored?, ...model state}`. `cancelled` is the truth: true only when a load or download was actually stopped. If the state manager has lost track of a load the backend is still running, the backend is asked directly. When a load was cancelled, `whisper.model` and `whisper.compute_type` return to the values from before the click (`""` when there was no model), and the previous model is reloaded in the background once the abandoned load thread has unwound. A cancel that finds nothing loading changes nothing (`cancelled: false`) |
| `models.delete_info` | `{alias}` | `{alias, cached, size_bytes, catalogue_mb, shared_with[], in_use}`. `size_bytes` is measured on disk without following links; it is what a delete frees |
| `models.delete` | `{alias}` | `{started: true}`; the outcome is the `model_delete` event |
| `models.inference.get` | `{alias}` | `{alias, kind, values}` |
| `models.inference.set` | `{alias, values}` | `{alias, kind, values, pushed}`. Only the fields sent change; numbers are clamped as the Qt value objects clamp them (beam 1-20, temperature 0-1). `language` `null`, `""` or `"auto"` is auto-detect, otherwise a code from `models.list.languages`. A value that would otherwise be silently replaced is refused with `bad_params` and `error.field`: an unknown language, a non-number or non-finite `beam_size` / `temperature`, a non-boolean `vad_filter` / `timestamps`, an `initial_prompt` that is not text (at most 2000 characters). `pushed` is true when the alias was active and the backend received it |
| `models.storage.get` | none | `{path, is_default, configured, exists, busy, size_bytes: null}`; the size follows as a `storage` event with `phase: "size"` |
| `models.storage.plan` | `{path}` | `{path, current, same, old_size, destination_has_models}`; what choosing the folder would do, so the renderer can ask Move, Leave or Cancel. `bad_path` (with `field: "path"`) for a non-folder, a folder that cannot be written, and **a folder inside, or a parent of, the current models folder** (links resolved) |
| `models.storage.apply` | `{path, move}` | `{started: true}`; progress and outcome are `storage` events. `move` relocates the `hub` folder first. The checks of `plan` run again here. The move never deletes the source before the copy has been compared with it file by file; a copy that does not match is removed and the source stays (`storage` `done` with `skipped: "copy_failed"`) |
| `models.storage.reset` | none | `{started: true}`; back to the built-in default, nothing moved |
| `models.storage.open` | none | `{opened}`; shows the folder in the platform file manager, creating it first |
| `models.hf_token.get` | none | `{set: bool}`; the value is never returned |
| `models.hf_token.set` | `{token}` | `{set}`; `bad_params` (field `token`) for a value with spaces, control characters (a NUL included), non-ASCII text or more than 512 characters, before anything is saved; stored in `huggingface.token` and mirrored to `HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN` in the runtime process |
| `models.hf_token.reset` | none | `{set: false}`; the environment variables are removed |
| `firstrun.status` | none | `{show, deferred, complete, candidate, hotkeys{start, stop}}`; `show` is true only with no model on disk, the flag unset and the screen not set aside this session. The disk is checked live |
| `firstrun.complete` | none | `{complete: true}`; the only writer of `onboarding.complete`, and only once |
| `firstrun.defer` | `{reason?: "later"\|"catalogue"}` | `{deferred: true}`; "Set up later" and "See all models instead". Ends first-run mode for this session; the flag stays unset so the screen returns on the next launch while no model is on disk. `app.snapshot` reports `first_run: false` afterwards |

Python callers outside the model handlers use `handlers.models.push_vad(rt, enabled)` (the Settings handler does) and `push_inference(rt, settings)`.

Errors: `unknown_model`, `no_stack`, `busy` (a model is already loading, a storage change is running, a delete is running; a select or a delete that conflicts with either), `already_cached`, `in_use` (the active model, or one sharing its repository, or a load in progress), `not_cached`, `no_settings`, `bad_path`, `open_failed`, `bad_params`, `internal`. A storage `error` event's `message` is a sentence, never an exception text.

## Events

| Event | Sticky | Payload |
| --- | --- | --- |
| `models` | no | a model state; sent after a select, a cancel, a delete, a storage change and whenever the app returns to idle (the transition Qt refreshes every card on) |
| `model_load` | no (last one kept: `models.state.last_load`, `app.last_events`) | `{alias, outcome: "ready"\|"error"\|"cancelled"}` when a load ends |
| `model_delete` | no (last one kept: `app.last_events`) | `{alias, deleted, error, freed_bytes, shared_with[]}` |
| `storage` | no | `{phase: "size", path, size_bytes}`, `{phase: "moving", done_bytes, total_bytes}`, `{phase: "done", changed, path, is_default, old_root, left_bytes, moved, moved_bytes, skipped, reason}`, `{phase: "error", message}`. `skipped` is `null`, `"destination_exists"`, `"copy_failed"`, `"in_use"` or `"other"` |

Loading progress and state are the core `progress` and `state` events; this area adds none for them. A renderer that needs a total before the backend reports one uses the card's `size_mb`.

## Known limit

The inference worker is a separate process that inherits the environment when it is spawned. A storage change and a token change are applied to the runtime process, as Qt applies them to its own, and are not forwarded to the worker. Whether a download started after a change lands in the new folder or uses the new token was not measured here.
