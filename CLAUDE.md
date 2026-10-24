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

The full suite is **1496 passed, 10 skipped** on this machine (main run, `-m "not timing"`), plus 8 timing tests run serially — 1514
collected. Wall time with `-n auto` is 31 s; the serial run took 9 min 42 s, and `tests/gui/` was most of it;
both figures are from one machine and are only a hint on another.

Every skip is a platform conditional or an opt-in — never a missing
model. All ten, by count: six winsound-prewarm and three pywin32 tests
that only exist on Windows, and one opt-in in
`tests/gui/test_recording_factory.py` that is exercised end to end by
the launch smoke test.

The five bundle tests in `tests/test_bundle_contents.py` are the reason
the local count differs from every CI leg's. They look for a built
`dist/Lazy to Text.app`, read the signature it carries, or run the
worker interpreter out of it: they run here, where the bundle exists,
and skip on every CI runner — Windows included, since the bundle is built
by `release.yml`, not `tests.yml` — because they measure an artifact
rather than the source. That is five. The sixth is
`test_a_certified_signature_anchors_and_ad_hoc_does_not`, which is
macOS-only and needs a codesigning identity: it runs here because this
machine has one, and skips on every CI runner because none does. So
local is 1485/10 + 8 timing now, and macOS *and* Windows were 1486/16 at the last green run; Linux adds four
more of its own platform conditionals on top, for 1482/20. The totals
have to match across legs, or a leg has failed at collection.
Measured, not assumed.

`load()` now also runs one short buffer through the model before
publishing `ready` (see "A model that binds is not a model that runs"
below), so a model whose execution provider binds at session-create and
then throws on the first `run()` fails here instead of turning every
dictation into "no speech detected". It costs one inference per load.

**The suite runs in a scratch `HOME`** (`tests/conftest.py`). The models, the Hugging Face hub, the icons and the single-instance lock all live under `$HOME`, so a test that touched them would touch a user's downloaded weights. A test that needs a real path has to say so explicitly.

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
green run is `39958562647` on `a0a392f`, read out
of the run logs rather than carried over from the previous commit:

| Leg | Result |
| --- | --- |
| macos-latest | 1536 passed, 17 skipped |
| windows-latest | 1536 passed, 17 skipped |
| ubuntu-latest | 1532 passed, 21 skipped (under `xvfb-run`) |

1553 collected on every leg, and the totals have to add up to that: a
leg reporting fewer has failed at collection, not lost a test. Locally
1543 pass and 10 skip (the CI table below is from the last green CI run and is refreshed on the next one) — the seven extra skips are the bundle tests, which
run only where a bundle exists.

The Linux leg needs two things the other two have already: a display for
pynput, which opens an X connection at import, and `libportaudio2`, which
`sounddevice` raises `OSError` over at import.

A leg reporting *fewer* tests than that has not lost a test — it has
failed at collection, which is what the collection-time import failures
above look like.

**A green leg used to mean nothing on Windows.** The workflow ran the
two pytest passes as two lines of one step, so the step's exit status
was the *second* one's — the timing pass, eight tests that always pass.
A red main run was therefore reported as a green job. It was found by
reading the run log of the 0.1.19 tag rather than the job's conclusion:
the log said `3 failed, 1486 passed, 17 skipped` and the job said
`success`. The passes are two steps now, so a step's exit status is its
own command's.

The three failures underneath it were the scratch-home guard, and they
were a real gap rather than a bad assertion: `tests/conftest.py`
redirected `$HOME`, which Windows does not read. There `Path.home()`
comes from `USERPROFILE` and `platformdirs` puts the app's cache under
`LOCALAPPDATA`, so the redirect was a no-op — the Windows leg ran
against the real user profile, with the models, the hub cache and the
lock all one directory away from being touched. The fixture redirects
those too now.

The fix for the first version of that was wrong in a way only the
Windows leg could show: the passes were chained with `&&` and a
backslash continuation, and the Windows leg runs PowerShell, where that
is `Unexpected token '&&'`. Two steps, not a shell chain — the shell is
the runner's, and the step is the unit whose exit code is checked.

## Spec-driven development (Spec Kit)

