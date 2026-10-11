# AGENTS.md — agent context for `lazy-to-text`

Local-first speech-to-text with a Qt UI. Cross-platform (Windows /
macOS), single ONNX inference path via [`onnx-asr`](https://github.com/istupakov/onnx-asr).
This file is your project quickstart — keep it skim-able.

## Run / build / test

```bash
uv sync                          # bootstrap venv from uv.lock
uv run lazy-to-text-ui           # launch the app in dev mode (CPU)
uv run lazy-to-text-ui-cuda      # launch with GPU auto-setup (Windows+NVIDIA)

# Portable bundle — wrapper picks the right tool per OS:
./scripts/build-macos.sh         # py2app alias .app, 5–10 s (Mac)
./scripts/build-macos.sh --release   # py2app full .app, 5–10 min (Mac)
.\scripts\build-windows.ps1        # PyInstaller folder bundle, CPU-only  -> dist/LazyToText/    (~400 MB)
.\scripts\build-windows-cuda.ps1   # PyInstaller folder bundle, GPU/CUDA  -> dist/LazyToText-CUDA/ (~3.0 GB)
.\scripts\build-windows.ps1 -OneFile  # PyInstaller single .exe, CPU-only (Win)
```

The full suite is **670 passed, 8 skipped** at last commit. Skipped
tests are mostly engine-specific paths that need a real model.

## Where things live

| Data | Dev (`uv run`) | macOS `.app` (frozen) | Windows portable (frozen) |
| --- | --- | --- | --- |
| `config.yaml` | `<project>/config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` + history | `<project>/logs/` | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights (HF hub) | `<project>/models/hub/` | `~/Library/Caches/LazyToText/models/hub/` | `%LOCALAPPDATA%\LazyToText\Cache\models\hub\` |
| Single-instance lock | filelock under cache | `~/Library/Caches/LazyToText/LazyToTextQt.lock` | named mutex |

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
and falls back to CPU on accelerator failure. It unwraps model
adapters (like GigaAM's `TextResultsAsrAdapter`) to find the
inner session. Some models (GigaAM / T-One) are pinned to CPU
via `prefer_cpu_provider=True` in `model_mapping.py` to avoid
known CoreML compilation crashes.

## macOS HUD / Fullscreen Overlay

The recording overlay (`app/gui/widgets/recording_overlay.py`) is
designed to stay visible over native full-screen applications.
Key technical choices:

- **Agent Mode:** `setup.py` sets `LSUIElement = True`. This
  background-app mode is required for windows to reliably pierce
  other applications' full-screen Spaces.
- **Window Level:** Uses `NSScreenSaverWindowLevel` to stay above
  full-screen shields, the Notch, and the Menu Bar.
- **Collection Behavior:** Uses `CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle | Stationary`. This ensures it's on every desktop, follows Cmd+Tab ignores, and doesn't slide during swipes.
- **Focus Policy:** We strictly avoid `raise_()` on background events
  (like finishing transcription) to prevent focus stealing. Toasts
  use `WA_ShowWithoutActivating`.

## UI Performance & Layout

- **FlowLayout:** Optimized to use uniform `spacing()` instead of
  calling `style().layoutSpacing()` thousands of times per frame
  during list resize events.
- **Batching:** `setUpdatesEnabled(False/True)` is used during
  multi-widget updates (like model selection) to prevent layout
  thrashing and scroll freezes.
- **Deferred Tasks:** Heavy UI/IPC handshakes (like model change)
  are deferred via `QTimer.singleShot(0)` to keep animations fluid.

## Hotkey defaults — and why they differ per OS

```python
# config_manager.py
if sys.platform == "darwin":
    _DEFAULT_START_HOTKEY = "ctrl+f2"
    _DEFAULT_STOP_HOTKEY  = "ctrl+f3"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f6"
else:
    _DEFAULT_START_HOTKEY = "ctrl+f2"
    _DEFAULT_STOP_HOTKEY  = "ctrl+f3"
    _DEFAULT_CANCEL_HOTKEY = "ctrl+f6"
```

macOS reserves `Ctrl+F1`..`Ctrl+F7` for system keyboard navigation
(focus → menu bar / Dock / window / toolbar / floating window /
next window / status menu). We use higher F-keys or safe ones like
F2/F3/F6 where possible to avoid conflicts.


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

## Cutting a release — where the version lives

The version is in **six** places. Five of them decide what the artifact
says, and nothing in the build fails when they disagree — a bundle whose
`CFBundleVersion` is one release behind ships. The sixth is documentation,
which fails by being quietly wrong in the next release instead.

| Place | What it drives |
| --- | --- |
| `pyproject.toml` `[project] version` | the wheel, and the canonical value every other place is compared to |
| `setup.py` `CFBundleVersion` | what Finder shows |
| `setup.py` `CFBundleShortVersionString` | what the macOS privacy pane shows |
| `setup.py` `version=` in `setup()` | the py2app bundle metadata |
| `app/version.py` `_FALLBACK` | what the UI reports when distribution metadata is unreadable |
| `README.md` notarization examples | illustrative only — update so the docs read as current |

Order matters, and it is not optional:

```bash
# 1. bump all six
# 2. commit
# 3. tag — tests/test_version.py requires the newest v* tag to match pyproject
git tag -a v0.1.5 -m "v0.1.5 — …"
# 4. re-sync the venv, or the new test fails and for the right reason
uv sync --frozen
# 5. build, verify, then push the tag
./scripts/build-macos.sh --release
```

**Step 4 is not housekeeping.** `tests/test_version.py::test_the_runtime_reports_the_version_the_tree_declares`
compares what the app would *print* against `pyproject.toml`, and after a bump it fails until the venv is
re-synced: `importlib.metadata` keeps answering from a `.venv/…/lazy_to_text-<old>.dist-info` left over
from the install before the bump. Every other test in that file compares strings in the repo and passes
happily while the UI shows the previous version. A version that lies is worse than none — the user quotes
it in a bug report and believes it.

**`--frozen`, not a bare `uv sync`.** A bare `uv sync` re-resolves and rewrites `uv.lock`, which is a
silent rebuild of the dependency set underneath a green run, and it fails on a missing lockfile only
when you did not pass the flag.

**macOS artifacts are a manual step.** `release.yml` builds Windows only
(`runs-on: windows-latest`, no `macos` anywhere in the file). The `.app` has to be built locally,
zipped with `ditto -c -k --keepParent`, and uploaded to the release:

```bash
ditto -c -k --keepParent "dist/Lazy to Text.app" "dist/Lazy-To-Text-<v>-macos-arm64.zip"
gh release upload v0.1.5 "dist/Lazy-To-Text-<v>-macos-arm64.zip"
```

Verify the archive after zipping, not just the bundle: `ditto` round-trips symlinks and the execute bit,
and a `.pyc` removed from under an existing signature turns the seal invalid without anything saying so.

**The download sizes in README.md and docs/index.html go stale every release, and nothing catches it.**
Both quote the byte count of the *attached file*, so they are only true for the release they were written
for. After v0.1.4 the README still claimed 159,349,810 B while the actual v0.1.5 asset is 155,353,854 B.
The one test that touches these figures,
`test_the_documented_download_size_agrees_across_surfaces`, only checks that the two surfaces agree
*with each other* — it cannot notice that both are equally wrong.

Read the sizes from the release itself rather than carrying the previous ones forward:

```bash
gh release view <tag> --json assets -q '.assets[] | "\(.name)\t\(.size)"'
du -sk "/Applications/Lazy to Text.app"   # installed, and it is not the archive size
```

Both surfaces must move together: the test requires the smaller of the two sets to be a subset of the
larger, so updating only the README makes it fail.

## Style / safety rails

- **Don't reach for emojis** — they don't render right in the dark
  QSS theme and the Logs view is monospaced. Same for source files.
- **Don't add new dependencies casually** — the project ships a
  curated set in `pyproject.toml`; any addition should justify itself
  against the package size and Apple Silicon wheel availability
  (some ML libs only ship x86_64 wheels).
