#!/usr/bin/env bash
#
# Build (or rebuild) the macOS ``Lazy to Text.app`` bundle.
#
# Default mode is ``alias`` — py2app symlinks the bundle's
# ``site-packages`` and entry script back into the project's venv,
# so each build takes ~5–10 s and source edits are picked up on
# the next launch with no rebuild.  Pass ``--release`` to produce
# a self-contained bundle suitable for distribution (5–10 minutes; the
# measured download and installed sizes are in README.md).
#
# Only the release mode prunes.  An alias build has no PySide6 of its
# own to trim — it is symlinked back to the venv, and pruning that
# would break ``uv run`` for everything else on the machine.
#
# Usage:
#     ./scripts/build-macos.sh             # alias / dev (fast)
#     ./scripts/build-macos.sh --release   # full bundle (slow)
#
# Prerequisites: ``uv sync`` has been run in the repo (so the venv
# has py2app installed) and the project is on a Mac with Xcode
# command-line tools (``iconutil`` ships with them).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

mode="alias"
if [[ "${1:-}" == "--release" ]]; then
    mode="release"
fi

# Use the already-synced project venv directly. Running ``uv run``
# while ``pyproject.toml`` is temporarily stripped for py2app can
# rewrite ``uv.lock`` to match the patched dependency set.
venv_python=".venv/bin/python"
if [[ ! -x "$venv_python" ]]; then
    echo "✗ expected $venv_python from a prior 'uv sync'" >&2
    exit 1
fi

# Always start from a clean dist/ — py2app refuses to overwrite a
# pre-existing bundle and the residue of an earlier build can
# silently mask missing files.
rm -rf build dist

# Refresh the icon — the squircle is rendered programmatically
# from the same painter the running app uses, so any token /
# colour change picks up automatically.  Skip silently if iconutil
# is missing; the build still works without an icon (it just looks
# generic in the Dock).
if command -v iconutil >/dev/null 2>&1; then
    echo "→ regenerating .icns from the runtime squircle"
    "$venv_python" scripts/generate_icns.py
else
    echo "  (iconutil not found — bundle will use a default icon)"
fi

# py2app 0.28 trips on PEP 621 ``[project] dependencies`` —
# setuptools auto-derives ``Distribution.install_requires`` from
# them and py2app raises ``install_requires is no longer
# supported``.  We can't drop ``dependencies`` from
# ``pyproject.toml`` permanently (every other tool — uv, pip,
# IDEs — reads them from there), so we temporarily strip the
# block, run py2app, restore the original on exit (including on
# Ctrl-C or build failure).
restore_pyproject() {
    if [[ -f pyproject.toml.bak ]]; then
        mv pyproject.toml.bak pyproject.toml
    fi
}
trap restore_pyproject EXIT INT TERM

cp pyproject.toml pyproject.toml.bak
python3 <<'PY'
import re
text = open("pyproject.toml").read()
# Remove the multi-line ``dependencies = [...]`` block so
# setuptools doesn't populate ``install_requires`` from it.
patched = re.sub(
    r"^dependencies\s*=\s*\[.*?^\]\s*$",
    "",
    text,
    flags=re.DOTALL | re.MULTILINE,
)
open("pyproject.toml", "w").write(patched)
PY

# py2app expects a literal ``-A`` flag for alias mode; setup.py
# leaves ``alias`` out of the static config so non-alias builds
# stay self-contained.
if [[ "$mode" == "alias" ]]; then
    echo "→ py2app alias build (fast iteration)"
    "$venv_python" setup.py py2app -A
else
    echo "→ py2app release build (full bundle, slow)"
    "$venv_python" setup.py py2app
fi

# Restore happens via the EXIT trap; keep a no-op here so the
# next ``set -e`` step doesn't see a stale exit code from py2app.
true

bundle="dist/Lazy to Text.app"
if [[ ! -d "$bundle" ]]; then
    echo "✗ expected $bundle to exist after build" >&2
    exit 1
fi

# Drop the Qt this app never loads before anything is signed.
#
# ``_PACKAGES`` has to name the bare ``"PySide6"`` package, because
# naming submodules produces a bundle that dies at launch on a missing
# ``PySide6.QtCore/__init__.pyc``. py2app's answer to that is to copy
# the entire wheel: every Qt module, the QML trees, the designer tools,
# and QtWebEngineCore — which this widgets app never opens a window with.
#
# Pruning here rather than after signing is deliberate: codesign walks
# the tree, so trimming first is both faster and keeps the signature
# matching what actually ships. The keep-list lives in the script and is
# checked against the app's real imports by
# ``tests/test_bundle_contents.py``, so adding a Qt import without
# updating it fails the suite instead of the release.
if [[ "$mode" == "release" ]]; then
    echo "→ pruning the Qt the app never loads"
    "$venv_python" scripts/prune_bundle.py "$bundle"