Features are driven from `specs/`, with [Spec Kit](https://github.com/github/spec-kit).
`.specify/memory/constitution.md` holds the principles a change is checked
against, `specs/00x-*` describe what the application already does (baseline,
status `Implemented (baseline)`), and `specs/010-electron-interface/` is the
first feature run through the whole flow. The agent skills live in
`.claude/skills/speckit-*`.

```text
/speckit-specify  -> specs/NNN-name/spec.md     what and why, no how
/speckit-clarify  -> resolves [NEEDS CLARIFICATION] markers
/speckit-plan     -> plan.md, contracts/        how, with the constitution check
/speckit-tasks    -> tasks.md                   ordered, parallel-marked tasks
/speckit-implement
```

A change to behaviour a baseline spec describes changes that spec in the same
pull request. `specs/README.md` is the index.

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

### Two themes, one stylesheet, and one number that cannot match

`app/gui/styles/base.qss` is shared by both palettes. It was `dark.qss`
when there was only a dark theme — an honest name then, and a lie once
there were two. Switching themes is swapping fifteen values in
`TOKENS.colors`; it is not maintaining two stylesheets that have to be
kept from drifting. The three hex literals still in the file are inside
comments, documenting measurements, and `tests/gui/test_first_run.py`
holds that property.

`TOKENS` is swapped **in place**, never rebound. It is imported by name
across the widget tree and several modules hold the object itself, so
rebinding would leave all of them on the dark palette forever. The dark
source is a **copy** (`_DARK_COLORS = dict(TOKENS.colors)`), not
`TOKENS` itself: `TOKENS.colors.clear()` then wipes the very dict it is
about to copy from, and that only shows the *second* time the theme
changes — so a suite that sets each theme once never sees it.

**Reading a token once, at import, is the same bug wearing a hat.** The
swap above preserves the *identity* of `TOKENS.colors`, so holding the
dict is safe and copying its values is not — and four modules did the
copy: `resource_widget.py` and `vu_meter.py` (module-level `QColor`s),
`logs_view.py` (ten hex constants) and the Dock icon's gradient in
`app.py`. All four froze the dark palette, because the dark palette is
what is live when Python imports them.

It stayed invisible because nothing painted a widget and then asked what
colour came out — the offscreen legs set one theme per file, so a
constant read under dark and compared against itself passes under light
too. Measured on the running app instead: CPU fill `#b4b704` against
dark `success` `#b8bb26`, RAM fill `#e19605` against dark `warning`
`#d79921`, and the bar track `#282826` — dark `bg_secondary`, on a cream
window.

The rule that follows: **resolve a colour where it is painted**, never
at import. `tests/gui/test_theme_fidelity.py` switches themes, grabs
the widget and reads the pixels, because the failure has no other
symptom.

**Thirteen of the fifteen light values are canonical Gruvbox swatches**,
and the two that are not cannot be. Only five chromatic swatches clear
4.5:1 as ink on the cream ground — `faded_red`, `faded_purple`,
`faded_blue`, `faded_orange`, `neutral_red` — and there is no green and no
yellow among them. `success` and `warning` are therefore darkened from
`faded_green` (4.29:1) and `faded_yellow` (3.33:1) to clear 4.5:1, and
they are the only two values in either palette that are not a swatch.

This was found by searching, not by deciding. A brute-force search over
every assignment of the sixteen swatches first returned **six
solutions** — all of them in which `accent`, `success`, `danger` and
`warning` were the same near-black. They clear every floor and the
palette is grey. Requiring the state tokens to be chromatic and to
differ from each other in hue by 20° takes the count to **zero**, which
is the actual proof that the two derived values are forced.

Membership is asserted rather than claimed.
`test_both_palettes_are_built_from_the_published_gruvbox_swatches` pins
every value in both palettes to the published list and names the two
exceptions. It is there because it was the one check missing: setting
`accent_focus` back to the hand-derived `#5c1f02` passes every contrast
floor and both state-separation assertions, and would have walked the
palette back out of Gruvbox one commit at a time without a single red
test. Contrast floors cannot police this — any colour can be mixed until
they pass, and mixing is how the palette left the scheme in the first
place.

Every light value was measured. The interesting one is `accent_focus`:

| | dark | light |
| --- | --- | --- |
| `accent_focus` vs `accent` | 1.57:1 | 2.41:1 |
| icon (`bg_primary`) on `accent` | 6.09:1 | 5.40:1 |
| icon (`bg_primary`) on `accent_focus` | 9.56:1 | 12.99:1 |
| `text_muted` on `bg_hover` | 4.17:1 | 5.32:1 |
| quiet step (`text_secondary` − `text_muted`) | 1.46 | 1.66 |
| hover step (`bg_hover` on `bg_secondary`) | 1.27:1 | 1.59:1 |

**The focus step goes *down*, not up, and that was the whole mistake.**
`sidebar.py` paints the selected row's icon in `bg_primary`, because the
fill is `accent`. In the dark theme that fill is light and the icon is
dark ink; inverting the theme inverts that relationship, so in the light
theme the focus fill has to be dark to carry a light icon. This file
used to record the light theme's focus separation as a structural
1.32:1 ceiling — "two dark colours cannot be separated as far as a light
fill can be from a dark one". That was a search that only looked for
**brighter** candidates. Two dark colours separate by going *down* just
as well, and `bg0` does it: **2.41:1** against `faded_orange`, better
than the dark theme's 1.57:1. Both pairs are asserted in `test_theme.py`,
so the ceiling cannot be reintroduced by editing a comment.

Do not "fix" this by brightening `accent_focus` — in an inverted theme
the icon is the light one, so a brighter fill takes it under AA, and
that is the change that would silently remove the keyboard focus
indicator.

**Two light values are one step harder than they look, and the reason is
the same in both.** `text_primary` is `bg0_hard`, not `bg0` — `bg0` is
6.77:1 on the hover plane where muted text has to sit, and the floor
there is 7.0; `bg0_hard` is 7.53:1 and buys the extra half-point for
free, because it is a darker member of the same neutral family.
`accent_hover` is `bg3`, not a second orange: Gruvbox has no such
swatch, and the candidates that do exist are unusable as ink —
`faded_yellow` is 3.33:1 on the cream ground. The dark theme takes
`fg4` for exactly this slot, so the light theme taking `bg3` is
symmetry rather than a compromise.

**The light accent is a hue decision, not a contrast one.** It shipped
as `bright_blue`, which was never low-contrast — the icon sat on it at
5.82:1 and it sat on the rail at 5.25:1. It read wrong because it is
cold and saturated against a warm, desaturated cream ground: a foreign
object rather than part of the palette. The lever is temperature, and
only temperature — in an inverted theme the icon-on-fill ratio and the
fill-on-rail ratio are the *same* number, so there is no lightness or
chroma to spend without taking the icon under AA. It is now
`faded_orange` (hue only, 0.98 saturation against the blue's 0.94 —
saturation was never the lever and an earlier note here claimed it was).

The surface ladder ended up the canonical one — `fg1` / `fg` / `fg2` /
`fg3` for `bg_primary` … `bg_hover` — so the hover step is 1.59:1 and
muted text under it is 5.32:1. Both are asserted. An earlier revision
traded these against each other by hand (`#d9c9a8` vs `#ddcdae`); that
trade stopped existing when the swatches stopped being hand-picked.

### The default that is not the same on every platform

Some of Qt's alignment and metric defaults come from the platform's
style hint, so reading one and handing it straight back is not a
setting — it is a way of inheriting whatever the running platform
thinks. Measured, same source, nothing else changed:

```
cocoa     — what ships on macOS        labelAlignment=2  AlignRight
                                            formAlignment=36  AlignHCenter
offscreen — what every CI leg runs     labelAlignment=1  AlignLeft
                                            formAlignment=33  AlignLeft
```

`_make_section_card` did exactly that, so every Settings label sat
flush right on a Mac and flush left on Windows, Linux and in every
test. Both are named outright now. The general rule this repo has to
follow: **name the Qt property, never write back what you read.**

Two consequences worth keeping:

- **The offscreen suite is blind to this class of bug by
  construction.** A layout default that only differs on macOS has the
  shipped build disagreeing with a suite that is green three times a
  day. When a layout looks wrong on this machine, reproduce it under
  `QT_QPA_PLATFORM=cocoa` before believing an offscreen render —
  building the same `MainWindow` and calling `card.grab()` renders
  through the real cocoa backing store and is enough.
- **Simulating the other platform's default needs a scoped patch, and
  the assertion has to happen outside it.** Patching
  `QFormLayout.labelAlignment` to return `AlignRight` is what forces
  the override to be exercised, but reading the property back while
  that patch is live compares the patch against itself and passes
  either way. `monkeypatch.context()` around the construction fixes
  it — the card writes its own value during that window, and the
  assertion afterwards reads what it really stored.

### An oversized icon is sharp; a tagged one is cut in half

`icon_pixmap` rasterises at `size × screen-dpr` and **leaves the pixmap
untagged**. Both halves are load-bearing and each was measured, not
reasoned about.

The bug was that the nav glyphs were rasterised at exactly their layout
size: a 20×20 bitmap stretched across the 40 physical pixels a 20 px icon
occupies on the built-in Retina display. 384 mid-tone pixels in the icon
column, against 132 for the oversized render — same glyph, same size on
screen, 2.9× fewer soft pixels.

**Do not "improve" this by tagging the pixmap.** `pm.setDevicePixelRatio(dpr)`
next to the oversizing is the obvious companion move and it renders wrong:
the tagged 40×40 dpr-2 pixmap comes back from `QIcon::pixmap(iconSize)` at
40×40, and the list delegate draws it into the 20 px slot at full device
size. Every glyph is clipped to its top-left quarter — Models became an
arrow, Transcribe a corner bracket, History an arc. Qt's item delegate does
not honour the tag on the whole-pixmap draw path. Untagged, the pixmap just
reports 40×40 to `QIcon`, which scales it into the slot.

Handing `QIcon` the resolved SVG (`addFile`) *does* render natively per-dpr,
but it needs the file written to the cache first and measured
byte-identical to oversizing, so it buys nothing.

The tests patch `_screen_dpr` to 2.0 rather than running on a Retina
screen, because CI is offscreen at 1.0 and could not tell a correct build
from a hardcoded 1.0. One test therefore reads the screen directly, since
every other one bypasses the line that does.

### A cocoa-only gap that the offscreen suite cannot see

**A styled `QCheckBox` loses its layout's spacing on cocoa.** Two rows hit
it, and both were reported from screenshots: the preset picker, where the
combo landed at x=152 with the checkbox's cell ending at 153, so its left
edge sat **1 px inside where the label's text ended** — the border running
through the last letter of "Use this one instead"; and the Logs toolbar,
where "Show network logs" ended at x=1940 and the "Clear logs" border began
at x=1942. Same is −1 px at 1200 and at 360, dark and light.

It is the stylesheet-styled checkbox specifically. A `QHBoxLayout` with a
`QLabel` or a `QPushButton` in its place measures a clean 8 px. Two
alternatives were rendered and changed nothing: moving the checkbox's
`spacing: 10px` to `QCheckBox::indicator`'s `margin-right`, and raising the
layout's spacing — the latter only widens the cell the checkbox gets and the
combo moves with it. What works is giving it a plain, unstyled holder,
which does get the spacing.

Four other checkboxes exist (`VadFilterCheckbox`,
`NemoTimestampsCheckbox`, `LlmEnabledCheck`, `AutoPasteCheckbox`). Measured
against the widget on their right, all four sit alone in a row and cannot
have this. `sweep_all_checkboxes.py` in the scratch dir re-checks all six.

**The offscreen platform measures a clean 8 px with the bug present.** That
is the same blindness as the layout defaults above, and it is why the tests
here pin the *tree* — the holder's existence, and that it contributes no
margin and no spacing of its own — rather than the pixels. A geometry-only
test would have stayed green through a revert on all three CI legs. Every
geometry claim here was taken under cocoa.

### The harness that reports the bug is fixed

A sweep meant to find every affected checkbox reported all six as healthy,
and its canary caught it: the row it was written to check no longer
reproduced. Three mistakes, each of which made it blind in a different way
— `check.parentWidget().layout()` is not the row layout (the widget is
added to a sub-layout via `addLayout`, and is now wrapped in a holder, so
`indexOf` returns −1); `check.x()` and `other.geometry()` stop being
comparable once the coordinates live in different parents, which turned a
1 px gap into 926 px; and the canary quietly stops meaning anything the
moment the fix lands.

So it now walks every layout to find the one that holds the widget, maps
both points into the top widget's coordinates, and runs its canary against a
**reconstructed pre-fix tree** rather than the shipped one. The general
rule that came out of it: a canary that passes because the bug is gone is
not a canary, and a verdict from a tool that has never been shown a failure
is not a verdict.

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

## The microphone can wedge the app — and the app has to survive it

**The field report.** On 2026-10-22 the app stopped recording and never
recovered. The log showed the same thing over and over:

```
[WARNING] Recording thread is still alive after stopping; aborting its input stream.
[ERROR]   Aborting the input stream did not return within 1.0 s
[ERROR]   Recording thread is still alive after aborting its input stream
[ERROR]   Microphone is still held by the previous recording. Restart the app.
```

Every dictation after the first one failed that way. Then quitting the app
*hung*: the process stayed alive with no window, still holding
`~/Library/Caches/LazyToText/LazyToTextQt.lock`, so every later launch was
refused — the app looked launched and broken.

**The cause, from the stacks of the wedged process.** Two threads, each
holding the lock the other needs:

```
recording thread : FinishStoppingStream → AudioDeviceStop_mac_imp → HALB_Mutex::Lock()
CoreAudio IO thr : startStopCallback → AudioUnitGetProperty → CoreAudio property lock
```

The stop path holds the AudioUnit instance mutex inside
`AudioOutputUnitStop` and waits for the HAL IOContext mutex; CoreAudio
delivers the `kAudioOutputUnitProperty_IsRunning` notification on its IO
thread while holding that mutex, and PortAudio's listener answers it with
`AudioUnitGetProperty` — which needs the instance mutex the other thread
holds. This is upstream
[PortAudio/portaudio#1174](https://github.com/PortAudio/portaudio/issues/1174)
("macos: deadlock stopping audio", P1, milestone V19.8). The same mutex
is why `Pa_Terminate` deadlocks at exit, which is what turned a broken
microphone into an app that could not be quit.

**The fix we ship.** PortAudio's last release is V19.7.0 (2021) and the
upstream fix is not in it, so the library is built here: `vendor/portaudio/`
holds the patch (the upstream one, verbatim) and
`scripts/build_patched_portaudio.py` builds PortAudio at a pinned commit
and puts the result where `sounddevice` loads it from. `build-macos.sh`
does that before the signing step, because the dylib is inside the
bundle's seal and replacing it afterwards would leave the app unable to
verify against its own signature. The installed dylib gets a
`.patched.json` marker, and `tests/test_bundle_contents.py` fails the
suite when the shipped bundle does not carry it — a bundle built without
the patch is otherwise indistinguishable from a good one until it breaks
in the field, hours later.

**The canary, and why it needs a phase sweep.**
`scripts/stress_portaudio_stop.py` opens and stops streams in a loop and
reports the cycle it died on. Measured on this machine:

| PortAudio | Result |
| --- | --- |
| the wheel's own dylib | **deadlock at cycle 709** |
| the patched dylib | 800 cycles clean, and 2500 cycles clean |

Two things make that script work, and both were found by it not working:

- **The phase between the start and the stop has to be swept.** The race
  window is sub-millisecond, so a fixed pause hits the same phase every
  time and never fires it — 400 cycles of a fixed 20 ms pause passed
  against a library that deadlocks at 709. The upstream repro sweeps
  0–40 ms; so does ours.
- **It must not exit normally.** sounddevice's atexit hook calls
  `Pa_Terminate`, which deadlocks on the very mutex the deadlock is
  about, so a canary that returns from `main()` hangs at exit instead of
  reporting the deadlock it just found. It ends with `os._exit`.

**The app must not depend on the library to be able to quit.** The
patched library makes the stop path safe, but a thread that still cannot
be stopped leaves the app unable to finalize, and an app that cannot quit
is the failure that outlives the next launch. `app/gui/app.py` checks
`AudioRecorder.has_stuck_recording_thread()` on the way out and leaves
the process with `os._exit`, the same escape the ONNX Runtime path
already had. That is a *second* line of defence, not the fix: the fix is
the patched library.

**A green suite proves nothing here.** The deadlock needs a real input
device, a real CoreAudio, and the phase sweep — no test in the repo
loads a model or opens a microphone. The measurement above is the
evidence; the suite only holds the artifact in place.

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

## The hardened runtime — a stable anchor is not a notarizable build

A certificate-anchored signature and a notarizable build are two
different properties, and passing the first says nothing about the
second. Apple requires the **hardened runtime** outright: *"To upload a
macOS app to be notarized, you must enable the Hardened Runtime
capability."* The release bundle this repo produced measured

```
CodeDirectory v=20400 flags=0x0(none)          before
CodeDirectory v=20500 flags=0x10000(runtime)    after
```

`v=20500` is the signature version that can carry the flag at all, so
this is not a flag that was set and ignored.

The runtime denies whatever it does not explicitly permit, and this app
records from a microphone, so `scripts/entitlements.plist` declares
exactly one key: `com.apple.security.device.audio-input`. No
`automation.apple-events` either — the autopaste posts through Quartz
`CGEventPost`, not AppleScript. Accessibility and Microphone
*permissions* are TCC grants, not entitlements; nothing here grants or
bypasses either.

**A self-signed certificate cannot carry the hardened runtime without
one more entitlement, and the reason is worth the whole section.**

The runtime validates every library the process loads against the
loading process's **Team ID**. Team IDs are issued by Apple. A
certificate you generate yourself never has one, so every nested library
in the bundle reports `TeamIdentifier=not set`, dyld will not match it to
the executable, and the inference worker dies on its first instruction:

```
dyld: Library not loaded: @executable_path/../lib/libpython3.12.dylib
Reason: tried: '…/Contents/Frameworks/libpython3.12.dylib' (code signature
  … not valid for use in process: mapping process and mapped file
  (non-platform) have different Team IDs)
```

The failure is invisible from outside, which is what makes it worth
writing down: the window opens, because the app catches a dead worker
and falls back to the in-process backend. Nothing reports an error.
Dictation just quietly stops running in its own process.

Giving the self-signed certificate a Team ID in its OU was tried and
does not work — codesign still reports `TeamIdentifier=not set` for a
certificate Apple did not issue. So the entitlement is the only route,
and it is paid for on the local build only:

| identity | entitlements file | `disable-library-validation` |
| --- | --- | --- |
| Developer ID | `scripts/entitlements.plist` | no — nested code shares the Team ID |
| self-signed / ad-hoc | `scripts/entitlements-local.plist` | yes, or the worker will not start |

`tests/test_bundle_contents.py` holds both files to exactly what they
should contain *and* to their difference, because the wrong fix is easy
and silent: adding the key to `entitlements.plist` turns off a real
protection on the artifact people actually download, and no test reading
only the local file would notice.

**Entitlements on the bundle do not reach the worker.** That is a second
failure of the same shape, and it cost another cycle to find. The
hardened runtime is enforced by *the process*, and
`Contents/MacOS/python` is `exec`'d in its own right, so its signature
is its own. Signing the bundle covers the launcher; the worker needs the
entitlements applied separately, which is why `sign_entry()` exists and
`Contents/MacOS/` is special-cased in the signing loop.

Both halves of this fail the same way, which is what makes them worth a
test each: **the window keeps opening.** The app catches a dead worker,
falls back to the in-process backend, and reports nothing. There is no
error to read and no log line — only a dictation app that has quietly
stopped running inference in its own process. Hence
`test_the_built_inference_worker_actually_runs`, which executes
`Contents/MacOS/python` rather than asking `otool -L` about it: the
linkage test passes against a bundle whose worker cannot start, because
a link is not a promise that dyld will honour it.

**`--options runtime` is applied to nested code explicitly, leaves
first, bundle last.** `--deep` would do it as a side effect of signing
the container, which leaves the order to codesign rather than to the
build script. And the selection predicate cannot be the execute bit:

> 27 Mach-O files under `Contents` carry no execute bit. They are the
> load-bearing ones: `Contents/Frameworks/libpython3.12.dylib`, which
> the worker interpreter links against, 22 `lib-dynload/*.so` pyobjc
> modules behind the autopaste and the permission probes, and four
> bundled dylibs — three of scipy's gfortran runtime and
> `_sounddevice_data`'s `libportaudio`. An unsigned one means the
> inference process will not start, the paste does nothing, or
> `scipy.signal.resample_poly` fails to import. Selecting on
> `-perm -u+x` builds green, passes `codesign`, and ships a dictation
> app that cannot paste.

Selecting on extensions alone fails the other way: `ffmpeg-macos-
aarch64-v7.1` has none, and Qt's framework binaries sit at
`Versions/A/QtCore` inside a wrapper that has to be signed as a
wrapper. So `find` narrows to the places code lives and the Mach-O
magic decides. Measured after the rebuild: **200 of 200 candidates
signed, 23 of 23 bit-less included.**

**The build now refuses to ship a bundle that cannot verify.** `codesign`
exiting 0 and `codesign --verify` passing are different questions, and
this machine answered them differently once: a green build with a
certificate-anchored designated requirement failed
`--verify --deep --strict` with *"a sealed resource is missing or
invalid"*, listing `.pyc` files a hand-run cleanup had deleted after
the build signed them. Nothing in the build can see that; Apple's
notary service is where it would have surfaced. So the seal is checked
where it can still be fixed.

Alias builds are exempt from all of it and deliberately unchanged: their
site-packages is symlinked back to the venv, so turning the runtime on
would make library validation reject unsigned venv dylibs and break the
dev loop rather than protect anything.

Two operational rules this section cost something to learn, both worth
more than the code around them:

- **Never edit a script while a build is running it.** `bash` reads a
  script incrementally, so mutating `build-macos.sh` under a live
  release build does not fail the build — it produces a bundle that was
  signed by whatever bytes happened to be at the offset, which came out
  `flags=0x2(adhoc)` with a broken seal and no entitlements, and every
  measurement taken from it was about a bundle that did not exist.
- **Do not leave probe certificates in the login keychain.** A second
  certificate sharing the CN `Lazy to Text Signing` makes `codesign -s
  "Lazy to Text Signing"` ambiguous, and the release build then stops
  with *"could not sign …"* on the first nested binary. That failure is
  at least honest; the cost was the rebuild.

### What a Developer ID would actually buy

Only Apple's signature — the runtime, the entitlements and the
inside-out ordering are all testable today against the self-signed
identity, which is how the microphone question above was settled without
paying anyone. The paid parts are the certificate ($99/year, waiveable
for nonprofits, education and government), `notarytool submit`, and
`stapler staple`. `spctl --assess` on this bundle answers `rejected`,
and no amount of local work changes that. Full command sequence is in
README.md under *Notarizing the Mac build*.

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

## Where the version comes from — and the lie it can tell

`app/version.py:current_version()` is the only reader, used by the
About dialog and by the version footer at the bottom of Settings
(`shortcuts_view.py`). It asks `importlib.metadata`, and the answer
depends on *which* metadata it reaches first:

- the checkout's `lazy_to_text.egg-info/` — py2app residue, present
  only after a build
- `.venv/…/lazy_to_text-<v>.dist-info` — the installed copy
- `_FALLBACK` in `app/version.py` — when neither resolves

That middle one goes stale on its own. After bumping to 0.1.4 and
re-running `uv sync --frozen`, it still said `lazy_to_text-0.1.3`:
every string comparison in `tests/test_version.py` passed while the
footer displayed **0.1.3** to a tree declaring 0.1.4. A version that
lies is worse than no version, because the user quotes it in a bug
report and believes it. The fix was one command, `uv sync --frozen`;
the guard is `test_the_runtime_reports_the_version_the_tree_declares`,
which compares what the app *would print* against `pyproject.toml`
rather than comparing two strings in the repo. It passes either way
round, since an uninstalled checkout falls back to the pinned string.

`tests/test_version.py` also used to accept **two** hardcoded
fallbacks in `main_window.py` — one per failure branch — and reading
only the first let the second drift. There is one now, in one module,
and the test is an exact-count match rather than a search.

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

## Muting the system output — `app/system_audio.py`

The Settings → Microphone card has a checkbox that mutes the system
output while a recording runs, so music and notifications stay out of
the microphone. macOS only; the control is not built where the platform
cannot do it, because a checkbox that silently does nothing is worse
than no checkbox.

**The mute is CoreAudio's own per-device property**, not a volume
slider and not `osascript`. Three things about that API are not
guessable, and each of them cost a round trip:

- **The output scope is `outp`, not `out `.** `kAudioObjectPropertyScopeOutput`
  is `'outp'`; `'out '` is a different constant, and CoreAudio answers
  `who?` (`kAudioHardwareUnknownPropertyError`) for the *whole
  property* when the address is wrong. The symptom is a mute that
  reports success and changes nothing — the checkbox "does not work",
  with nothing in the log. The value is pinned by a test.
- **The selector is four characters**: `dOut` for the default output
  device, `mute` for the mute property. `dOut ` (with a trailing
  space) is a five-character code, and `int.from_bytes` will happily
  encode it into a nonsense address.
- **The constants live in the SDK, not in a guess**:
  `CoreAudio.framework/Versions/A/Headers/AudioHardwareBase.h`.

`ctypes` rather than a binding package: the app already depends on
`sounddevice`, but nothing on CoreAudio, and two property reads are
not worth a framework binding.

**Every output device is muted, not only the default one.** Measured
on this machine, and it is the difference between the feature working
and the feature doing nothing: the default output device was a
Bluetooth headset whose output channel was *already muted at the device
level*, while the sound the user heard came from another device. A
mute of the default alone would have been a no-op in exactly the
situation the feature is for — and it would have looked like a broken
checkbox rather than a wrong scope. The devices that are already
muted are skipped, and only the ones this call muted are undone.

**Two rules about ownership.** A mute the *user* had already set is not
ours to undo — `mute()` reports it as not muted by us and `restore()`
leaves it alone. And a crash must not leave the machine silent: the
device id is written to `output-mute.json` next to `config.yaml`
*before* the mute, and the file is removed when the mute is undone.
The next launch reads the file back and unmutes the device. The order
matters — the file first means a crash between the two leaves a device
that was never muted, which is harmless; the other way round leaves
the machine silent with nothing to undo it.

**The two acoustic signals sit on opposite sides of the mute.** The
start beep plays *before* the output is muted (it has to be audible),
and the stop beep plays *after* it is unmuted. A user who cannot hear
the confirmation does not know whether the keypress was caught. The
tests assert the order, not just the calls.

## The silero VAD — a global switch, and a second model

Settings → Microphone has a second checkbox: *Skip silence (silero
VAD)*. The recording is cut into its speech segments before it reaches
the model, so the silences cost nothing.

**It is global, not per model**, and that is deliberate. The VAD does
not depend on the model — the same recording is segmented whichever
model recognises it — so a per-model switch would be a second way to
say the same thing.

**The per-model checkbox in the model card is dead.** "VAD filter (skip
silence)" in the Whisper card's inference panel saves `vad_filter` into
`InferenceSettings`, and nothing reads it: the backend never asks for a
VAD, so ticking it changes nothing. It was left alone here because
that panel's layout is measured to the pixel (see the width-floor
computation in `inference_settings_panel.py`) and removing a widget
from it moves the compact/two-column decision. Two VAD checkboxes in
two places is a trap, though — the panel one should go, or become the
per-model override of this switch. Not done here, on purpose.

