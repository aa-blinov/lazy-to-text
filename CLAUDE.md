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
QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/gui/    # GUI subset (~7 min)
QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/backends/test_subprocess_backend.py    # 25 tests, <2 s
```

**Both Windows wrappers — `build-windows.ps1` and `build-windows-cuda.ps1`
— build from `lazy_to_text.spec`.** The folder bundle is the default, and
`-OneFile` (on either script) sets `LAZYTOTEXT_ONEFILE=1` to
flip the spec's `EXE`/`COLLECT` shape instead of re-declaring the build
as CLI flags. They drifted apart once and the one-file exe shipped
without `onnx_asr`'s `.dist-info` (so it died at import) and with assets
at `_MEIPASS/assets` while `resolve_asset_path` reads
`_MEIPASS/app/assets`. The spec is the only place that says what ships;
keep it that way.

**Both CI workflows sync with `uv sync --frozen`** — `tests.yml` to test
the pins, `release.yml` so the published artifact *is* those pins. A
bare `uv sync` re-resolves and rewrites `uv.lock`, which is a silent
rebuild of the dependency set underneath a green run. `--frozen` also
fails on a missing lockfile instead of quietly inventing one.

The macOS bundle is **pruned after py2app and before codesign**, by
`scripts/prune_bundle.py` — release mode only, because an alias build
has no PySide6 of its own to trim. Do not try to slim it through
`setup.py`'s `_PACKAGES` instead: it has to name the bare `"PySide6"`
package, because naming submodules builds a bundle that dies at launch
on a missing `PySide6.QtCore/__init__.pyc`, and py2app copies the whole
Qt tree either way.

The prune runs on two lists, and both are checked against the app's
real imports by `tests/test_bundle_contents.py` so a change fails the
suite rather than the release. `KEEP_QT_FRAMEWORKS` is a **keep**-list
(new Qt modules must be added to it). `PRUNE_PYTHON_PACKAGES` is a
**cut**-list, and the polarity matters: adding a name there deletes it
from the bundle, so anything the app ever imports has to come off it
first. The two non-Qt entries ride on edges that stop short of
anything the app runs — `setuptools` is there for py2app itself, and
`pygments` arrives only through httpx's guarded `from ._main import
main`, which falls back to a stub rather than failing to import.

The full suite is **1154 passed, 10 skipped** on this machine — 1164
collected. Wall time is about 7 minutes, and `tests/gui/` is most of
it; both figures are from one machine and are only a hint on another.

Every skip is a platform conditional or an opt-in — never a missing
model. All ten, by count: six winsound-prewarm and three pywin32 tests
that only exist on Windows, and one opt-in in
`tests/gui/test_recording_factory.py` that is exercised end to end by
the launch smoke test.

The two bundle tests in `tests/test_bundle_contents.py` are the reason
the local count differs from every CI leg's. They look for a built
`dist/Lazy to Text.app`: they run here, where the bundle exists, and
skip on every CI runner — Windows included, since the bundle is built
by `release.yml`, not by `tests.yml` — because they measure an artifact
rather than the source. One more is macOS-only and needs a codesigning identity
(`test_a_certified_signature_anchors_and_ad_hoc_does_not`) — it skips
where no identity exists, which includes every CI runner. So local is
1154/10 and macOS *and* Windows are 1151/13; Linux adds four more of its
own platform conditionals on top. The totals have to match across legs,
or a leg has failed at collection. Measured, not assumed.

`load()` now also runs one short buffer through the model before
publishing `ready` (see "A model that binds is not a model that runs"
below), so a model whose execution provider binds at session-create and
then throws on the first `run()` fails here instead of turning every
dictation into "no speech detected". It costs one inference per load.

**No test loads a model.** The suite stubs onnx-asr throughout and the
repo ships no audio fixtures, so a green run means the plumbing is right,
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
`skipped` list matches the platform. The trigger is a push to `prod`, a
pull request, **or a `v*` tag** — the tag leg matters because
`release.yml` fires on that same push and a tag is neither a branch push
nor a PR, so without it the exact commit being published never ran the
suite. It is not a release gate (`release.yml` does not wait on this
workflow's status); it makes a red published commit discoverable. Last
green run, read out of the run logs rather than carried over from the
previous commit:

| Leg | Result |
| --- | --- |
| macos-latest | 1151 passed, 13 skipped |
| windows-latest | 1151 passed, 13 skipped |
| ubuntu-latest | 1147 passed, 17 skipped (under `xvfb-run`) |

1164 collected on every leg, and the totals have to add up to that: a
leg reporting fewer has failed at collection, not lost a test.

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
  bundle-mode backend selection (`app/gui/app.py:795`), CoreML provider
  selection (`app/backends/onnx_backend.py:412+`).
- **`getattr(sys, "frozen", False)`** — flips data paths to `~/Library/*`
  and, on macOS, turns on the bundle spawn environment
  (`_child_spawn_env()`) that the frozen `.app` needs.

## Backend topology

```
                    SubprocessBackend                RegistryBackend
                    ──────────────────                ─────────────────
   used on:         everywhere it starts              macOS .app fallback
   IPC:             multiprocessing.Pipe              direct method calls
   when:            worker acks within 10 s           worker never acked
```

Both frozen targets spawn a worker. The subprocess exists on Windows to
dodge the Win32 DLL-loader-lock, and on macOS because ONNX Runtime's
pybind11 bindings never release the GIL during session creation: an
in-process load starves every Python slot for ~0.3 s, measured at
341–369 ms against 4.6–10.5 ms for the spawned worker. A thread cannot
fix that and `sys.setswitchinterval` does not see it, so the load has
to leave the process.

The macOS `.app` case needs two things a plain spawn does not have, and
both were measured against a shipped release zip rather than reasoned
about:

- **`_child_spawn_env()`** (`app/backends/subprocess_backend.py`) —
  clears `sys.frozen` for the duration of `Process.start()`, or
  `multiprocessing` selects the frozen-executable protocol and hands
  the child `--multiprocessing-fork`, which CPython answers with
  "unknown option" and exit 2. It also clears `__main__.__file__`,
  otherwise the child `runpy`s the bundle's `__boot__.py` and re-runs
  the whole application ("Worker pipe closed before init").
  `PYTHONHOME`/`PYTHONPATH` are set only when `python312.zip` is really
  in the bundle — pointing an alias build at `Resources` breaks the
  child's stdlib.
- **`Contents/lib/libpython3.12.dylib`**, staged by
  `scripts/build-macos.sh`. The interpreter stub links
  `@executable_path/../lib/`, which py2app never creates; without it the
  child dies on its first instruction with `dyld: Library not loaded`.

Decision lives in `app/gui/app.py`:

```python
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    _early_backend = SubprocessBackend(**_backend_kwargs)
    if not _early_backend.wait_for_worker(_WORKER_START_TIMEOUT):
        # A laggy dictation app beats one that never transcribes.
        _early_backend = RegistryBackend(**_backend_kwargs)
else:
    _early_backend = SubprocessBackend(**_backend_kwargs)
```

`wait_for_worker()` returns True only when initialisation actually
survived. The reader thread sets the init event on EOF as well as on
the ack, so "the event fired" alone would read a dead worker as a live
backend and leave the app with no engine at all.

When editing `subprocess_backend.py`, remember it uses
`multiprocessing.get_context("spawn")` instead of the bare
`multiprocessing.Pipe()` / `Process()`. The fixture in
`tests/backends/test_subprocess_backend.py` patches `get_context`
to return a fake ctx — patching the bare module attributes alone
won't intercept the calls. That is also why the file runs in under a
second: there is no real spawn in it. The bundle-env tests force
`sys.platform` to `darwin` rather than inheriting the host's, so they
exercise the bundle branch on every CI leg instead of being vacuous on
the two that are not macOS.

### The pipe is correlated by sequence number

Commands go out as `("cmd", seq, op, *args)` and come back as
`("resp", seq, kind, payload)`; the reader routes each reply to the
waiter registered under its `seq`. The obvious version — one shared
`queue.Queue`, replies matched by arrival order — is wrong in a way that
does not announce itself: a command that *times out* leaves its eventual
reply on the queue, and the next command, a different one, for a
different caller, pops it and returns it as its own payload. A file that
overran the transcribe cap was enough to make `cancel_load` answer with
the previous transcript. A retired `seq` has nowhere to deliver, so the
reply is dropped instead.

Two consequences to preserve when editing this file:

- **`_send_lock` covers the pipe write only.** It used to wrap the
  blocking `get` as well, which locked every other caller out of
  *sending* for the duration — including the Qt thread's Cancel. Only
  the write needs serialising; a `Connection` is not safe against
  concurrent senders, but waiting for a reply is.
- **Worker death drains every waiter, not one.** `_fail_all_waiters`
  exists because a single sentinel unblocked one caller and left the
  rest to sit out their full timeout, then report "timed out" for a
  worker that had already died.

`shutdown_worker` is the one untagged command and gets no reply: the
parent joins the process instead of waiting for an ack.

## Why scipy is still a dependency

`onnx-asr` never imports scipy — the 84 MB in the bundle is
`pyproject.toml` alone. It is there for `scipy.signal.resample_poly`
at two call sites: `AudioRecorder._resample_to` (microphone) and
`onnx_backend._resample` (files). Both keep a `numpy.interp` fallback,
and the fallback's docstring once called itself "fine for
speech-band audio at common ratios (44100 → 16000 etc.)". That claim
is false, and it was load-bearing: it is what makes the 84 MB look
like dead weight.

Measured against the fallback on real Russian speech at 44.1 kHz —
spoken-Wikipedia recordings off Wikimedia Commons, 10 clips, 25
minutes, transcribed through the real `OnnxAsrBackend`:

- **0 of 10 clips transcribe identically.** Across 2486 words, 53
  change — 2.13% branch-vs-branch, from 0.32% on the cleanest clip to
  9.80% on the noisiest.
- **The cause is aliasing, and it is countable without a model.**
  Linear interpolation has no anti-alias filter, so the 8–22 kHz half
  of the spectrum folds onto 0–8 kHz. Its output carries **2.0× more
  energy in the 7–8 kHz band**, consistently across all ten clips
  (1.7×–3.2×).
- **Direction of the errors favours scipy.** Reading the divergences
  by hand, polyphase was right where linear was wrong in most of them
  (`нетберст` vs `нэдберст`, `декодиру` vs `декотируя`, `три икс` vs
  `три их`); the reverse case is rare.

Method matters here, because the obvious version of this measurement
is empty: a `say`-synthesised clip has so little energy above 8 kHz
that both branches look identical, and white noise has so much that
both look broken. Neither is speech. Use real recordings at a real
capture rate — `say` output is also 22.05 kHz, which skips the
`44.1/48 → 16` path entirely.

So the fallback is there for a broken install, not because it is
equal, and the docstring now says so. If this is ever revisited, the
question is not "does scipy matter" — it is what the 84 MB buys
against the ~2% of words, and whether that is worth it.

## A model that binds is not a model that runs

`load_model` returning means a session was *built*. An execution
provider can bind at session-create and throw on the first `run()` — this
module's own notes record Parakeet TDT v3 as unstable on CoreML at
exactly that point. Before the post-load probe such a model passed
`health_check()`, showed its accelerator in the Engine pill, and reported
"no speech detected" for every dictation: a permanently broken install
that read as a working one.

`_probe_inference` runs one second of silence through the model before
`ready` is published. A failed probe on an accelerator is treated as an
accelerator failure and reloads on CPU — the same ordering as the
session-create fallback, because CPU is the universal EP. Failing there
too means the model is genuinely unusable, and saying so beats waiting
for the user's first dictation to find out.

The probe is why a handful of `tests/backends/test_onnx_asr_backend.py`
tests reset their `recognize` counter after `load()`: they are about how
`transcribe` splits its input, and the probe is a separate, earlier call.

Two things in the same file that look like the obvious version:

- **`None` no longer means both "heard nothing" and "failed".**
  `TranscriptionError` (in `app/backends/base.py`) separates them. It
  used to be flattened into `None`, and the UI rendered every failure as
  *"no speech detected"* or *"the file may be corrupt"* — a diagnosis
  about the user's audio, made by the code that knows it never got as far
  as listening to it.
- **`transcribe_file` chunks too.** It used to hand a whole decoded
  recording to one call while `transcribe` capped at `_CHUNK_SAMPLES`,
  and onnx-asr does no windowing of its own.

## Signing — why TCC grants survive rebuilds

macOS keys every Accessibility / Microphone grant to the app's
**designated requirement**, not to its path. What that requirement
anchors on is the whole difference, and both halves were measured on
this machine:

| Signature | Designated requirement | Rebuilds |
| --- | --- | --- |
| ad-hoc | `cdhash H"24517fd…"` | new every build → TCC sees a new app, both permissions are orphaned |
| self-signed cert | `certificate root = H"b6327a25…"` | constant — verified identical across three different payloads |

So `codesign` exiting 0 is not enough to know a bundle is safe to ship.
`build-macos.sh` therefore reads the requirement back and refuses the
build if an identity was chosen but the result is a cdhash — the
identity is overridable from the environment (`L2T_SIGN_IDENTITY`), and
a release shipped ad-hoc from a machine that already had a usable
identity precisely because the exit status was the only check.

**`codesign` exiting 0 says nothing about which signature it wrote.**
The requirement is what says it.

`scripts/setup-signing.sh` creates the self-signed identity and puts it
at `~/Library/Application Support/LazyToText/` scope for development and
for distributing to people who already know what they are getting.
Distributing to the general public wants a real Apple Developer ID plus
notarisation: a self-signed certificate is not verifiable by Gatekeeper
on a machine that does not trust it, so first launch there needs the
right-click → Open exemption.

Two traps in that script, both of which kept it looking healthy:

- **Do not derive the keychain password.** It passed
  `-k "$(security show-keychain-info … | sed -n 's/.*password: //p')"`.
  That command prints `Keychain "…" no-timeout` — the substring
  `password:` is not in the output — so the substitution produced an
  empty string, `-k ""` failed, and a `|| { … }` arm printed "skipped"
  and carried on. Omit `-k` and let macOS prompt instead; it keeps the
  password out of shell history too.
- **Being listed is not being usable.** `security find-identity`
  reports what the keychain holds; `codesign` additionally needs the
  private key's access-control list to grant it, which
  `set-key-partition-list -S apple-tool:,apple:,codesign: -s -l "$CN"`
  arranges. Without it, `codesign` raises a blocking keychain dialog
  with no timeout of its own — measured at 19 s to sign a one-byte file,
  and seconds again per invocation. The script now *probes* rather than
  assuming, so an installed-but-unusable identity is repaired instead of
  reported as "already installed" and skipped.

`set-key-partition-list` only works from an interactive session —
`launchctl managername` must report `Aqua`. Run `setup-signing.sh` from
a Terminal, not from a background shell.

Switching an existing install from ad-hoc to a certificate is a one-time
event: the old grants are keyed to a cdhash that will never come back,
so they have to be cleared once, by hand, and the user grants again.

```bash
tccutil reset Accessibility ai.eora.lazytotext
tccutil reset Microphone     ai.eora.lazytotext
```

No `sudo` is needed on current macOS; both were run unprivileged here.
After that one reset, later reinstalls keep the grants.

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
  hotkeys + the `Cmd+V` autopaste keystrokes. macOS won't prompt.
  Two gates are probed separately in `app/macos_permissions.py`
  (listening to key events vs posting synthetic ones) because they are
  not the same TCC grant; `is_post_event_access_trusted` reads both,
  since the app has two paste paths and either gate being open is
  enough. The Settings banner has exactly **two** states — `hidden`
  and `untrusted`, the latter opening *Privacy & Security →
  Accessibility*. There is no "granted but needs restart" banner and
  no relaunch button: the grant is picked up live, because
  `mac_permissions_changed` stops and re-starts the hotkey listener,
  which rebuilds `MacHotkeyMonitor` against the new state.
  `_on_restart_requested` exists and works but is wired to nothing —
  see its docstring before assuming a restart is ever required.
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
- `tests/utils/` — `app/utils.py` helpers
- `tests/test_*.py` (top level) — everything non-Qt: audio recorder, clipboard
  manager, hotkey listener, config manager, history manager, model mapping

There is no `tests/services/` directory. Service tests are top-level files
named after the module they cover, so look for `tests/test_clipboard_manager.py`
rather than `tests/services/test_clipboard.py`.

Always pass `-x` during dev so the first failure surfaces fast;
GUI failures often cascade through the autouse fixtures.

## Transcribe view — the three contracts

`app/gui/views/transcribe_view.py`. Everything here was a bug or a
hollow test at some point; the shapes exist because the obvious
version of each is wrong.

**The drop zone has two pages.** `_source_stack` holds an invitation
and a file identity behind the same dashed `QFrame`, so the drag
surface never disappears — only the 120px of prompt does. Loaded, the
zone calls `setMinimumHeight(0)` and caps itself at its own sizeHint.
A fixed minimum here is what kept it from ever yielding the screen.

**The transcript is editable, and `_baseline` is what makes that
honest.** It holds the model's own return, so `Edited` in the identity
line is a fact rather than a guess, and Copy copies what is on screen.
Anything that changes the text without updating `_baseline` turns
`Edited` into a lie.

**The status label needs the unpolish/polish pair.**

```python
label.setProperty("status", kind)
label.style().unpolish(label)
label.style().polish(label)
```

`setProperty` alone does not restyle anything. Four `TranscribeStatus`
rules sat in the QSS for a while and never fired once, so busy, done,
warning and error all painted the base grey and an error read as a
caption. Corollary for tests: `palette()` will not see it either —
sample the rendered pixels (`label.grab().toImage()`), which is the
only honest witness. A test that used the palette passed against a
build with the fix removed.

## Delivery confirmation — the race that ate it every time

Dictation used to end in silence: the overlay hid on `idle`, the text
landed in whatever window had focus, and "did it go in?" had no answer
anywhere. Three things had to line up, and the first one kept undoing
the other two.

**`idle` is not allowed to hide a live confirmation.**
`RecordingOverlay.show_delivery()` is called from the transcription
pipeline thread, and the state machine reaches `idle` milliseconds later
as that same pipeline finishes. An unconditional hide on `idle` won that
race every single time, so the confirmation was never seen. `set_state`
returns early when a delivery is active, and a new `recording` state
stops the expiry timer so a stale timeout cannot blank the live state
later.

**The answer has three values, not two.** A failed copy leaves the text
nowhere; a failed keystroke leaves it on the clipboard waiting for the
user, and the dictation still belongs in History.
`ClipboardManager.deliver_transcription` returns
`pasted` / `copied` / `failed` for exactly that reason;
`execute_auto_paste` keeps its bool contract so its own tests are
untouched, and the distinction lives in `copied_before_paste`. Its
`use_auto_enter` branch used to fall off the end and return `None` — a
fourth value nothing could render.

**The overlay never claims "Pasted".** `_send_paste_combo` reports only
that keystrokes went out; no platform API confirms the target app
pasted, and the rest of the app already refuses to claim it. The title
is `Paste sent`.

The new states do **not** go through `state_changed`: it fans out to the
topbar, the sidebar and the controller as well, and three widget
validators reject states they do not know. The overlay gets its own
method.

Its dot colours are pinned to rendered pixels, not to the QSS, because
four `TranscribeStatus` rules once sat in the stylesheet and never fired
once. Writing those tests immediately found that the base fill was
`danger`, which silently doubled as the recording colour and made the
`[state="failed"]` rule a copy of the base rather than a rule of its own.
The base is now `text_muted` and each state names its own colour.

## A `KeyError` out of an event filter is a segfault

`app/gui/views/history_view.py`. The longest-standing crash in the
suite, and it wore a disguise the whole time: `pytest
tests/gui/test_app_controller.py` died on its 70th test with
`Fatal Python error: Segmentation fault` inside
`pytestqt/plugin.py:_process_events`. It was never Qt, never the
thread pool, and never the tray — every one of those was a dead end
on the way. `HistoryView._apply_column_widths()` indexes
`_fitted_widths`, which the code documents as empty until the first
fit, and `eventFilter` calls it on *every* viewport `Resize`. The first
`Resize` arrives when the window is first shown, which on a view
nobody has populated is strictly before the first `set_entries` — so
`KeyError: 0` was raised from inside a Qt event filter, i.e. from C++
calling into Python.

Three things made it survive so long:

- **A hidden page is still laid out.** `QStackedWidget` resizes its
  non-current pages, so History's viewport got its first `Resize`
  while History was the tab *nobody was looking at*. `isVisible()` is
  False there, so every "did it paint?" assertion pointed at the
  wrong widget.
- **The full suite never hit it**, because some earlier test changes
  the application font, and a font change lands on a fresh view as a
  `changeEvent` that schedules the deferred re-fit — so by the time
  History was reached it had already been measured by an empty table.
  Only the isolated run reproduced it. A test that only ever runs in
  company can be hiding a crash.
- **`lldb` produced no output at all** here, so the native route was
  a dead end. What worked was narrowing in Python: 5–7 probes a
  round, each killing one suspect, until a *plain Qt* reproducer came
  up empty and the bug was provably ours.

The rule it leaves behind: a callback Qt invokes from C++ has no
Python caller to catch for it, so "empty until first use" state has
to be checked at the top of every entry point, not documented once at
the point of creation. Two tests pin it, and they are not
interchangeable — `test_apply_column_widths_before_the_first_fit_hands_out_nothing`
fails cleanly on a `KeyError` in any ordering and is the reliable
witness, while `test_window_survives_its_first_paint_with_an_unpopulated_history`
reproduces the real process-kill but only when run **alone**; in file
order the neighbouring font change has already measured the view, so
it passes against a broken build. Never trust one to cover the other.

## Style / safety rails

- **Don't reach for emojis** — they don't render right in the dark
  QSS theme and the Logs view is monospaced. Same for source files.
- **Don't add new dependencies casually** — the project ships a
  curated set in `pyproject.toml`; any addition should justify itself
  against the package size and Apple Silicon wheel availability
  (some ML libs only ship x86_64 wheels).
- **Don't restate measured figures in comments.** A comment cannot be
  tested, so a comment that quotes a measurement is a claim with
  nothing holding it up — and it goes stale the first time the thing
  is re-measured somewhere testable. Point at where the number is
  published (`README.md`, `docs/index.html`, `MEASURED` in
  `tests/test_model_mapping.py`) instead of copying it. The macOS
  bundle size in `setup.py` went stale this way: the archive was
  rebuilt, the figure was corrected in both published places, and the
  comment was the last one still saying the old value. Note the fix is
  not "update the comment too" — it is that the comment should never
  have carried a number at all.
