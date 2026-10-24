# Parity: Post-processing (Qt `presets_view.py` vs `views/PostProcessing.svelte`)

Reference: `app/gui/views/presets_view.py`, `app/gui/controllers/app_controller.py`
(`_on_llm_changed`, `_refresh_presets_ui`, `_on_preset_changed`,
`_sync_flat_keys_to_active`, `_on_preset_activated`, `_ensure_first_preset`,
`_on_preset_key_reset`, `_on_preset_create/duplicate/delete_requested`,
`_on_preset_override_changed`), spec 005. Renderer:
`views/PostProcessing.svelte`, `components/presets/*`. Handlers:
`app/server/handlers/presets.py`.

| Qt control, state or message | Electron |
| --- | --- |
| Title "Post-processing", subtitle "Rewrite dictated text before it is pasted." | `PageHeader`, same strings |
| Card "Language model" with the intro line (cloud model receives your words) | Same card and string (the italic word is kept) |
| Switch "Rewrite dictated text before it is pasted", inside the card, global, never part of a preset | `Switch` inside the same card; sends `llm.set_enabled` alone, which writes `llm.enabled` and nothing else |
| Shared note (numbers as digits, language unchanged) | Same, under the switch |
| Name (placeholder "Work, Letters, Quick notes"), commits on focus-out; empty falls back to the id | `TextField`, commits on change; the runtime applies the fallback |
| Provider picker (12 providers, unknown id lands on Custom) | `Select`; options from `presets.catalogue`; unknown provider shown as Custom (`providerValue`) |
| Provider change rewrites the address only when it is empty or a known default; Custom never rewrites | Same rule (`withProvider`), tested |
| Server field; privacy line follows the address per keystroke, save waits for focus-out | `TextField`; `presets.privacy` is asked 120 ms after the last keystroke, save on change |
| Model (placeholder "qwen3:8b, or gpt-5.4-mini") | Same |
| API key as a password field with a Clear button (disabled when empty); Clear writes at once and clears that preset's key, not the active one's | `TextField type=password` and `Button` "Clear" (disabled when empty) calling `presets.reset_key` |
| "What it does" picker (three modes) | `Select`; the mode's own description is shown under it (addition: Qt had it only as data) |
| Reasoning effort picker (Provider default, Off (fastest), Minimal, Low, Medium, High) | Same labels |
| Max tokens spin, 0 shown as "Provider default", range 0..32768, step 64 | Number field, empty means 0 with the placeholder "Provider default"; runtime clamps |
| Timeout spin, 1..600 s | Number field with "seconds" hint; runtime clamps |
| Own wording text area with placeholder "Leave empty to use the mode's own wording." and the hint that the two house rules stay | Same strings |
| Privacy line: "Runs on this machine ..." or "Runs on a remote server ..." | `Notice` (info for local, warning for remote), same strings |
| Card "Preset": combo "Choose", button "Use this one by default" turning into disabled "In use by default" with a tooltip | Card `PresetPicker`, always visible; same labels and states; the tooltip is the `title` of the disabled button |
| New preset (copy of the first, "<name> copy", opens on it) | Same; the new preset is opened |
| Duplicate (copy including its key) | Same, plus a toast "Preset duplicated" |
| Delete (disabled with a tooltip when there is only one preset); no confirmation | Same disabled rule; **a confirmation dialog is added** (FR-008: destructive actions ask first). The preset's key goes with it, and the dialog says so |
| Empty state "No presets left ..." when the editor has no preset | Shown inside the card when the list is empty (the runtime always materialises one, so it is reachable only from a hand-edited file) |
| Editor does not emit while populating | The draft is local; nothing is sent until a field changes or loses focus |
| Edit commits the whole preset, not a field | `presets.update` carries the whole editor payload |
| A first preset is materialised at launch | `presets.get` does it on first read, idempotently |
| Flat keys mirrored on edit, activate, delete, key reset (when active) | Same, in the handler |
| Transcribe-screen per-run pin (`_on_preset_override_changed`) | `presets.set_override` / `override_id` in the state; the Transcribe screen owns its picker |
| (not in Qt) | **Added:** layout order puts the picker above the settings so it is clear which preset the card edits; it is always visible and nothing on the screen folds it away |
| (not in Qt) | **Added:** "Test connection" runs a small request with the editor's current values and shows the result or the failure reason; it sends a fixed sentence, never the user's words, and logs nothing |
| (not in Qt) | **Added:** the screen flushes an edit that was typed but not yet committed when it is left; the list refreshes on the `presets` event |

## Differences from Qt, deliberate

- Deleting a preset asks first.
- `presets.delete` and `presets.reset_key` read the active id before writing.
  The Qt controller reads it from the live section after writing the list, where a
  deleted active id no longer resolves, so the stale `active_profile` was left in
  the file (harmless, because resolution falls back, but untidy).

## Not verified

- A request against a real cloud endpoint: only the refused-connection case was
  exercised against the real runtime; success and HTTP-error replies are covered
  with `complete` replaced.
