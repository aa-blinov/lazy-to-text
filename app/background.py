"""Work that must not be felt: a worker process that runs behind everything else.

A long file, and the speaker diarization in front of it, keep every core busy
for as long as the recording is long. Run next to the interface that starves
the window (it cannot be moved), the hotkeys and the dictation that has to
come back in a second. The cure is not a sleep between chunks but the scheduler:
the process that does the file work asks the operating system to run it a step
behind everything the person is using, and keeps to half of the cores.

``enter()`` is called once, by the worker process that is started for this
(``SubprocessBackend(background=True)``); nothing else changes priority.
Every step is best-effort: a platform that refuses leaves a normal-priority
worker, which is slower for the person and still correct.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

log = logging.getLogger(__name__)

_ENV_FLAG = "L2T_BACKGROUND_WORKER"

# POSIX: a few steps behind the interface, not at the bottom. The bottom is
# not a gentler version of the same thing: macOS's "background" policy
# (``taskpolicy -b``) pins a process to the efficiency cores and was measured
# an order of magnitude slower on the same file, which is a long file turned
# into a longer wait for no benefit once the cores are shared by priority.
_NICE = 10
# Windows: processthreadsapi.h. Not PROCESS_MODE_BACKGROUND_BEGIN, for the same reason.
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def is_background() -> bool:
    """True inside the worker process that was started for background work."""
    return os.environ.get(_ENV_FLAG) == "1"


def thread_budget(default: int) -> int:
    """How many compute threads one model session may use.

    The normal worker keeps ``default``; the background one takes at most half
    of the cores, so that the rest stay for the dictation and the interface
    even before the scheduler's priority comes into it.
    """
    if not is_background():
        return default
    return max(1, min(default, (os.cpu_count() or 2) // 2))


def session_options():
    """ONNX Runtime options with the thread budget, or ``None`` outside the
    background worker (the library then picks its own, as it always has)."""
    if not is_background():
        return None
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = thread_budget(os.cpu_count() or 2)
    options.inter_op_num_threads = 1
    return options


def enter() -> bool:
    """Make this process a background one. Returns whether the OS agreed."""
    os.environ[_ENV_FLAG] = "1"
    try:
        lowered = _lower_priority()
    except Exception as exc:  # pragma: no cover - platform specific
        log.warning("Could not lower the priority of the background worker: %s", exc)
        return False
    if not lowered:
        log.warning("The background worker keeps the normal priority on this system.")
    return lowered


def _lower_priority() -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        return bool(kernel32.SetPriorityClass(
            kernel32.GetCurrentProcess(), _BELOW_NORMAL_PRIORITY_CLASS,
        ))
    os.nice(_NICE)
    return True


def current_priority() -> Optional[int]:
    """The process's nice value on POSIX, for tests and the log."""
    if sys.platform == "win32":
        return None
    return os.getpriority(os.PRIO_PROCESS, 0)
