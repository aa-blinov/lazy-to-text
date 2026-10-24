#!/usr/bin/env python
"""Build the headless runtime that the Electron app ships.

    uv run --frozen --with "pyinstaller>=6.0" python scripts/build_server.py

Output: ``dist/lazy-to-text-server/``. One script for all three platforms,
so CI does not need a shell-specific step per leg; the platform-specific
parts are conditionals here, not three copies of a command.

What it does beyond running PyInstaller on ``lazy_to_text_server.spec``:

* macOS: replaces the wheel's PortAudio with the patched one
  (``build_patched_portaudio.py --dist``) and re-signs that one dylib
  ad hoc. PyInstaller signs what it collects, the replacement is a
  different file, and an arm64 process will not load a library whose
  signature does not match. electron-builder signs the finished app, so
  this is only what keeps the folder runnable on its own.
* ``--smoke`` (default on): starts the built binary, waits for the ready
  line and asks ``app.snapshot`` over HTTP. A bundle that builds but does
  not start is the failure this exists for.

Nothing here talks to the network except PortAudio's source clone on macOS
(cached under ``build/``) and whatever PyInstaller itself does.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "lazy-to-text-server"
DIST = ROOT / "dist" / NAME


def _log(msg: str) -> None:
    print(f"-> {msg}", flush=True)


def build() -> None:
    _log("PyInstaller")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(ROOT / "dist"),
         "--workpath", str(ROOT / "build" / "server"),
         str(ROOT / "lazy_to_text_server.spec")],
        cwd=ROOT, check=True,
    )
    if not DIST.is_dir():
        raise SystemExit(f"expected {DIST} after the build")


def check_bundle() -> None:
    """Facts about the built folder that a start-up smoke run cannot see."""
    # A GPL-3.0-or-later module in an MIT application's bundle: excluded in
    # the spec, checked here because an exclude is only a request.
    if any(DIST.rglob("mouseinfo")):
        raise SystemExit("mouseinfo (GPL-3.0-or-later) is in the runtime bundle")
    # The Linux AppImage has no package manager to bring PortAudio, and the
    # build machine's copy is what the smoke run would silently use instead.
    if sys.platform.startswith("linux") and not any(DIST.rglob("libportaudio.so*")):
        raise SystemExit("the Linux runtime bundle carries no libportaudio")
    _log("bundle checks passed")


def patch_portaudio() -> None:
    _log("patched PortAudio")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_patched_portaudio.py"),
         "--dist", str(DIST)],
        cwd=ROOT, check=True,
    )
    for dylib in DIST.rglob("libportaudio.dylib"):
        subprocess.run(["codesign", "--force", "--sign", "-", str(dylib)],
                       check=True)
        _log(f"re-signed {dylib.relative_to(DIST)}")


def exe_path() -> Path:
    return DIST / (NAME + (".exe" if sys.platform == "win32" else ""))


def smoke(timeout: float = 90.0) -> dict:
    """Start the built runtime and ask it for a snapshot.

    Runs in a scratch HOME so the build machine's config and models are
    not touched, and with ``--no-single-instance`` so it does not collide
    with a running application.
    """
    exe = exe_path()
    home = tempfile.mkdtemp(prefix="l2t-smoke-")
    env = dict(os.environ)
    env.update({"HOME": home, "USERPROFILE": home,
                "APPDATA": home, "LOCALAPPDATA": home,
                "XDG_CONFIG_HOME": home, "XDG_CACHE_HOME": home,
                "XDG_DATA_HOME": home,
                "PYTHONUNBUFFERED": "1"})
    _log(f"smoke run: {exe}")
    proc = subprocess.Popen(
        [str(exe), "--no-single-instance"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True,
    )
    tail: list[str] = []
    ready: dict = {}
    got = threading.Event()

    def _read_out() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and "ready" in msg:
                ready.update(msg)
                got.set()
                return

    def _read_err() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            tail.append(line.rstrip())
            del tail[:-40]

    threading.Thread(target=_read_out, daemon=True).start()
    threading.Thread(target=_read_err, daemon=True).start()
    try:
        deadline = time.time() + timeout
        while not got.is_set() and time.time() < deadline and proc.poll() is None:
            time.sleep(0.1)
        if not ready.get("ready"):
            raise SystemExit("the runtime did not print a ready line:\n"
                             + "\n".join(tail))
        req = urllib.request.Request(
            f"http://127.0.0.1:{ready['port']}/rpc",
            data=json.dumps({"method": "app.snapshot", "params": {}}).encode(),
            headers={"Authorization": f"Bearer {ready['token']}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        if "result" not in body:
            raise SystemExit(f"app.snapshot failed: {body}")
        _log("ready line printed, app.snapshot answered")
        return body["result"]
    finally:
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse dist/lazy-to-text-server")
    parser.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()

    if not args.skip_build:
        build()
        if sys.platform == "darwin":
            patch_portaudio()
    check_bundle()
    if not args.no_smoke:
        smoke()
    return 0


if __name__ == "__main__":
    sys.exit(main())