**The VAD is a second ONNX model, and it lives in the worker.** The
model is loaded through `onnx_asr.load_vad("silero")`, which downloads
`istupakov/silero-vad-onnx` (about 1-2 MB) into the app's own hub
cache on first use. The download must not happen inside a dictation:
the toggle pushes `set_vad_enabled` to the backend on a background
thread, and the worker loads the model there. A load that fails leaves
the feature off and says so in the log — a dictation without the VAD
beats no dictation.

**The result shape changes.** With the VAD on, the recogniser returns
a *stream of segments* (`start` / `end` / `text`), not one text, and
`_transcribe_chunk` reads both shapes. The order of the checks
matters: a plain result has a string `.text` and is read as such; a
stream has no `.text` of its own and is consumed segment by segment.
A stream whose segments carry no text is still an error — the
"unreadable shape" rule predates the VAD and still holds.

## The overlay disappears without an error

The recording overlay — and with it the delivery confirmation — is a
floating panel, and macOS decides on its own whether such a window is
on screen. It can fail in ways that leave no trace in the app: the
window reports itself visible while being nowhere near the screen.

Two of those ways are known, and both are handled now:

- **a window of a hidden application is not on screen**, even after
  ``orderFrontRegardless`` — that call orders the window, it does not
  wake the app. The app lives hidden (its main window sits in the
  tray), so the overlay now wakes it first, with
  ``unhideWithoutActivation`` so the focus stays where the user is
  dictating into.
