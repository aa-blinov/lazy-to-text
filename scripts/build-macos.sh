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

# Signing.
#
# Two separate requirements meet here, and they are not the same thing:
#
# 1. A stable *anchor*, so TCC grants survive a rebuild. Ad-hoc is enough
#    to launch, but it costs the user their Accessibility and Microphone
#    permissions: macOS identifies an ad-hoc binary by its cdhash, and
#    that changes on every rebuild, so grants made to one build silently
#    fail to apply to the next. Measured on the release bundle:
#
#        Signature=adhoc   TeamIdentifier=not set
#        # designated => cdhash H"2a6ab71750e243a94018c32de98566ba..."
#
#    A self-signed identity anchors the requirement on the certificate
#    instead, which is stable across rebuilds. Run scripts/setup-signing.sh
#    once to create one; this script then picks it up on its own.
#
# 2. The *hardened runtime*, which notarization requires outright:
#    "To upload a macOS app to be notarized, you must enable the Hardened
#    Runtime capability." It also denies anything it does not explicitly
#    permit, and this app opens a microphone — see
#    scripts/entitlements.plist.
#
# The two flags below are decided from different things on purpose:
#
#   - ``--timestamp`` is what lets a signature outlive its certificate,
#     and Apple's timestamp authority will not stamp a self-signed
#     identity, so asking for one unconditionally turns a working local
#     build into a failure that looks unrelated to signing. It is wanted
#     exactly when the identity is a Developer ID.
#   - The runtime flag and its entitlements are skipped for an alias
#     build, whose Python is symlinked back to the venv. Library
#     validation would reject those unsigned dylibs at load, so enabling
#     it there breaks the dev loop rather than protecting anything. Alias
#     builds therefore keep ``--deep`` and change nothing else.
#
# ``--force`` overwrites a stale signature from a prior build.
signing_identity="${L2T_SIGN_IDENTITY:-}"
if [[ -z "$signing_identity" ]]; then
    # ``|| true`` is load-bearing, not defensive noise. Having no
    # codesigning identity is a normal state for a fresh machine — it is
    # exactly the case the ad-hoc branch below exists to serve — but
    # ``grep`` still exits non-zero when it matches nothing, and an
    # assignment inherits the status of its command substitution. Under
    # ``set -euo pipefail`` that killed the script right here, so the
    # ad-hoc path below was unreachable and a keychain-less build died
    # before it could print anything useful.
    signing_identity="$(
        security find-identity -v -p codesigning 2>/dev/null |
        grep -o '"[^"]*"' | head -n 1 | tr -d '"' || true
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

entitlements="scripts/entitlements.plist"

# Does a file start with a Mach-O magic number?
#
# The bytes decide because no cheap predicate does. Selecting on
# ``-perm -u+x`` looks right and is wrong: 27 Mach-O files in this bundle
# carry no execute bit, and they are the load-bearing ones —
# ``Contents/Frameworks/libpython3.12.dylib``, which the worker
# interpreter links against, and every ``lib-dynload/*.so`` pyobjc module
# (``_Quartz.so``, ``_AppKit.so``) behind the autopaste and the
# permission checks. Leave them unsigned and library validation refuses
# to load them, which surfaces as a worker that will not start and an
# autopaste that silently does nothing.
#
# Selecting on ``*.so``/``*.dylib`` alone is wrong the other way:
# ``ffmpeg-macos-aarch64-v7.1`` has no extension, and Qt's framework
# binaries live at ``Versions/A/QtCore`` inside a wrapper.
#
# So the find() narrows to the places code actually lives, and the magic
# check drops the data files that share those names — a JPEG and a
# Windows icon both carry an executable bit in here.
_is_macho() {
    local magic
    magic="$(od -An -tx1 -N4 "$1" 2>/dev/null | tr -d ' \n')"
    case "$magic" in
        feedface|feedfacf|cafebabe|bebafeca|cefaedfe|cffaedfe) return 0 ;;
        *) return 1 ;;
    esac
}

# A Developer ID is the only identity another machine trusts, and the
# only one Apple's timestamp authority will stamp. A secure timestamp is
# what lets a signature outlive its certificate, so it is wanted exactly
# here — asking for one from a self-signed identity fails, and the
# failure reads like a signing problem rather than a timestamp one.
_stamp() { [[ "$signing_identity" == "Developer ID"* ]]; }

sign_nested() {
    if _stamp; then
        codesign --force --options runtime --timestamp -s "$signing_identity" "$@"
    else
        codesign --force --options runtime -s "$signing_identity" "$@"
    fi
}

