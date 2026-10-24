# CLAUDE.md — agent context for `lazy-to-text`

Local-first speech-to-text. An Electron window (`desktop/`) over a headless
Python runtime (`app/server`), cross-platform (Windows / macOS / Linux),
with one ONNX inference path via [`onnx-asr`](https://github.com/istupakov/onnx-asr).
The Qt interface and the CUDA build were removed in spec 011; this file
describes what is left. Keep it skim-able.

## Run / build / test

```bash
uv sync --frozen                 # bootstrap venv from uv.lock
uv run lazy-to-text-server       # the Python runtime alone (prints a ready line)
cd desktop && npm install && npm run dev      # runtime + Vite + Electron

# Tests
uv run --frozen python -m pytest tests/ -n auto -m "not timing"
uv run --frozen python -m pytest tests/ -m timing           # serial
uv run --frozen python -m pytest tests/backends/test_subprocess_backend.py   # <2 s
cd desktop && npm test                                     # renderer and shell (vitest)

# Installers: the runtime first (built on the platform it ships for), then the shell
uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py
cd desktop && npm run build && node scripts/dist.mjs --dir      # unpacked app
cd desktop && npm run dist:mac | dist:win | dist:linux          # installers
```

**The runtime spec, `lazy_to_text_server.spec`, is the only place that says
what ships in the Python half.** `scripts/build_server.py` wraps it: patched
PortAudio on macOS, then a smoke run that reads the ready line and one
`app.snapshot`. A bundle that builds and does not start fails there.

**Both CI workflows sync with `uv sync --frozen`** — `tests.yml` to test
the pins, `desktop.yml` (called by `release.yml`) so the published artifact
*is* those pins. A bare `uv sync` re-resolves and rewrites `uv.lock`, which
is a silent rebuild of the dependency set underneath a green run.
`--frozen` also fails on a missing lockfile instead of quietly inventing one.
A change to `pyproject.toml` dependencies is therefore a change to `uv.lock`
in the same commit (`uv lock`), reviewed like code.

**One release job.** `release.yml` calls `desktop.yml` (three platforms) and
then one job, `release`, creates the GitHub release for a `v*` tag with the
section of `CHANGELOG.md` for that version as its body and attaches every
installer. Only that job holds a write token. A tag with no changelog
section fails before anything is published.

**The suite runs in a scratch `HOME`** (`tests/conftest.py`), and on Windows
in a scratch `USERPROFILE`, `LOCALAPPDATA` and `APPDATA` too: the models, the
Hugging Face hub, the icons and the single-instance lock all live under the
user's profile, so a test that touched them would touch a user's downloaded
weights. A test that needs a real path has to say so explicitly.

**No test loads a model.** The suite stubs onnx-asr throughout and the
repo ships no audio fixtures, so a green run means the plumbing is right,
not that any model transcribes. Model claims get measured by hand
against the real `OnnxAsrBackend`, and the card in
`app/model_mapping.py` has to match that measurement.

Every skip is a platform conditional or an opt-in, never a missing model.
The totals differ between CI legs (Windows-only tests skip elsewhere and the
other way round), and that is not a failure: what matters is that each leg
is non-zero and its skips match its platform. A leg reporting fewer tests
than the others has failed at collection, not lost a test.

`load()` also runs one short buffer through the model before publishing
`ready` (see "A model that binds is not a model that runs" below), so a model
whose execution provider binds at session-create and then throws on the first
`run()` fails there instead of turning every dictation into "no speech
detected". It costs one inference per load.

**A green leg used to mean nothing on Windows.** The workflow ran the two
pytest passes as two lines of one step, so the step's exit status was the
*second* one's, the timing pass, which always passes. The passes are two
steps now, and the Windows leg runs PowerShell, where `&&` is a parse error:
two steps, not a shell chain.

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

| Data | Dev (`uv run`, `npm run dev`) | macOS (packaged) | Windows (packaged) |
| --- | --- | --- | --- |
| `config.yaml` | `<project>/config.yaml` | `~/Library/Application Support/LazyToText/` | `%APPDATA%\LazyToText\` |
| `app.log` + history | `<project>/logs/` | `~/Library/Logs/LazyToText/` | `%LOCALAPPDATA%\LazyToText\Log\` |
| Model weights (HF hub) | `<project>/models/hub/` | `~/Library/Caches/LazyToText/models/hub/` | `%LOCALAPPDATA%\LazyToText\Cache\models\hub\` |
| Single-instance lock | filelock under cache | `~/Library/Caches/LazyToText/LazyToTextQt.lock` | named mutex |

The paths are the ones the Qt application used, on purpose: a user who had
the classic app keeps settings, history and models. `L2T_DATA_DIR` (or
`--data-dir` on the runtime) moves config, logs and history for a test or a
tester; models are not moved.

`config.yaml` is **generated, not tracked** — the app rewrites it on
every start (migrating old keys, adding new ones), so a committed copy
guaranteed a dirty tree. The defaults live in `DEFAULT_CONFIG`
(`app/config_manager.py`) and the file is rebuilt from them on first
launch. Edit `DEFAULT_CONFIG`, not the YAML.

`platformdirs.user_{config,log,cache}_dir("LazyToText", appauthor=False)`
is the single source of truth — `app/utils.py:_is_frozen()` and
`app/config_manager.py:_resolve_base_dir()` gate the frozen paths.

The lock name `LazyToTextQt` is a Qt-era name kept on purpose: a classic copy
that is still installed and the new one exclude each other through it. Rename
it only together with the upgrade path.

## Platform conditionals — what to grep for

- **`sys.platform == "win32"`** — `clipboard_manager`, `audio_feedback`,
  `instance_manager`, `hotkey_listener` (Win32-API replacements:
  `win32api`, `winsound`, named mutex). Each Win-specific import is
  guarded under the same conditional, so the modules import cleanly
  on macOS / Linux.
- **`sys.platform == "darwin"`** — Accessibility / Microphone permission
  checks (`app/macos_permissions.py`, `app/mic_check.py`), the muting of the
  system output (`app/system_audio.py`), worker selection in
  `app/server/runtime.py`, CoreML provider selection
  (`app/backends/onnx_backend.py`).
- **`getattr(sys, "frozen", False)`** — flips data paths to the per-user
  directories (PyInstaller sets it for the packaged runtime).

## Backend topology

```
                    SubprocessBackend                RegistryBackend
                    ──────────────────                ─────────────────
   used on:         everywhere it starts              macOS packaged fallback
   IPC:             multiprocessing.Pipe              direct method calls
   when:            worker acks within 10 s           worker never acked
```

The subprocess exists on Windows to dodge the Win32 DLL-loader-lock, and on
macOS because ONNX Runtime's pybind11 bindings never release the GIL during
session creation: an in-process load starves every Python slot for ~0.3 s,
measured at 341–369 ms against 4.6–10.5 ms for the spawned worker. A thread
cannot fix that and `sys.setswitchinterval` does not see it, so the load has
to leave the process.

Decision lives in `app/server/runtime.py:_build_stack`:

```python
backend = SubprocessBackend(**kwargs)
if sys.platform == "darwin" and getattr(sys, "frozen", False):
    if not backend.wait_for_worker(_WORKER_START_TIMEOUT):
        # A laggy dictation app beats one that never transcribes.
        backend = RegistryBackend(**kwargs)
```

`wait_for_worker()` returns True only when initialisation actually
survived. The reader thread sets the init event on EOF as well as on
the ack, so "the event fired" alone would read a dead worker as a live
backend and leave the app with no engine at all.

The spawn needs no bundle workarounds: the PyInstaller runtime only needs
`multiprocessing.freeze_support()` (called in `app/server/__main__.py`). The
py2app helpers `_child_spawn_env()` and `_is_py2app_bundle()` that used to
live in `subprocess_backend.py` were removed with their tests.

When editing `subprocess_backend.py`, remember it uses
`multiprocessing.get_context("spawn")` instead of the bare
`multiprocessing.Pipe()` / `Process()`. The fixture in
`tests/backends/test_subprocess_backend.py` patches `get_context`
to return a fake ctx — patching the bare module attributes alone
won't intercept the calls. That is also why the file runs in under a
second: there is no real spawn in it.

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
  *sending* for the duration — including the interface's Cancel. Only
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
and puts the result where `sounddevice` loads it from.
`scripts/build_server.py` does that on macOS before the runtime is signed
(`desktop/scripts/dist.mjs` signs it), because the dylib is inside the
seal and replacing it afterwards would leave the app unable to verify
against its own signature. The installed dylib gets a
`.patched.json` marker, and `build_server.py` refuses to finish, and
`tests/test_desktop_packaging.py` fails the suite, when the shipped runtime
does not carry it — a bundle built without
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
is the failure that outlives the next launch. `app/server/__main__.py` asks
`Runtime.stuck()` (which reads
`AudioRecorder.has_stuck_recording_thread()` and the backend's load in
flight) on the way out and leaves the process with `os._exit`, the same escape the ONNX Runtime path
already had. That is a *second* line of defence, not the fix: the fix is
the patched library.

**A green suite proves nothing here.** The deadlock needs a real input
device, a real CoreAudio, and the phase sweep — no test in the repo
loads a model or opens a microphone. The measurement above is the
evidence; the suite only holds the artifact in place.

## Signing — why TCC grants survive rebuilds

macOS keys every Accessibility / Microphone grant to the app's
**designated requirement**, not to its path. What that requirement
anchors on is the whole difference, and both halves were measured:

| Signature | Designated requirement | Rebuilds |
| --- | --- | --- |
| ad-hoc | `cdhash H"24517fd…"` | new every build → TCC sees a new app, both permissions are orphaned |
| self-signed cert | `certificate root = H"b6327a25…"` | constant — verified identical across three different payloads |

`codesign` exiting 0 says nothing about which signature it wrote; the
requirement is what says it (`codesign -d -r- <app>`). `desktop/scripts/dist.mjs`
picks the identity: a Developer ID named by `CSC_NAME`, else the local
identity `Lazy to Text Signing` if the keychain holds it, else ad hoc. It
does not read the requirement back, so after building with a local identity
check it by hand. CI has no identity and signs ad hoc, which is why a CI
release asks for Microphone and Accessibility again after each update.

`scripts/setup-signing.sh` creates the self-signed identity for development
and for distributing to people who already know what they are getting.
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
  with no timeout of its own. The script *probes* rather than assuming,
  so an installed-but-unusable identity is repaired instead of reported
  as "already installed" and skipped.

`set-key-partition-list` only works from an interactive session —
`launchctl managername` must report `Aqua`. Run `setup-signing.sh` from
a Terminal, not from a background shell.

Switching an existing install from ad-hoc to a certificate is a one-time
event: the old grants are keyed to a cdhash that will never come back,
so they have to be cleared once, by hand, and the user grants again.

```bash
tccutil reset Accessibility io.github.aa-blinov.lazytotext
tccutil reset Microphone     io.github.aa-blinov.lazytotext
```

No `sudo` is needed on current macOS. After that one reset, later
reinstalls keep the grants.

## The hardened runtime — a stable anchor is not a notarizable build

A certificate-anchored signature and a notarizable build are two
different properties, and passing the first says nothing about the
second. Apple requires the **hardened runtime** outright: *"To upload a
macOS app to be notarized, you must enable the Hardened Runtime
capability."* The runtime denies whatever it does not explicitly permit,
and this app records from a microphone, so the entitlements declare
`com.apple.security.device.audio-input` (plus the two V8 keys Electron
needs). Accessibility and Microphone *permissions* are TCC grants, not
entitlements; nothing here grants or bypasses either. There is no
`automation.apple-events`: the autopaste posts through Quartz
`CGEventPost`, not AppleScript.

**A self-signed certificate cannot carry the hardened runtime without
one more entitlement, and the reason is worth the whole section.** The
runtime validates every library the process loads against the loading
process's **Team ID**. Team IDs are issued by Apple. A certificate you
generate yourself never has one, so every nested library reports
`TeamIdentifier=not set`, dyld will not match it to the executable, and the
inference worker dies on its first instruction:

```
dyld: Library not loaded: @executable_path/../lib/libpython3.12.dylib
Reason: tried: '…' (code signature … not valid for use in process:
  mapping process and mapped file (non-platform) have different Team IDs)
```

The failure is invisible from outside: the window opens, because the app
catches a dead worker and falls back to the in-process backend. Nothing
reports an error; dictation just quietly stops running in its own process.
Giving the self-signed certificate a Team ID in its OU was tried and does
not work. So the entitlement is the only route, and it is paid for on the
local build only:

| identity | entitlements files (`desktop/build/`) | `disable-library-validation` |
| --- | --- | --- |
| Developer ID | `entitlements.mac.plist`, `entitlements.mac.inherit.plist` | no — nested code shares the Team ID |
| self-signed / ad-hoc | `entitlements.mac.local.plist`, `entitlements.mac.local.inherit.plist` | yes, or the runtime will not start |

`tests/test_desktop_packaging.py` holds both pairs to exactly what they
should contain *and* to their difference, because the wrong fix is easy and
silent: adding the key to the Developer ID files turns off a real protection
on the artifact people actually download.

**Entitlements on the app do not reach the runtime.** The hardened runtime is
enforced by *the process*, and `resources/backend/lazy-to-text-server` is
`exec`'d in its own right, so its signature is its own. `dist.mjs`
signs every Mach-O file in the runtime folder itself, libraries first and
executables last, with the inherit entitlements, and `signIgnore` keeps
electron-builder out of that folder (it would sign thousands of data files
with a timestamp request apiece).

**The selection predicate cannot be the execute bit alone.** Dozens of
Mach-O files carry no execute bit and are the load-bearing ones: the
interpreter's `libpython`, the `lib-dynload/*.so` modules behind the
autopaste and the permission probes, and the bundled dylibs (scipy's
gfortran runtime, `libportaudio`). An unsigned one means the worker will
not start, the paste does nothing, or `scipy.signal.resample_poly` fails to
import. `dist.mjs` takes every `.so` and `.dylib` plus anything executable.

Both halves of this fail the same way, which is what makes them worth a test
each: **the window keeps opening.** Hence the smoke run in `build_server.py`,
which starts the built runtime and requires the ready line and one snapshot,
rather than asking `otool -L` about it.

Two operational rules this cost something to learn:

- **Never edit a script while a build is running it.** `bash` reads a
  script incrementally, so mutating one under a live build produces a
  bundle signed by whatever bytes happened to be at the offset, with a
  broken seal and no entitlements, and every measurement taken from it is
  about a bundle that did not exist.
- **Do not leave probe certificates in the login keychain.** A second
  certificate sharing the CN `Lazy to Text Signing` makes `codesign -s
  "Lazy to Text Signing"` ambiguous, and the build then stops with
  *"could not sign …"* on the first nested binary.

### What a Developer ID would actually buy

Only Apple's signature — the runtime, the entitlements and the
inside-out ordering are all testable today against the self-signed
identity. The paid parts are the certificate ($99/year, waiveable for
nonprofits, education and government), `notarytool submit`, and
`stapler staple`. Set `CSC_NAME` to the identity and `dist.mjs` takes the
strict entitlement files and a secure timestamp; the notarisation commands
(`xcrun notarytool submit … --wait`, `xcrun stapler staple`) are then run on
the resulting `.app`. `spctl --assess` on a self-signed build answers
`rejected`, and no amount of local work changes that.

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

## Where the version comes from — and the lie it can tell

The version has several places and nothing in the build fails when they
disagree: `pyproject.toml` (canonical), `app/version.py` `_FALLBACK`,
`desktop/package.json`, and the two `version` fields at the top of
`desktop/package-lock.json`. `tests/test_version.py` holds them equal and
requires the newest `v*` tag to match `pyproject.toml`; `release.yml` checks
the tag again. The order is fixed: bump all of them, commit, tag,
`uv sync --frozen`, build, verify, then push the tag.

`app/version.py:current_version()` is the only reader, used by the About
dialog and the footer of Settings. It asks `importlib.metadata`, and the
answer depends on *which* metadata it reaches first: the installed
`.venv/…/lazy_to_text-<v>.dist-info`, else `_FALLBACK`. In the packaged
runtime the `lazy-to-text` distribution metadata is not bundled, so the About
text shows `_FALLBACK`: it must be bumped with every release.

The installed copy goes stale on its own. After bumping to 0.1.4 and
re-running `uv sync --frozen`, it still said `lazy_to_text-0.1.3`: every string
comparison in `tests/test_version.py` passed while the footer displayed
**0.1.3** to a tree declaring 0.1.4. A version that lies is worse than no
version, because the user quotes it in a bug report and believes it. The fix
is one command, `uv sync --frozen`; the guard is
`test_the_runtime_reports_the_version_the_tree_declares`, which compares what
the app *would print* against `pyproject.toml`.

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
  no relaunch button: the grant is picked up live, because the
  permissions handler (`app/server/handlers/permissions.py`) stops and
  re-starts the hotkey listener, which rebuilds `MacHotkeyMonitor`
  against the new state.
- **Microphone** (`AVCaptureDevice.authorizationStatus`) — system
  prompt fires automatically via `requestAccessForMediaType_` the
  first time we call it. `app/mic_check.py` wraps it; the Settings banner shows authorized /
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

## Tests — naming conventions

- `tests/server/` — the runtime protocol: handlers, RPC, events, safe paths
- `tests/backends/` — backend dispatch + worker process tests
- `tests/utils/` — `app/utils.py` helpers
- `tests/test_*.py` (top level) — everything else: audio recorder, clipboard
  manager, hotkey listener, config manager, history manager, model mapping,
  start-up helpers (`test_bootstrap*.py`, `test_file_logging.py`), the
  recording factory, the translation check, the release workflow, the
  desktop packaging rules (`test_desktop_packaging.py`)

Service tests are top-level files named after the module they cover, so look
for `tests/test_clipboard_manager.py`.

Always pass `-x` during dev so the first failure surfaces fast.

## Translations

`desktop/renderer/src/i18n/*.json` is the only Russian catalogue: a flat
`{"English source": "Russian"}` table per area, merged by `lib/i18n.js`.
Sentences Python builds are wrapped in `mark()` (`app/translation_mark.py`) and
translated by the renderer, whole or by `%1` template. `scripts/check_translations.py`
(run by `tests/test_translations.py`) fails when a renderer `$t('…')` string or
a Python `mark()` sentence has no Russian entry. It cannot prove an entry is
unused: a runtime template can be live without appearing literally, so
entries are only deleted by hand.

## Delivery confirmation — three values, not two

A failed copy leaves the text nowhere; a failed keystroke leaves it on the
clipboard waiting for the user, and the dictation still belongs in History.
`ClipboardManager.deliver_transcription` returns `pasted` / `copied` /
`failed` for exactly that reason. The capsule never claims "Pasted":
`_send_paste_combo` reports only that keystrokes went out, and no platform API
confirms the target app pasted, so the title is `Paste sent`. And `idle` must
not hide a live confirmation: the state machine reaches `idle` milliseconds
after the delivery is reported, so the shell keeps the confirmation up until
its own timer expires.

## The Electron interface

`desktop/` is the only front end: Electron plus Svelte on `@monos/ui`, over
the Qt-free runtime in `app/server/` (HTTP + SSE on loopback). Spec, plan,
contracts: `specs/010-electron-interface/`; the removal of the Qt window is
spec 011.

Things that were found by building it:

- **The runtime must stay free of any UI toolkit.** `tests/test_desktop_packaging.py`
  runs the runtime's imports under a meta-path guard that refuses `PySide6`,
  and the spec lists PySide6 in `excludes`. `app/translation_mark.py` exists so
  `app.model_mapping` can mark strings without a translator.
- **electron-builder signs every file it copies**, each with a timestamp
  request. The runtime folder has thousands of data files, so
  `desktop/scripts/dist.mjs` signs the Mach-O files itself and `signIgnore` keeps
  electron-builder out of `Resources/backend`.
- **The two entitlement pairs differ by one key**, and
  `tests/test_desktop_packaging.py` holds the difference (see "The hardened
  runtime").
- **The app id is `io.github.aa-blinov.lazytotext`** (0.2.1; 0.2.0 still used
  the Qt application's `ai.eora.lazytotext`, which was a work domain on a
  personal project). A build signed with the same identity keeps the
  Microphone and Accessibility grants across rebuilds (the CI build is ad hoc
  and does not). electron-builder derives the Windows uninstall entry from the
  id, so the installer removes the entry of each earlier id; the classic Qt
  build is found by its Inno key instead.
- **`build/` is gitignored repository-wide**, which also swallowed
  `desktop/build/` (entitlements, icons); `.gitignore` re-includes it.
- PyInstaller is a Windows-only dev dependency in `pyproject.toml`, so the
  runtime build gets it with `--with`.
- **The icons are drawn by `scripts/make_icons.py`**, which needs PySide6 as a
  drawing library only: `uv run --with pyside6 python scripts/make_icons.py`.
  The generated PNG, ICNS and ICO are committed.

## Style / safety rails

- **Don't reach for emojis** — the Logs view is monospaced and they render
  badly. Same for source files.
- **Don't add new dependencies casually** — the project ships a
  curated set in `pyproject.toml`; any addition should justify itself
  against the package size and Apple Silicon wheel availability
  (some ML libs only ship x86_64 wheels).
- **Don't restate measured figures in comments.** A comment cannot be
  tested, so a comment that quotes a measurement is a claim with
  nothing holding it up — and it goes stale the first time the thing
  is re-measured somewhere testable. Point at where the number is
  published (`README.md`, `docs/index.html`, `MEASURED` in
  `tests/test_model_mapping.py`) instead of copying it. The fix when one
  goes stale is not "update the comment too" — it is that the comment should
  never have carried a number at all.