- **a window on another Space is on screen and invisible at the same
  time.** The collection behaviour makes the window join every space,
  but a window that was already ordered out stays where it was, so
  the overlay re-orders itself onto the active space.

Neither of those was *measured* in the app — the failure was seen
once, in an instance that had been running for hours, and it did not
reproduce in a fresh one. What made the difference is the
instrument: every appearance now writes the window's state to
``app.log`` (``hidden``, ``policy``, ``level``, ``visible``,
``on_active_space``), because the next occurrence has to be named in
the log rather than guessed at.

**The capsule must not re-anchor in the middle of a dictation.** The
anchor is the screen the user is looking at, resolved once per
appearance — and the fallback for an unresolvable anchor is the
*primary* screen, which is where the capsule was seen jumping to. The
state machine used to dip through ``idle`` between the recording ending
and the pipeline starting (the busy flag was set after the recorder had
already been stopped), and the overlay read that dip, hid itself and
appeared again on the next state — re-anchored. The busy flag now goes
up before the recorder is stopped, so the state goes recording →
processing without passing through idle, and the anchor survives the
whole dictation.

**This is what the full-screen case is.** A full-screen app lives in
its own Space, and the overlay joins every Space, so the capsule can
float over it — that is the whole point of the collection behaviour.
But a window that is hidden and shown again is not necessarily in the
Space it was in: it comes back on the app's own Space, which is the
primary display. The capsule was therefore jumping to the first
screen exactly when the recognition started — the hide and re-show in
the middle of the dictation. No hide, no jump. The log line names the screen the window is on, so a
re-anchor would be visible in the log rather than inferred.

