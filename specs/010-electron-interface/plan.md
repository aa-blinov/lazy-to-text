# Implementation Plan: Electron Interface on @monos/ui

**Branch**: `010-electron-interface` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

## Summary

A second front end over the existing domain stack. Python stays the
engine; Electron is a window, a tray and a capsule. A headless runtime
(`app/server`) assembles the stack without Qt and serves it over loopback
HTTP: `POST /rpc` for requests, `GET /events` (server-sent events) for
changes. The Electron main process launches the runtime, keeps it alive
and gives the connection to the renderer through a preload bridge. The
renderer is Svelte 4 on `@monos/ui`, built by Vite.

## Technical Context

**Languages**: Python 3.12+ (runtime), JavaScript (Electron main CommonJS, renderer ES modules + Svelte 4)
**Dependencies added**: none in Python (stdlib `http.server`). In `desktop/`: electron, electron-builder, vite, svelte 4, tailwindcss 3.4, `@monos/ui` (GitHub), lucide-svelte, vitest, jsdom. Each is a development dependency; the packaged app carries only Electron, the built renderer and the runtime.
**Storage**: the existing `config.yaml`, history file, model cache. No new store.
**Testing**: pytest for the runtime (`tests/server/`), vitest for the renderer (`desktop/tests/`), a scripted Electron smoke test (`L2T_SCREENSHOT`), CI builds per OS.
**Target platforms**: Windows 10/11, macOS (Apple Silicon and Intel), Linux (X11; Wayland as documented limitation).
**Constraints**: the runtime must not import PySide6; a second front end must not duplicate a rule (Constitution, Additional Constraints).

## Constitution Check

| Principle | Status |
| --- | --- |
| I. Local-first | Pass. The channel is bound to 127.0.0.1, protected by a per-launch token and a Host check; nothing is sent anywhere new. |
| II. Never lose words | Pass. Dictation, delivery and the LLM fallback run in the unchanged domain stack; the front end only displays outcomes. |
| III. Measured | Pass. Start-up cost (SC-005) is measured, not asserted. |
| IV. Platform honesty | Partial. Windows and Linux cannot be exercised on the development machine; Known Gaps lists what is verified only by CI. |
| V. Tests hold the artifact | Pass. New suites for the runtime and renderer; the Qt suite is untouched; the Electron build is asserted by tests that read the packaging config. |
| VI. Signed and verified | Pass, to do. The macOS Electron build carries the hardened-runtime entitlements for microphone use and the patched PortAudio is shipped inside the runtime; a test pins both. |
| VII. Small surface | Pass. No Python dependency added; `@monos/ui` is the stated design system. |
| VIII. Spec-driven | Pass. This directory. |

## Architecture

```
 Electron main (CJS)                Renderer (Svelte, Vite)
 ------------------                 -----------------------
 backend.cjs  spawns runtime        lib/rpc.js     call(), subscribe()
 windows.cjs  main, capsule, tray   lib/backend.js stores from events
 events.cjs   SSE client (tray,     lib/i18n.js    en / ru
              capsule rules)        views/*.svelte one per screen
 preload.cjs  window.l2t bridge     Overlay.svelte the capsule
        |                                  |
        | stdout: ready line               | POST /rpc, GET /events
        v                                  v
              Python runtime  (python -m app.server)
              rpc.py registry  events.py bus  httpd.py channel
              runtime.py -> ConfigManager, StateManager, backend,
                            HotkeyListener, HistoryManager
              handlers/*.py  one module per screen
```

Decisions:

- **HTTP + SSE, not a pipe or WebSocket.** Works unchanged from Electron and from a plain browser tab (development and debugging), needs no dependency, and a browser tab is the fastest way to look at a screen.
- **The runtime shares the Qt single-instance lock.** One engine owns the microphone and the hotkeys, whichever interface started it.
- **The capsule's visibility is decided in the main process** from `state` and `delivery` events, so it does not depend on a renderer being awake; the capsule renderer only draws.
- **Hotkeys, paste and sound stay in Python.** They already work on all three platforms; re-implementing them in Electron would create a second source of truth.
- **Translations are exported, not copied.** `scripts/export_translations.py` turns the Qt catalogue into `ru.json`.

## Project Structure

```
app/server/            runtime, channel, bus, registry
app/server/handlers/   core.py (shell), then one module per screen
desktop/electron/      main.cjs backend.cjs windows.cjs events.cjs preload.cjs
desktop/renderer/      index.html overlay.html popup.html src/
desktop/renderer/src/  lib/ views/ components/ i18n/
desktop/tests/         vitest
desktop/scripts/       dev.mjs
specs/010-electron-interface/contracts/   wire contracts, one file per area
```

## Wire contract

Requests: `POST /rpc` with `{"method": "area.name", "params": {}}`; the
response is `{"result": ...}` or `{"error": {"code", "message"}}`. Events:
`GET /events`, `event: <name>` + one JSON `data:` line. Both need
`Authorization: Bearer <token>` (or `?token=` for the event stream).
The per-area method lists are in `contracts/`:

- `contracts/rpc-core.md`: shell, recording, resources, logs
- `contracts/rpc-<area>.md`: added by each slice (files, history, models, firstrun, settings, presets)

## Delivery slices

1. **Foundation** (done): runtime, channel, bus, registry, shell, theme, i18n, rpc client, capsule and tray rules.
2. **Transcribe and History**
3. **Models and First run**
4. **Settings and permissions**
5. **Post-processing, Logs, Capsule, status strip**
6. **Packaging and CI** for all three platforms

## Known Gaps

Windows and Linux behaviour (tray, capsule transparency, hotkeys, installer)
is verified by CI builds and unit tests only; each gap found is recorded
here with the date.
