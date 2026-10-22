#!/usr/bin/env python
"""Stress the PortAudio open/start/stop/close cycle on macOS.

This is the canary for the CoreAudio stop deadlock (PortAudio
``#1174``).  The macOS host API installs a property listener on every
audio unit; when the unit stops, the listener re-enters CoreAudio
(``AudioUnitGetProperty``) while the stop path is holding the HAL
mutex, and the two wait for each other.  The stream never stops, the
thread that owns it never returns, and the process can no longer quit:
``Pa_Terminate`` deadlocks on the same mutex.

Unpatched PortAudio V19.7.0 deadlocks within a few hundred cycles — 709
on this machine, against the wheel's own dylib; the patched library
survives thousands.  So the number of cycles that complete is the
measurement — a run that hangs is the bug, not a slow machine.

Usage::

    python scripts/stress_portaudio_stop.py [cycles] [--device NAME] [--duplex]

``--duplex`` opens input and output in the same stream, which is the
shape the upstream repro uses.  It matters: the CoreAudio deadlock needs
the audio unit that carries the notification to be attached to the
output device as well, and an input-only unit does not always hit it.

Exit codes::

    0  every cycle completed — no deadlock
    3  a cycle hung (the deadlock reproduced)
    1  the script itself could not run (no input device, bad args)
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import threading
import time

import sounddevice as sd


#: A cycle that takes longer than this is treated as a deadlock.  The
#: normal cycle is milliseconds; the deadlock is forever, so the exact
#: threshold does not matter — only that it is far above normal and far
#: below "wait for the user".
HANG_SECONDS = 5.0

#: The race window between our stop call and CoreAudio's notification
#: delivery is sub-millisecond, so a fixed pause always hits the same
#: phase and can miss it forever.  The upstream repro sweeps the phase
#: across 0-40 ms; so do we, or the canary never fires.
PHASE_SWEEP_MS = 41

#: Extra gap between cycles, decorrelated from the on-time sweep.
GAP_SWEEP_MS = 7


def _resolve_device(name: str | None):
    """Return the input device index to use, or ``None`` for default."""
    if not name:
        return None
    for index, info in enumerate(sd.query_devices()):
        if name.lower() in info["name"].lower() and info["max_input_channels"] > 0:
            return index
    raise SystemExit(f"no input device matching {name!r}")


def _one_cycle(device, callback, duplex: bool, phase_ms: int) -> None:
    """Open, start, stop and close one stream."""
    if duplex:
        stream = sd.Stream(device=device, channels=1, dtype="float32",
                           callback=callback)
    else:
        stream = sd.InputStream(device=device, channels=1, dtype="float32",
                                callback=callback)
    try:
        stream.start()
        time.sleep(phase_ms / 1000.0)
        stream.stop()
    finally:
        stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cycles", nargs="?", type=int, default=500,
                        help="how many open/start/stop/close cycles to run "
                             "(default: 500)")
    parser.add_argument("--device", default=None,
                        help="substring of the input device name")
    parser.add_argument("--duplex", action="store_true",
                        help="open input and output in the same stream "
                             "(the shape the upstream repro uses)")
    args = parser.parse_args()

    device = _resolve_device(args.device)
    info = sd.query_devices(device, "input") if device is not None else \
        sd.query_devices(kind="input")
    print(f"device: {info['name']} @ {int(info['default_samplerate'])} Hz")
    print(f"mode: {'duplex' if args.duplex else 'input only'}")
    print(f"cycles: {args.cycles}")

    def callback(*args):
        # Duplex streams hand the callback (indata, outdata, frames,
        # time, status); input-only streams hand it four arguments.
        # Either way this callback only has to keep the stream alive.
        pass

    faulthandler.enable()

    for cycle in range(1, args.cycles + 1):
        phase_ms = (cycle - 1) % PHASE_SWEEP_MS
        done = threading.Event()

        def run():
            try:
                _one_cycle(device, callback, args.duplex, phase_ms)
            finally:
                done.set()

        worker = threading.Thread(target=run, daemon=True,
                                  name=f"cycle-{cycle}")
        worker.start()
        if not done.wait(HANG_SECONDS):
            print(f"\nDEADLOCK at cycle {cycle}: the stream did not stop "
                  f"within {HANG_SECONDS:.0f} s", file=sys.stderr)
            faulthandler.dump_traceback()
            sys.stderr.flush()
            # ``os._exit`` and not ``return``: sounddevice's atexit hook
            # calls ``Pa_Terminate``, which deadlocks on the very mutex
            # the deadlock is about -- a normal exit would hang here
            # instead of reporting the deadlock it just found.
            os._exit(3)
        time.sleep(((cycle - 1) % GAP_SWEEP_MS) / 1000.0)
        if cycle % 50 == 0:
            print(f"  {cycle} cycles done")

    print(f"OK: {args.cycles} cycles completed, no deadlock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