**Read the log, not the screen.** ``screencapture`` shows what is on
the screen; the app's own belief about its window is not evidence.
The measurements that mattered here:

- a stand with the real widget: the panel appears, level 25,
  ``CanJoinAllSpaces`` ✓ — so the widget, the level and the
  positioning are not the problem;
- the same stand with a hidden app: the native window says
  ``visible=True`` and nothing is on screen — the two failures look
  identical from the app and only the log tells them apart.

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

## The Electron interface

`desktop/` is a second front end: Electron plus Svelte on `@monos/ui`,
over the Qt-free runtime in `app/server/` (HTTP + SSE on loopback). Spec,
plan, contracts: `specs/010-electron-interface/`.

```bash
cd desktop && npm install && npm run dev
cd desktop && npm test
QT_QPA_PLATFORM=offscreen uv run --frozen python -m pytest tests/server

uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py   # dist/lazy-to-text-server
cd desktop && npm run build && node scripts/dist.mjs --dir                # unpacked app in desktop/release
```

Things that were found by building it:

- **The runtime was not Qt-free.** `app.model_mapping` imported `mark` from
  `app.language`, which imports `QTranslator`; the runtime pulled PySide6 in
  the first time it asked for a model alias. `mark` lives in
  `app/translation_mark.py` now and `app.language` re-exports it. The spec
  also lists PySide6 in `excludes`, and `tests/test_desktop_packaging.py`
  runs the runtime's imports under a meta-path guard.
- **`_child_spawn_env` is for py2app only.** Both py2app and PyInstaller set
  `sys.frozen`; the py2app workarounds (clearing it, pointing at a bundled
  `python`) break a PyInstaller child, which needs
  `multiprocessing.freeze_support()` and nothing else. `_is_py2app_bundle()`
  tells them apart by `sys._MEIPASS`.
- **electron-builder signs every file it copies**, each with a timestamp
  request. The runtime folder has thousands of data files, so
  `scripts/dist.mjs` signs the Mach-O files itself and `signIgnore` keeps
  electron-builder out of `Resources/backend`.
- **The two entitlement pairs differ by one key**, as the Qt pair does, and
  `tests/test_desktop_packaging.py` holds the difference. A self-signed or
  ad-hoc Electron app cannot load its own frameworks under the hardened
  runtime without `disable-library-validation`; a Developer ID build must
  not carry it.
- **`build/` is gitignored repository-wide**, which also swallowed
  `desktop/build/` (entitlements, icons); `.gitignore` re-includes it.
- PyInstaller is a Windows-only dev dependency in `pyproject.toml`, so the
  runtime build gets it with `--with`.

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