sign_bundle() {
    if [[ "$mode" != "release" ]]; then
        # Alias builds symlink site-packages back into the venv, so there
        # is nothing of ours to sign leaf-first, and the runtime flag
        # would only make the loader reject unsigned venv dylibs.
        codesign --sign "$signing_identity" --deep --force "$bundle"
        return
    fi

    # Inside-out. ``--deep`` signs nested code as a side effect of
    # signing the container, which leaves the order to codesign rather
    # than to this script and is not what Apple's distribution guidance
    # describes. Leaves first, bundle last.
    #
    # Longest path first: a framework is sealed over the binary inside
    # it, so signing that binary afterwards would invalidate it.
    echo "→ signing nested code from the inside out"
    nested_list="$(mktemp -t l2t-nested.XXXXXX)"

    find "$bundle/Contents" \
        \( -type d -name '*.framework' -o -type d -name '*.bundle' \) -print \
        >> "$nested_list"
    while IFS= read -r -d '' candidate; do
        if _is_macho "$candidate"; then
            printf '%s\n' "$candidate" >> "$nested_list"
        fi
    done < <(find "$bundle/Contents" -type f \
                 \( -name '*.so' -o -name '*.dylib' \
                    -o -path '*/Contents/MacOS/*' \
                    -o -name 'ffmpeg-*' \) -print0)

    if ! _stamp; then
        echo "  $(wc -l < "$nested_list" | tr -d ' ') items, no secure timestamp"
        echo "  (a self-signed identity cannot be timestamped; get a Developer ID"
        echo "   before shipping this to anyone else)"
    fi

    signed=0
    while IFS= read -r item; do
        [[ -n "$item" ]] || continue
        if ! sign_nested "$item"; then
            echo "  ✗ could not sign ${item#"$bundle"/}" >&2
            signed=1
            break
        fi
    done < <(awk '{ print length, $0 }' "$nested_list" | sort -rn | cut -d' ' -f2-)
    rm -f "$nested_list"
    [[ $signed -eq 0 ]] || return 1

    # The bundle last, and the only place entitlements are attached:
    # Apple documents them as applying to an executable, which frameworks
    # and plug-ins inherit from their host.
    if _stamp; then
        codesign --force --options runtime --timestamp \
            --entitlements "$entitlements" -s "$signing_identity" "$bundle"
    else
        codesign --force --options runtime \
            --entitlements "$entitlements" -s "$signing_identity" "$bundle"
    fi
}

if ! sign_bundle; then
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

# A signature that does not verify is worse than no signature, and it
# verifies as a *separate* question from the one answered above: codesign
# succeeded can still mean the seal covers bytes that are no longer there.
#
# Not hypothetical. The bundle this script produces was verified on this
# machine and failed with "a sealed resource is missing or invalid",
# listing .pyc files under __pycache__ that a hand-run cleanup had
# deleted after the build had already signed them. The build was green,
# the designated requirement was a certificate, and the artifact could
# not verify — three facts that only disagree with each other if you ask.
#
# Release only: an alias bundle's seal covers a symlink into the venv, so
# verifying it measures the venv rather than the build.
if [[ "$mode" == "release" ]]; then
    echo "→ verifying the seal"
    if ! codesign --verify --deep --strict --verbose=2 "$bundle"; then
        echo "" >&2
        echo "✗ the bundle does not verify against its own signature." >&2
        echo "  Do not ship it: notarization rejects a bundle that cannot" >&2
        echo "  verify, and Gatekeeper will not vouch for it either." >&2
        exit 1
    fi
    echo "  seal is intact"
fi

# Did the signature actually anchor, or did we just build another bundle
# whose permissions die on the next reinstall?
#
# ``codesign`` exiting 0 says nothing about *which* signature it wrote.
# A build can pick an identity and still end up ad-hoc — the identity is
# overridable from the environment, and the release that motivated all
# this shipped ad-hoc from a machine that already carried a perfectly
# good self-signed identity, because "codesign succeeded" was the only
# check. The tell is in the designated requirement, and it is exact:
#
#   ad-hoc  →  cdhash H"…"          new on every build, TCC sees a new
#                                    app, Accessibility + Microphone are
#                                    orphaned
#   signed  →  certificate root = H"…"   constant across rebuilds
#
# So check the requirement rather than the exit status. This also covers
# a partially-signed bundle, where codesign reports success and the outer
# executable is still unanchored.
bundle_requirement="$(codesign -d -r- "$bundle" 2>/dev/null | tail -1 || true)"
if [[ $bundle_requirement == *"cdhash"* ]]; then
    if [[ "$signing_identity" != "-" ]]; then
        echo "" >&2
        echo "✗ signed as \"$signing_identity\" but the requirement is a cdhash." >&2
        echo "  The bundle is ad-hoc; TCC grants will not survive it." >&2
        exit 1
    fi
    echo "  (requirement is a cdhash — expected for ad-hoc)" >&2
else
    echo "→ requirement anchors on the certificate, grants will survive rebuilds"
    echo "  $bundle_requirement"
fi

echo
echo "✓ built $bundle"
echo "  drag it into /Applications, or run:"
echo "      open \"$bundle\""
