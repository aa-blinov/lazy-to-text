# Implementation guide: building a screen of the Electron interface

Read first: `spec.md`, `plan.md`, `contracts/rpc-core.md`, the baseline
specs for your area (`specs/00x-*`), and `.specify/memory/constitution.md`.
The Qt code is the reference for behaviour; the baseline specs say what the
behaviour is and what was found inconsistent. Port the behaviour, not the
bugs, and write down each deliberate difference.

## What exists

- `app/server/`: `rpc.py` (`@method("area.name")`, `RpcError`, `need`), `events.py` (`bus.emit(name, data)`, sticky events), `runtime.py` (`Runtime`: `config`, `backend`, `state_manager`, `hotkey_listener`, `history`, `sampler`), `httpd.py`, `handlers/core.py`.
- `desktop/renderer/src/lib/`: `rpc.js` (`call`, `subscribe`), `backend.js` (stores: `snapshot`, `config`, `state`, `engine`, `resources`, `progress`, `level`; `patchConfig`, `refresh`), `i18n.js` (`$t('English source')`), `theme.js`.
- `desktop/renderer/src/views/*.svelte`: placeholders, one per screen, registered in `views/index.js`. `App.svelte` is the shell.
- `desktop/electron/`: main process; `preload.cjs` is the bridge (`window.l2t`: dialogs, shell, clipboard, window, overlay).
- `@monos/ui` docs: `desktop/node_modules/@monos/ui/docs/components.md`, `DESIGN.md`, `docs/tokens.md`. Use its components (`Button`, `Card`, `Modal`, `AlertDialog`, `Table`, `Tabs`, `Switch`, `Select`, `Toaster`/`toast`, ...) and its Tailwind names (`bg-surface`, `text-ink`, `border-line`, `rounded-ui`). Do not write a hex colour, `rgb()`, a pixel radius or a font family in the renderer.

## Rules

1. **Own your files.** Touch only the files of your slice. Shared files (`lib/backend.js`, `App.svelte`, `views/index.js`, `desktop/electron/*`, `app/server/runtime.py`) may be extended additively and minimally; re-read the file immediately before editing, because other people are editing in parallel. Do not run `git commit`, `git stash` or any command that changes the git state.
2. **Handlers.** `app/server/handlers/<area>.py`, one module per area, registered with `@method`. Never block the channel thread: start a thread for slow work and report by event. Persist with `rt.config.update_user_setting` and apply live exactly as `app/gui/controllers/app_controller.py` does. Extracting Qt-free logic out of `app/gui/*` into a Qt-free module is allowed when both interfaces need it, if the Qt module imports it back and all Qt tests stay green; never import PySide6 from `app/server`.
3. **Contract.** Write `specs/010-electron-interface/contracts/rpc-<area>.md` in the same format as `rpc-core.md`: every method, params, result, error codes, every event.
4. **Text.** English source strings through `$t('...')`. Russian: strings already in `app/i18n/app_ru.ts` are picked up automatically (run `uv run python scripts/export_translations.py` if the catalogue changed); strings new to this interface go in `desktop/renderer/src/i18n/ru.<area>.json` as `{"English": "Русский"}`. No emojis anywhere. Comments explain why, never what, and carry no measured figures.
5. **Convenience.** FR-013 asks for screens that are more convenient than the Qt ones: use judgement, keep every behaviour of the Qt screen, and add what makes it faster to use. State each addition in your parity file.
6. **Parity file.** `specs/010-electron-interface/parity-<area>.md`: a table of every control, state and message in the Qt screen(s) of your area (read the whole Qt view, not a summary) with the Electron equivalent or `omitted: reason`. Tick the matching tasks in `tasks.md`.
7. **Tests.** Runtime tests in `tests/server/test_<area>.py` (pytest; fake the runtime pieces; no test loads a model, opens a microphone, touches the network or the real home; the suite runs in a scratch HOME already). Renderer tests in `desktop/tests/<area>.test.js` (vitest + @testing-library/svelte; fake `lib/rpc.js`). The full Qt suite must still pass: `QT_QPA_PLATFORM=offscreen uv run --frozen python -m pytest tests/ -n auto -m "not timing" -q`.
8. **Verify in a browser and in Electron, not only in tests.**
   - Run the runtime on your own port from your own scratch directory so configs do not collide: `mkdir -p $SCRATCH/<you> && touch $SCRATCH/<you>/pyproject.toml && cd $SCRATCH/<you> && uv run --frozen --project <worktree> python -m app.server --no-single-instance --no-stdin-watch --token devtoken --port <PORT>` (run it in the background; it reads and writes `config.yaml` in that directory). To isolate config, logs and history without a `pyproject.toml` trick, pass `--data-dir <folder>` (or set `L2T_DATA_DIR`): `config.yaml`, `logs/app.log` and `logs/transcription_history.jsonl` live under it instead of the checkout. Models are not moved; set `storage.models_dir` in that `config.yaml`.
   - Run the renderer on your own port: from `desktop/`, `npx vite --config vite.config.js --port <VITEPORT>` (strictPort is on, so pick a free one), then open `http://127.0.0.1:<VITEPORT>/?port=<PORT>&token=devtoken` in the Browser pane tools (`mcp__Claude_Browser__*`) and look at every state of your screen in light and dark (`document.documentElement.dataset.mode`) and in Russian. Take screenshots and fix what looks wrong.
   - Electron: `L2T_DEV=1 L2T_SCREENSHOT=/path/out.png npx electron .` (needs a Vite dev server on 5173) saves a screenshot of the main window and quits.
   - Do not download a model. Model downloads, loads and transcriptions are tested with fakes. Do not leave processes running when you finish.
9. **Quality bar.** It must work against the real runtime, not only against fakes. Handle errors visibly (a Notice or a toast with the reason), empty states (EmptyState), loading states (Skeleton or Spinner), keyboard use and accessible names. Responsive down to the window minimum (900x600).

## Report

When finished, reply with: files written, methods and events added, what you verified and how, deliberate differences from the Qt screen, and anything you could not verify. Do not claim a behaviour you did not observe.
