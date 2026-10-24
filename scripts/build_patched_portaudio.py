#!/usr/bin/env python
"""Build PortAudio with the vendored CoreAudio stop-deadlock patch.

The macOS build of this app ships the ``sounddevice`` wheel's
``libportaudio.dylib``, and that PortAudio build deadlocks when a stream
is stopped (upstream issue PortAudio/portaudio#1174).  The deadlock holds
the microphone forever and then stops the app from quitting, because
``Pa_Terminate`` waits on the same mutex.

The fix is upstream's, but it is not in a PortAudio release — the last one
is V19.7.0 (2021).  So we build V19.7.0 ourselves with the patch from
``vendor/portaudio/`` and put the result where ``sounddevice`` loads it
from.

Usage::

    # patch the project venv, so ``uv run`` is protected too
    python scripts/build_patched_portaudio.py

    # patch a built bundle (before it is signed)
    python scripts/build_patched_portaudio.py \\
        --bundle "dist/Lazy to Text.app"

    # patch a PyInstaller folder bundle (the Electron runtime)
    python scripts/build_patched_portaudio.py \\
        --dist dist/lazy-to-text-server

    # just build, do not install
    python scripts/build_patched_portaudio.py --no-install

The installed dylib gets a ``.patched.json`` marker next to it, naming
the PortAudio version, the commit and the patch that produced it.  The
marker is what ``scripts/build_server.py`` checks the built runtime for,
so a bundle built without the patch fails the build instead of the release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "portaudio"
PATCH_FILE = VENDOR_DIR / "0001-coreaudio-stop-listener-must-not-re-enter-coreaudio.patch"

#: PortAudio release the wheel's dylib is built from, and the commit it
#: has to be — a tag can be moved, a commit cannot.
PORTAUDIO_REPO = "https://github.com/PortAudio/portaudio.git"
PORTAUDIO_TAG = "v19.7.0"
PORTAUDIO_COMMIT = "147dd722548358763a8b649b3e4b41dfffbcfbb6"

#: The wheel puts its dylib here; this is the path ``sounddevice``
#: falls back to when the system has no PortAudio of its own.
RELATIVE_DYLIB = Path("_sounddevice_data/portaudio-binaries/libportaudio.dylib")

#: The install name the wheel's dylib carries.  ``sounddevice`` opens the
#: library by absolute path, so the id only matters for consistency with
#: what was there before.
INSTALL_NAME = "@rpath/libportaudio.dylib"


def _log(message: str) -> None:
    print(f"→ {message}", flush=True)


def _run(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        raise SystemExit(f"✗ command failed: {' '.join(command)}")
    return None


def _cmake() -> str:
    """Return the cmake to build with.

    ``cmake`` is not a macOS system tool, and the PortAudio sources
    predate cmake 4 (their ``cmake_minimum_required`` is below the
    version cmake 4 still accepts), so the build passes
    ``CMAKE_POLICY_VERSION_MINIMUM`` to keep it working.
    """
    venv_cmake = PROJECT_ROOT / ".venv" / "bin" / "cmake"
    if venv_cmake.exists():
        return str(venv_cmake)
    found = shutil.which("cmake")
    if found:
        return found
    raise SystemExit(
        "✗ cmake not found.\n"
        "  Install it into the project venv:\n"
        "      uv pip install cmake"
    )


def _prepare_source(source_dir: Path) -> Path:
    """Clone PortAudio at the pinned commit and apply the patch."""
    if not (source_dir / ".git").exists():
        _log(f"cloning PortAudio {PORTAUDIO_TAG}")
        if source_dir.exists():
            shutil.rmtree(source_dir)
        _run(["git", "clone", "--depth", "1", "--branch", PORTAUDIO_TAG,
              PORTAUDIO_REPO, str(source_dir)])

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_dir,
                          text=True, stdout=subprocess.PIPE).stdout.strip()
    if head != PORTAUDIO_COMMIT:
        raise SystemExit(
            f"✗ PortAudio source is at {head}, expected {PORTAUDIO_COMMIT}\n"
            f"  Delete {source_dir} and run again."
        )

    # A patch that no longer applies means the vendored copy drifted from
    # the pinned source — that is a hard error, not something to paper
    # over with ``--3way``.
    check = subprocess.run(["git", "apply", "--check", "--reverse",
                             str(PATCH_FILE)], cwd=source_dir, text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    if check.returncode == 0:
        _log("patch already applied")
        return source_dir

    _log("applying the CoreAudio stop-deadlock patch")
    _run(["git", "apply", str(PATCH_FILE)], cwd=source_dir)
    return source_dir


def _build(source_dir: Path, build_dir: Path) -> Path:
    """Build the patched dylib and return its path."""
    cmake = _cmake()
    _log("configuring")
    _run([cmake, "-S", str(source_dir), "-B", str(build_dir),
          "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
          "-DCMAKE_BUILD_TYPE=Release",
          "-DPA_BUILD_SHARED=ON",
          "-DPA_BUILD_STATIC=OFF",
          "-DPA_BUILD_TESTS=OFF",
          "-DPA_BUILD_EXAMPLES=OFF",
          # The wheel ships a universal binary; keep that, so an Intel
          # Mac is not left out of the fix.
          "-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64"])

    _log("building")
    _run([cmake, "--build", str(build_dir), "-j8"])

    built = build_dir / "libportaudio.dylib"
    if not built.exists():
        raise SystemExit(f"✗ expected {built} to exist after the build")

    architectures = subprocess.run(["lipo", "-info", str(built)], text=True,
                                   stdout=subprocess.PIPE).stdout.strip()
    _log(f"built {architectures}")

    # The wheel's dylib is signed by nobody and carries this id; keeping
    # it means the file that replaces it looks the same to the loader.
    subprocess.run(["install_name_tool", "-id", INSTALL_NAME, str(built)],
                   check=True)
    return built


def _install(built: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    # The wheel's dylib is kept aside in the build directory, not next to
    # the target: inside a bundle that would ship the unpatched library
    # as a second file, which is dead weight and a confusing thing to
    # find in a shipped app.
    backup = built.parent / "libportaudio.dylib.wheel-original"
    already_patched = target.with_suffix(target.suffix + ".patched.json").exists()
    if target.exists() and not backup.exists() and not already_patched:
        shutil.copy2(target, backup)

    shutil.copy2(built, target)
    marker = {
        "portaudio_tag": PORTAUDIO_TAG,
        "portaudio_commit": PORTAUDIO_COMMIT,
        "patch": PATCH_FILE.name,
        # The hash of the library as built. Signing rewrites the file
        # afterwards, so this is not the hash of the installed dylib.
        "built_sha256": hashlib.sha256(built.read_bytes()).hexdigest(),
        "upstream_issue": "https://github.com/PortAudio/portaudio/issues/1174",
    }
    target.with_suffix(target.suffix + ".patched.json").write_text(
        json.dumps(marker, indent=2) + "\n"
    )
    _log(f"installed {target}")


def _targets(args: argparse.Namespace) -> list[Path]:
    targets: list[Path] = []
    if args.bundle:
        bundle = Path(args.bundle)
        targets.append(bundle / "Contents" / "Resources" / "lib" /
                       "python3.12" / RELATIVE_DYLIB)
    if args.dist:
        # PyInstaller 6 puts everything under ``_internal``; older layouts
        # put it beside the executable, so both are offered and the one
        # that exists is used.
        dist = Path(args.dist)
        targets.append(dist / "_internal" / RELATIVE_DYLIB)
        targets.append(dist / RELATIVE_DYLIB)
    if args.venv or not (args.bundle or args.dist):
        targets.append(PROJECT_ROOT / ".venv" / "lib" / "python3.12" /
                       "site-packages" / RELATIVE_DYLIB)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", default=None,
                        help="path to a built .app bundle to patch")
    parser.add_argument("--dist", default=None,
                        help="path to a PyInstaller folder bundle to patch")
    parser.add_argument("--venv", action="store_true",
                        help="patch the project venv (the default when no "
                             "--bundle is given)")
    parser.add_argument("--no-install", action="store_true",
                        help="build only, do not install")
    parser.add_argument("--source-dir",
                        default=str(PROJECT_ROOT / "build" / "portaudio-src"),
                        help="where to clone and build PortAudio")
    parser.add_argument("--build-dir",
                        default=str(PROJECT_ROOT / "build" / "portaudio"),
                        help="where to run the cmake build")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    build_dir = Path(args.build_dir)

    _prepare_source(source_dir)
    built = _build(source_dir, build_dir)

    if args.no_install:
        _log(f"built only: {built}")
        return 0

    for target in _targets(args):
        if not target.parent.exists():
            _log(f"skipping {target} (no such directory)")
            continue
        _install(built, target)

    return 0


if __name__ == "__main__":
    sys.exit(main())
