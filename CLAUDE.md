# CLAUDE.md — agent context for `lazy-to-text`

Local-first speech-to-text with a Qt UI. Cross-platform (Windows /
macOS), single ONNX inference path via [`onnx-asr`](https://github.com/istupakov/onnx-asr).
This file is your project quickstart — keep it skim-able.

## Run / build / test

```bash
uv sync                          # bootstrap venv from uv.lock
uv run lazy-to-text-ui           # launch the app in dev mode

# Portable bundle — wrapper picks the right tool per OS:
./scripts/build-macos.sh         # py2app alias .app, 5–10 s (Mac)
./scripts/build-macos.sh --release   # py2app full .app, 5–10 min (Mac)
.\scripts\build-windows.ps1      # PyInstaller folder bundle (Win)
.\scripts\build-windows.ps1 -OneFile  # PyInstaller single .exe (Win)

# Tests — always with offscreen Qt platform plugin so Cocoa /
# WinAPI never opens a real window in CI
QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/
QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/gui/    # GUI subset (~25s)
QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/backends/test_subprocess_backend.py    # ~90s, real spawn
```

The full suite is **923 passed, 10 skipped** at last commit. Every
skip is a platform conditional or an opt-in, never a missing model:
`sys.platform != "win32"` (pywin32 mutex, winsound prewarm),
`!= "darwin"` (native hotkey monitor, bundle path resolution), and one
`skipif(True)` full-build recording stack. Measured, not assumed.

**No test loads a model.** The suite stubs onnx-asr throughout and the
repo ships no audio fixtures, so 923 green means the plumbing is right,
not that any model transcribes. Model claims get measured by hand
against the real `OnnxAsrBackend`, and the card in
`app/model_mapping.py` has to match that measurement.

### Measuring a model card

Numbers in a card come from the **Golos test split** (HF
`bonlime/golos-test`, 16 kHz mono, the official held-out split — none
of these models trained on it). 400 clips, 1312 s, split evenly between
`crowd` (near-mic) and `farfield` (distant). Two rules, both learned
the hard way:

- **Never score numeric utterances against spelled-out references.**
  Golos writes `четыре четыреста семь семьсот сорок пять` where every
  model here writes `4 407 745 9026`. Scoring that as 100% WER measures
  the corpus convention, not the recogniser — and for a dictation app
  whose output gets pasted into a document, digits are what you want.
  Numeric clips are counted separately.
- **Say what the sample size can support.** 1554 reference words puts
  the 95% confidence interval at roughly ±1.0–1.8 points, so a gap
  under ~2 points is noise. Vosk RU, FastConformer RU and Parakeet TDT
  are a tie; GigaAM v3 is genuinely behind them.

Domain caveat: Golos crowd/farfield is voice-assistant commands
("афина, воспроизведи музыку"), not free dictation. Real voices, real
rooms, real accents — but short. Treat it as the floor of what these
models handle, not the ceiling.

Speed numbers (RTF, load seconds) come from a `say`-synthesised clip
and are still valid — synthesised audio is fine for timing, and it is
only the accuracy claims that needed real speech.

CI runs the same suite on all three platforms, so the counts differ and
that is not a failure — what matters is that each is non-zero and the
`skipped` list matches the platform. Last green run:

| Leg | Result |
| --- | --- |
| macos-latest | 923 passed, 10 skipped |
| windows-latest | 925 passed, 8 skipped |
| ubuntu-latest | 919 passed, 14 skipped (under `xvfb-run`) |

The Linux leg needs two things the other two have already: a display for
pynput, which opens an X connection at import, and `libportaudio2`, which
`sounddevice` raises `OSError` over at import.

A leg reporting *fewer* tests than that has not lost a test — it has
failed at collection, which is what the collection-time import failures
above look like.

## Where things live

| Data | Dev (`uv run`) | macOS `.app` (frozen) | Windows portable (frozen) |
| --- | --- | --- | --- |
| `config.yaml` | `<project>/config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` + history | `<project>/logs/` | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights (HF hub) | `<project>/models/hub/` | `~/Library/Caches/LazyToText/models/hub/` | `%LOCALAPPDATA%\LazyToText\Cache\models\hub\` |
| Single-instance lock | filelock under cache | `~/Library/Caches/LazyToText/LazyToTextQt.lock` | named mutex |

`config.yaml` is **generated, not tracked** — the app rewrites it on
every start (migrating old keys, adding new ones), so a committed copy
guaranteed a dirty tree. The defaults live in `DEFAULT_CONFIG`
(`app/config_manager.py`) and the file is rebuilt from them on first
launch. Edit `DEFAULT_CONFIG`, not the YAML. Nothing in the build reads
the file: both frozen targets resolve their own per-user config dir.

`platformdirs.user_{config,log,cache}_dir("LazyToText", appauthor=False)`
is the single source of truth — `app/utils.py:_is_frozen()` and
`app/config_manager.py:_resolve_base_dir()` gate the frozen paths.
Two frozen targets right now: py2app's `.app` on macOS and
PyInstaller's folder bundle on Windows.

## Platform conditionals — what to grep for

- **`sys.platform == "win32"`** — `clipboard_manager`, `audio_feedback`,
  `instance_manager`, `hotkey_listener` (Win32-API replacements:
  `win32api`, `winsound`, named mutex). Each Win-specific import is
  guarded under the same conditional, so the modules import cleanly
  on macOS / Linux.
- **`sys.platform == "darwin"`** — Accessibility / Microphone permission
  banners (`app/gui/views/_accessibility_check.py`,
  `_microphone_check.py`), Dock / tray icon rendering
  (`app/gui/widgets/tray_icon.py`, `app/gui/app.py:_render_dock_icon_at`),
  bundle-mode backend swap (`app/gui/app.py:677`), CoreML provider
  selection (`app/backends/onnx_backend.py:412+`).
- **`getattr(sys, "frozen", False)`** — flips data paths to `~/Library/*`
  and selects the in-process `RegistryBackend` over the spawn-based
  `SubprocessBackend`.

## Backend topology

```
                    SubprocessBackend                RegistryBackend
                    ──────────────────                ─────────────────
                    spawn worker process              in-process
   used on:         Windows / dev macOS               macOS .app (frozen)
   IPC:             multiprocessing.Pipe              direct method calls
   why:             dodge Win32 DLL-loader-lock       py2app + spawn fight
                                                      (launcher binary
                                                      can't be re-execed)
```

Decision lives in `app/gui/app.py:677`:

```python
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    _early_backend = RegistryBackend(**_backend_kwargs)
else:
    _early_backend = SubprocessBackend(**_backend_kwargs)
```

When editing `subprocess_backend.py`, remember it now uses
`multiprocessing.get_context("spawn")` instead of the bare
`multiprocessing.Pipe()` / `Process()`. The fixture in
`tests/backends/test_subprocess_backend.py` patches `get_context`
to return a fake ctx — patching the bare module attributes alone
won't intercept the calls.

## CoreML / Apple Silicon

Provider tuple for ORT on Mac:

```python
("CoreMLExecutionProvider", {
    "ModelFormat": "MLProgram",
    "MLComputeUnits": "ALL",         # NE + GPU + CPU
    "RequireStaticInputShapes": "0",
    "EnableOnSubgraphs": "0",
}),
"CPUExecutionProvider",
```

`onnx_backend.py:_detect_active_provider` probes the live session
and falls back to CPU on accelerator failure (some GigaAM ops crash
ORT's CoreML path on init — we retry on CPU and surface the
provider in the engine pill).

## Hotkey defaults — and why they differ per OS

```python
# config_manager.py
if sys.platform == "darwin":
    _DEFAULT_START_HOTKEY = "ctrl+f8"
    _DEFAULT_STOP_HOTKEY  = "ctrl+f9"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f10"
else:
    _DEFAULT_START_HOTKEY = "ctrl+f2"
    _DEFAULT_STOP_HOTKEY  = "ctrl+f3"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f6"
```

macOS reserves `Ctrl+F1`..`Ctrl+F7` for system keyboard navigation
(focus → menu bar / Dock / window / toolbar / floating window /
next window / status menu). pynput never sees the events — the OS
captures them first.

## macOS App menu (Cmd+, / Cmd+Q / About)

`app/gui/main_window.py:_install_app_menu` builds a single
`QMenuBar` with three `QAction`s:

| MenuRole | Text | Shortcut | Handler |
| --- | --- | --- | --- |
| `AboutRole` | About Lazy to Text | — | `_show_about_dialog` |
| `PreferencesRole` | Settings… | `Ctrl+,` (→ `Cmd+,`) | `_open_settings_view` |
| `QuitRole` | Quit Lazy to Text | `Ctrl+Q` (→ `Cmd+Q`) | `_quit_application` |

Qt's Cocoa platform plugin promotes these into the global App menu
(under the Apple logo) regardless of which submenu they're attached
to — the host menu's title is irrelevant on Mac. On Windows / Linux
the same actions appear in a regular `Lazy to Text` top menu.
`Ctrl+,` / `Ctrl+Q` → `Cmd+,` / `Cmd+Q` translation comes from Qt's
portable `QKeySequence` layer.

Quit goes through `request_quit()` (flips `_quitting=True` so
close-to-tray override doesn't kick in) **and** `QApplication.quit()`
(drops the event loop — `setQuitOnLastWindowClosed(False)` is set
when the tray is alive).

## Permissions UX (macOS)

Two TCC-gated capabilities are checked at startup:

- **Accessibility** (`AXIsProcessTrusted`) — for `pynput` global
  hotkeys + `pyautogui` autopaste keystrokes. macOS won't prompt;
  Settings shows a two-state banner that opens *Privacy & Security
  → Accessibility* and a separate "granted but needs restart" banner
  with an in-app relaunch button.
- **Microphone** (`AVCaptureDevice.authorizationStatus`) — system
  prompt fires automatically via `requestAccessForMediaType_` the
  first time we call it. The Settings banner shows authorized /
  denied / not_determined states, with *Open Microphone Settings*
  for the denied case.

Both checks are no-ops on non-macOS (early-return on `sys.platform
!= "darwin"`).

## Dialogs — `app/gui/widgets/dialogs.py`

Three helpers, all stamped with the live `QApplication.windowIcon()`
to replace QMessageBox's macOS template glyph (system "?"):

- `confirm(parent, title, text, *, default_yes, yes_label, cancel_label)`
- `confirm_three_way(parent, title, text, *, yes_label, no_label, cancel_label)`
- `notify(parent, title, text, *, kind, informative, rich_text)` —
  `informative` is the QMessageBox secondary body (lighter weight);
  `rich_text=True` enables HTML and clickable `<a href="…">`.

`tests/gui/conftest.py:stub_modal_dialogs` autouse-mocks all three
at every callsite so headless tests don't hang on `exec()`. When
adding a new dialog, route through these helpers — direct
`QMessageBox.question/.information` will (a) show the system glyph
on Mac instead of the app icon and (b) bypass the test mock.

## Tests — naming conventions

- `tests/gui/` — Qt widget logic, run with `QT_QPA_PLATFORM=offscreen`
- `tests/backends/` — backend dispatch + worker process tests
- `tests/services/` — pure-Python services (audio recorder, clipboard)
- `tests/utils/` — `app/utils.py` helpers

Always pass `-x` during dev so the first failure surfaces fast;
GUI failures often cascade through the autouse fixtures.

## Style / safety rails

- **Don't reach for emojis** — they don't render right in the dark
  QSS theme and the Logs view is monospaced. Same for source files.
- **Don't add new dependencies casually** — the project ships a
  curated set in `pyproject.toml`; any addition should justify itself
  against the package size and Apple Silicon wheel availability
  (some ML libs only ship x86_64 wheels).
- **Preserve `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
  in commit footers** — matches existing branch style.