else
    # An alias bundle symlinks site-packages back into the venv, so there
    # is nothing of ours to prune — and pruning the venv's own PySide6
    # would break ``uv run`` for everything else.
    echo "→ alias build: nothing to prune (Qt is symlinked to the venv)"
fi

# ``Contents/MacOS/python`` is the interpreter that ``SubprocessBackend``
# spawns the inference worker with. That stub links against
# ``@executable_path/../lib/libpython3.12.dylib`` — a path py2app never
# creates, because it puts the dylib in ``Contents/Frameworks``. As
# shipped, running the stub dies on its first instruction with
# ``dyld: Library not loaded``, which is a large part of why the frozen
# macOS build could not use a separate inference process. Verified by
# running the stub out of a shipped release zip.
#
# A relative symlink costs no bytes and resolves to the dylib that is
# already inside the bundle (and already covered by the signature below);
# a copy is the fallback for filesystems that refuse the link.
framework_dylib="$bundle/Contents/Frameworks/libpython3.12.dylib"
lib_dir="$bundle/Contents/lib"
if [[ -f "$framework_dylib" ]]; then
    mkdir -p "$lib_dir"
    if ln -sf ../Frameworks/libpython3.12.dylib "$lib_dir/libpython3.12.dylib" 2>/dev/null; then
        echo "→ libpython staged at Contents/lib (symlink)"
    else
        cp -f "$framework_dylib" "$lib_dir/libpython3.12.dylib"
        echo "→ libpython staged at Contents/lib (copy)"
    fi
else
    echo "⚠ libpython3.12.dylib missing from Contents/Frameworks." >&2
    echo "  The inference worker cannot start without it; the app will" >&2
    echo "  fall back to the in-process backend." >&2
fi

# Codesigning. Ad-hoc is enough to launch, but it costs the user their
# TCC grants: macOS identifies an ad-hoc binary by its cdhash, and that
# changes on every rebuild, so Accessibility and Microphone permissions
# granted to one build silently fail to apply to the next. Measured on
# the release bundle:
#
#     Signature=adhoc   TeamIdentifier=not set
#     # designated => cdhash H"2a6ab71750e243a94018c32de98566ba..."
#
# A self-signed identity makes the designated requirement anchor on the
# certificate instead, which is stable across rebuilds. Run
# scripts/setup-signing.sh once to create one; this script then picks it
# up on its own.
#
# ``--deep`` gives every embedded framework and dylib the same identity;
# ``--force`` overwrites a stale signature from a prior build.
signing_identity="${L2T_SIGN_IDENTITY:-}"
if [[ -z "$signing_identity" ]]; then
    signing_identity="$(
        security find-identity -v -p codesigning 2>/dev/null |
        grep -o '"[^"]*"' | head -n 1 | tr -d '"'
    )"
fi

if [[ -n "$signing_identity" ]]; then
    echo "→ codesigning as \"$signing_identity\""
else
    echo "→ ad-hoc codesigning (no signing identity found)"
    echo "  TCC grants will NOT survive a rebuild — Accessibility and"
    echo "  Microphone permissions have to be re-granted after every"
    echo "  build. Run scripts/setup-signing.sh once to fix that."
    signing_identity="-"
fi

if ! codesign --sign "$signing_identity" --deep --force "$bundle"; then
    echo "✗ codesign failed." >&2
    if [[ "$signing_identity" != "-" ]]; then
        # The signature is load-bearing now, not cosmetic: macOS keys
        # every TCC grant to the designated requirement, and an
        # ad-hoc bundle gets a new cdhash on every rebuild — which is
        # what orphaned Accessibility permissions in the first place.
        # An unsigned or ad-hoc bundle would build green, install, and
        # silently cost the user their permissions next time round.
        echo "" >&2
        echo "  A signed identity was chosen but could not be applied." >&2
        echo "  The bundle below is NOT safe to ship:" >&2
        echo "      codesign -d -r- \"$bundle\"" >&2
        exit 1
    fi
    echo "  Ad-hoc signing failed too; the bundle may need a" >&2
    echo "  quarantine exemption to launch:" >&2
    echo "      xattr -dr com.apple.quarantine \"$bundle\"" >&2
fi

echo
echo "✓ built $bundle"
echo "  drag it into /Applications, or run:"
echo "      open \"$bundle\""
