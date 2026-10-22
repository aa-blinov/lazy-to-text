# Vendored PortAudio patch

## What this is

PortAudio's macOS (CoreAudio) host API deadlocks when a stream is
stopped. Upstream tracks it as
[PortAudio/portaudio#1174](https://github.com/PortAudio/portaudio/issues/1174)
("macos: deadlock stopping audio", P1, `src-coreaudio`, milestone V19.8).

The deadlock is an AB-BA lock inversion between two threads:

- the thread calling `Pa_StopStream` holds the AudioUnit instance mutex
  inside `AudioOutputUnitStop` and then waits for the HAL IOContext mutex;
- CoreAudio delivers the `kAudioOutputUnitProperty_IsRunning` change
  notification synchronously on the HAL IO thread, which holds the HAL
  IOContext mutex, and PortAudio's `startStopCallback` listener answers it
  with `AudioUnitGetProperty` — a call that needs the AudioUnit instance
  mutex the other thread holds.

Each thread waits for the lock the other one holds. The stream never
stops, the thread that owns it never returns, and `Pa_Terminate` later
deadlocks on the same mutex — so the process cannot even quit.

The fix in `0001-coreaudio-stop-listener-must-not-re-enter-coreaudio.patch`
is the upstream one (commit `489c0b4` in the reporter's fork, not yet in a
PortAudio release): the listener no longer calls back into the AudioUnit.
It infers the stop transition from `stream->state` instead, which
`StopStream`/`AbortStream` set to `STOPPING` before they stop the units.

## Why we carry the patch instead of waiting for a release

PortAudio's last release is V19.7.0 (2021); everything newer is
"19.7.0-devel" on master, and the fix is not in it. The `sounddevice`
wheel bundles a V19.7.0-devel build, so the bug is in every macOS build
of this app until we replace that dylib ourselves.

`scripts/build_patched_portaudio.py` builds PortAudio V19.7.0 with the
patch applied and installs the result over the wheel's
`libportaudio.dylib` — in the project venv for `uv run`, and in the
bundle for the shipped app.

## Pin

| | |
| --- | --- |
| PortAudio version | `v19.7.0` |
| commit | `147dd722548358763a8b649b3e4b41dfffbcfbb6` |
| patch | `0001-coreaudio-stop-listener-must-not-re-enter-coreaudio.patch` |

## How it is verified

`scripts/stress_portaudio_stop.py` is the canary. It sweeps the phase
between the start and the stop of each cycle across 0–40 ms, because the
race window is sub-millisecond and a fixed pause hits the same phase
forever. Against the unpatched wheel it deadlocks within a few hundred
cycles and prints the cycle it died on; against the patched library it
runs thousands of cycles and exits cleanly.

The same measurement, made on the running app, is what the fix is for:
the microphone dying mid-dictation, every subsequent dictation failing
with "the microphone is still held by the previous recording", and the
app being unable to quit because `Pa_Terminate` deadlocks on the same
mutex.

## Licensing

PortAudio is MIT-licensed. The patch is the upstream fix, carried
verbatim apart from the comment wording.
