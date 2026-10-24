# Parity: models and first run (spec 002)

Qt sources read in full: `app/gui/views/models_view.py`, `app/gui/widgets/model_card.py`, `inference_settings_panel.py`, `parakeet_inference_settings_panel.py`, `app/gui/views/first_run_view.py`, the model parts of `app/gui/controllers/app_controller.py` and `_storage_mixin.py`.
Electron: `desktop/renderer/src/views/Models.svelte`, `FirstRun.svelte`, `components/models/*`, `app/server/handlers/models.py`, `firstrun.py`.

## Models page

| Qt | Electron |
| --- | --- |
| Page header "Models" and its sentence | `PageHeader`, same strings |
| Search field, debounced 200 ms, placeholder "Search models by name, alias, language..." | `SearchField`, filters as you type (16 cards need no debounce); matches alias, canonical, display name, description, languages, family, in English and in the shown language. Ctrl/Cmd+F focuses it |
| Language filter: Any language, Russian, English, Multilingual (matches "multilingual" or "langs") | `Select`, same four values, same matching |
| Sort: Recommended order, Most accurate first, Smallest first | `Select`, same three plus **Fastest first** (added) |
| Family filter reached from the card's family chip (toggle, stays checked) | The chip on each card, same toggle; plus a **family Select** in the toolbar (added) so the filter is reachable without finding a card |
| Cards in one column | `Grid` that follows the width (one column at the window minimum, more when wide) |
| Card: family chip, display name, Recommended pill, Active pill | same; Active pill becomes "Loading N%" or "Loading bytes" while its weights arrive |
| Card subtitle: alias, canonical, Hugging Face link icon with a tooltip and an accessible name | alias, canonical, "Hugging Face" link (opens in the OS browser through the bridge), same accessible name |
| Metric line WER, RTF, size, VRAM with tooltips; unmeasured shown as a dash | same four with tooltips, dash for unmeasured; **languages** added to the line (translated) |
| Description clamped to three lines, Show more / Show less | same |
| Select / Download primary button by cache state | same |
| Delete button on a present, inactive, non-loading card; "Deleting..." while it runs | same; hidden otherwise; spinner while it runs |
| Delete confirmation naming the model and its size in GB, sibling aliases listed | `AlertDialog` naming the model and the **measured size on disk** (Qt printed the nominal catalogue size, which read 0.0 GB for small models), siblings listed |
| Delete failure dialog "Delete failed" with the error | danger toast with the error, kept on screen until dismissed |
| Card is one tab stop only while active | cards are plain regions; the buttons inside are the tab stops (the kit's `Card` is not made interactive, because nesting buttons inside an interactive card is forbidden by its docs) |
| Empty state "No models match your filters" + hint | `EmptyState`, same strings, plus a **Clear filters** button |
| Lock: every Select/Download/Delete disabled while the state is not idle, with no explanation | same disabling, plus a **Notice that says why** (recording, processing, or loading) and, while loading, a banner |
| Inline inference panel on the active card | `InferenceSettings` in the active card, same fields and limits (below) |
| Page lock, scroll into view on focus, smooth scroll | the page scrolls natively; focus scrolls into view natively |
| (none) | **Loading banner** (sticky): name, progress bar, bytes, elapsed seconds, **Cancel**. Cancel is reachable from the page, not only from the top bar |
| (none) | "Showing N of M models" line (live region), skeletons while the catalogue loads, an error Notice with Try again when it cannot be loaded |
| (none) | A **Storage and access** drawer on the page with the Storage and Hugging Face cards, so the folder and the token are reachable from where the weights are managed (the same components are meant for Settings) |

## Selection, cancel, load

| Qt | Electron |
| --- | --- |
| Select writes `whisper.model`, `whisper.compute_type`; marks the card active with a Loading pill at once; pushes the saved inference settings; requests the change on the next tick | `models.select` does the same in one call; the card goes active at once because the selected alias counts as active while its weights arrive |
| A second request during a load is refused with a log line, **after** the config was already written | refused with `busy` **before** anything is written |
| During recording the recording is cancelled first; during processing the switch is queued | unchanged (state manager) |
| Cancel in the top bar restores the card, the pill, `whisper.model` and `whisper.compute_type`; nothing rolled back when the load had already finished | `models.cancel_load` does the same; the status strip and the banner both call it |
| After a cancel the previous card says Active but the backend has nothing loaded, and selecting it again is a no-op | **the previous model is reloaded** after the cancel, once the abandoned load has unwound, unless the user chose something else meanwhile |
| After a failed download the card stays Active with no weights | the card returns to Download and a **toast** says the model did not start |
| Card pill: Loading with percent or bytes | same, from the `progress` event; the catalogue size stands in for a missing total, held under 100% |
| Top-bar "Loading: alias" with percent or elapsed seconds | the status strip (another slice) plus the banner on this page |
| Cache state recomputed on a worker thread; superseded results dropped | recomputed by the runtime on every transition to idle and after a delete or storage change, pushed as the `models` event; one result per event, so there is nothing to supersede |
| Engine pill | status strip (another slice) |

## Inference settings

| Qt | Electron |
| --- | --- |
| Whisper: Language (Auto-detect + 16 languages), VAD filter, Beam size 1-20, Temperature 0.0-1.0 step 0.1, Initial prompt | same fields; numbers are clamped on commit by the runtime and the field shows the stored value |
| Parakeet: "Include word + segment timestamps in output" and the hint | same |
| GigaAM, T-One, Vosk: none | none |
| Persisted under `model_overrides.<alias>`; pushed live only for the active alias; pre-fill does not write back | same; a partial update keeps the other fields |
| An unknown stored language shows Auto-detect | stored language outside the list shows Auto-detect (the select has no such option) |
| (none) | **A note** that the engine applies only the language today and stores the rest (true per spec 002 assumptions), and a line when Auto-detect resolves to a default language for the model (Whisper Base, Canary) |

## First run

| Qt | Electron |
| --- | --- |
| Screen replaces the shell; sidebar and top bar hidden; navigation shortcuts ignored | `App.svelte` shows `FirstRun` instead of the shell when `snapshot.first_run`; the sidebar, the strip and the shortcuts are off while it is up |
| Step 1: one recommended card with its pitch, Download on the card | same, with the real card in compact form; no competing button |
| "See all models instead" ends first-run for the session and opens Models | `firstrun.defer {reason: "catalogue"}`, then the Models page |
| Step 2: header "Downloading <name>", size; progress bar; "N% of ... MB" then elapsed; indeterminate with bytes when no total | same, through the shared `DownloadProgress`; real bytes, never a timer |
| Advance to step 3 only when the weights are on disk; otherwise "The download did not finish." and a hint pointing at a key on a card that is not on screen | same rule, decided by asking the runtime whether loading has ended and then checking the disk; the failure shows **Try again** and **Back** |
| (none) | **Cancel** on the download step (the top bar that held Cancel is hidden during first run) |
| Step 3: start and stop hotkeys as key caps, none for an unbound key, "to stop" between | `Kbd` caps from the configured bindings, same |
| Back button (never shown) | omitted: it was never visible in any step |
| "Set up later" on steps 1 and 2, hidden on 3; **no handler in Qt** | **implemented**: `firstrun.defer {reason: "later"}` ends first-run for this session and opens the shell; `onboarding.complete` stays unset so the screen returns on the next launch while no model is on disk (spec 002 FR-075) |
| "Start dictating" writes `onboarding.complete` once | `firstrun.complete`, once |
| A model on disk always suppresses the screen | same; the runtime checks the disk live, so a model downloaded this session counts |

## Storage and Hugging Face token (cards live in Settings in Qt)

| Qt | Electron |
| --- | --- |
| Path with "(default)", size ("computing..." until measured on a worker), Change..., Reset storage (disabled on default), Open folder | `StorageCard`, same; size arrives by event |
| Change...: folder picker; same folder is a no-op; Move / Leave / Cancel when the old root holds weights | native folder dialog (a typed path in a plain browser tab), `models.storage.plan`, then a Modal with Move / Leave / Cancel |
| Move runs on a worker; no progress | progress bar with bytes moved of total, polled from the destination |
| Further Change/Reset ignored while one runs | refused with `busy`; the buttons are disabled; also refused while a model is loading |
| Summary dialog after the change | Notice with the same facts; reasons for a skipped move are named |
| Token field masked, saved on focus loss, Clear token disabled while empty | password field with an explicit **Save token** and Clear token (disabled while none is saved). The stored value is **never sent back** to the renderer: the card says only whether one is saved |
| Token mirrored to `HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN`, never logged | same; the runtime logs only the redacted config line |

## Deliberate differences, in one list

1. The delete dialog shows the measured size on disk.
2. A refused switch writes nothing.
3. A cancelled switch reloads the previous model.
4. A failed download leaves no active card.
5. "Set up later" works, session-scoped.
6. The HF token is not returned to the renderer.
7. The family filter is also a toolbar control; sort by speed added.
8. Cancel is on the page and on the first-run download step.
9. The worker-process environment is not updated by a storage or token change (same as Qt; see the contract, Known limit).

## Not verified

Native folder dialog and OS file-manager opening (checked only through the bridge contract and a plain browser tab); Windows and Linux; a real download, load or cancel against a real backend (the runtime was driven with a fake backend that simulates progress and writes a fake weights file); the macOS cocoa-only layout differences do not apply here.
