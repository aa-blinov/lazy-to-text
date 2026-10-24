"""``python -m app.server`` — start the headless runtime.

Prints one JSON line on stdout when it is listening::

    {"ready": true, "port": 51234, "token": "...", "pid": 123}

The parent (Electron's main process) reads that line and nothing else from
stdout; logging goes to stderr and ``app.log``. ``--token`` and ``--port``
exist for development, where a browser tab needs a token that does not
change between restarts.
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import os
import secrets
import signal
import sys
import threading


class _NoSensitive(logging.Filter):
    """Keep records tagged ``sensitive`` (the user's words) off stderr."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "sensitive", False)


def _wait_for(done: threading.Event) -> None:
    """Block the main thread until *done*, serving the OS event queue on macOS.

    The macOS hotkey monitor is an ``NSEvent`` global monitor, and AppKit
    delivers those only to a process whose main thread is pumping its event
    queue. In the Qt application Qt does that; here nothing would, and the
    hotkeys would be registered and never fire. An accessory-style application
    (no Dock icon, no menu) pumping its queue is all the monitor needs.
    """
    if sys.platform != "darwin":
        done.wait()
        return
    try:
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyProhibited,
            NSDefaultRunLoopMode,
            NSEventMaskAny,
        )
        from Foundation import NSDate
    except Exception:
        logging.getLogger(__name__).warning(
            "AppKit is unavailable, so global hotkeys cannot be delivered",
            exc_info=True,
        )
        done.wait()
        return
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)
    app.finishLaunching()
    while not done.is_set():
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny, NSDate.dateWithTimeIntervalSinceNow_(0.1),
            NSDefaultRunLoopMode, True,
        )
        if event is not None:
            app.sendEvent_(event)


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(prog="lazy-to-text-server")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--dev", action="store_true",
                        help="also accept pages from the Vite dev server's origin "
                             "(http://127.0.0.1:<--dev-port>); a packaged window "
                             "needs neither")
    parser.add_argument("--dev-port", type=int, default=5173,
                        help="the Vite dev server's port (with --dev)")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="one more page origin to accept; may be repeated")
    parser.add_argument("--data-dir", default=None,
                        help="keep config.yaml, the logs and the history in this "
                             "folder (also L2T_DATA_DIR); for development and "
                             "tests, so runs do not share them")
    parser.add_argument("--no-single-instance", action="store_true",
                        help="skip the lock shared with the Qt application (tests)")
    parser.add_argument("--no-stdin-watch", action="store_true",
                        help="do not exit when stdin closes (development, tests)")
    args = parser.parse_args(argv)
    # Before anything reads the config or opens the log: both resolve their
    # folder from this variable. A folder that was named and cannot be used
    # ends the start here - falling back to the per-user folders would put the
    # logs, the history and the config in a different profile.
    from app.utils import DATA_DIR_ENV, DataDirError, validate_data_dir

    named = args.data_dir if args.data_dir is not None else os.environ.get(DATA_DIR_ENV)
    if named is not None and (args.data_dir is not None or named.strip()):
        try:
            os.environ[DATA_DIR_ENV] = str(validate_data_dir(named))
        except DataDirError as exc:
            print(json.dumps({"ready": False, "error": "bad_data_dir",
                              "message": str(exc)}), flush=True)
            print(str(exc), file=sys.stderr, flush=True)
            return 2

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    # The Logs view shows what was just recognised, on purpose; stderr is
    # kept by whoever launched the process, which is a different store.
    for handler in logging.getLogger().handlers:
        handler.addFilter(_NoSensitive())

    try:
        from app.cuda_bootstrap import ensure_cuda

        ensure_cuda()
    except Exception:  # never block startup over bootstrap noise
        pass

    handle = None
    if not args.no_single_instance:
        from app.instance_manager import try_acquire_single_instance

        # The same name the Qt application takes, on purpose: two front ends
        # driving one microphone and one set of hotkeys is the failure the
        # lock exists to prevent.
        handle = try_acquire_single_instance("LazyToTextQt")
        if handle is None:
            print(json.dumps({"ready": False, "error": "already_running"}),
                  flush=True)
            return 3

    from app.server import rpc
    from app.server.httpd import _PACKAGED_ORIGINS, Channel, dev_origins
    from app.server.runtime import Runtime

    rpc.load_handlers()
    runtime = Runtime()
    runtime.instance_handle = handle
    runtime.start()

    token = args.token or secrets.token_urlsafe(24)
    origins = list(_PACKAGED_ORIGINS) + list(args.allow_origin)
    if args.dev:
        origins += dev_origins(args.dev_port)
    channel = Channel(runtime, token, args.port, origins)
    channel.start()

    done = threading.Event()
    runtime.quit_event = done  # the ``app.quit`` handler sets it

    def _stop(*_: object) -> None:
        done.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(json.dumps({"ready": True, "port": channel.port, "token": token,
                      "pid": os.getpid()}), flush=True)

    # The parent closing our stdin is the portable "you are orphaned"
    # signal: it works the same when the parent was killed outright.
    def _watch_stdin() -> None:
        try:
            while sys.stdin.read(1024):
                pass
        except Exception:
            pass
        done.set()

    if not args.no_stdin_watch and not sys.stdin.isatty():
        threading.Thread(target=_watch_stdin, name="stdin-watch", daemon=True).start()

    _wait_for(done)
    channel.stop()
    runtime.shutdown()
    if runtime.stuck():
        logging.getLogger(__name__).warning(
            "A model load or recording was still running at exit — leaving "
            "immediately instead of waiting for the interpreter to finalize."
        )
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:  # pragma: no cover — defensive
                pass
        os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
