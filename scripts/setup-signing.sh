#!/usr/bin/env bash
#
# One-time setup: a stable macOS code-signing identity for development.
#
# Why this exists
# ---------------
# Without it the release bundle is ad-hoc signed, and macOS identifies
# an ad-hoc binary by its cdhash — the hash of its own bytes. The cdhash
# changes on every rebuild, so every TCC grant (Accessibility for the
# global hotkeys and the Cmd+V autopaste, Microphone for recording)
# silently stops applying to the next build. The user then sees a
# permission that looks enabled in System Settings and an app that says
# it is not granted, because the entry belongs to a binary that no
# longer exists.
#
# A self-signed identity changes the designated requirement from
#
#     # designated => cdhash H"2a6ab71750e243a94018c32de98566ba..."
#
# to an anchor on the certificate, which does not change between
# builds. Grants then survive rebuilds and reinstalls.
#
# This is the local-development path. A distribution build wants a real
# Apple Developer ID instead, which behaves the same way but is
# verifiable by Gatekeeper on other machines.
#
# Usage
# -----
#     ./scripts/setup-signing.sh
#
# Needs the login keychain password twice — once to trust the
# certificate, once to let codesign reach the private key without
# prompting on every build. Both prompts come from macOS itself; this
# script cannot answer them for you.

set -euo pipefail

# Can ``codesign`` actually use this identity right now?
#
# A listed identity and a usable one are different states: the first is
# what ``find-identity`` reports, the second additionally needs the
# private key's access-control list to grant codesign. When it does not,
# codesign raises a blocking keychain dialog with no timeout of its own,
# so "did it work" has to be answered by signing something and looking —
# never by asking whether the identity appears in a list.
#
# The probe file is thrown away either way; ``mktemp`` keeps concurrent
# runs from sharing one.
_signing_works() {
    local probe
    probe="$(mktemp -t codesign-probe.XXXXXX)"
    # shellcheck disable=SC2064  # expand $probe now, not at trap time
    trap "rm -f '$probe'" RETURN
    codesign -f -s "$1" "$probe" >/dev/null 2>&1
}

cd "$(dirname "${BASH_SOURCE[0]}")/.."

CN="Lazy to Text Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
WORK="$HOME/.cache/l2t-scratch/signing-setup"

# The keychain already has it? Then nothing to do.
#
# ``security`` is captured first and matched afterwards rather than piped
# straight into ``grep -q``.  ``grep -q`` exits on the first match and closes
# the pipe, so ``security`` can die on SIGPIPE (141); under ``set -o pipefail``
# the pipeline then reports failure and this took the *false* branch — the
# script regenerating and re-importing an identity it already had, and asking
# for the keychain password to do it.  Whether that happened depended on how
# much output fitted in the pipe buffer, i.e. on how many other identities the
# machine happened to carry.  This is the mirror image of the zero-identity
# case fixed in an earlier build script, where the same pipeline killed the script
# outright; both now read "no usable identity" as ordinary output with nothing
# matching in it, which is a normal state and not an error.
#
# ``[[ ... == ... ]]`` keeps the match in bash itself, so there is no pipeline
# left for pipefail to have an opinion about.
identities="$(
    security find-identity -v -p codesigning 2>/dev/null || true
)"
if [[ $identities == *"\"$CN\""* ]]; then
    echo "✓ signing identity \"$CN\" is already installed"
    printf '%s\n' "$identities" | sed 's/^/  /'
    # Being *listed* is not the same as being *usable*.
    # ``security find-identity`` reports what the keychain holds and is
    # willing to count; ``codesign`` additionally needs the private key's
    # access-control list to already grant it, which is what the
    # partition list below arranges. The identity appearing here while
    # codesign still blocks on a dialog is a real state this machine was
    # in, and exiting here is what kept the broken one from ever being
    # repaired — re-running the script kept reporting "already installed".
    #
    # So measure it rather than assume it: sign a throwaway file and see
    # whether it comes back.
    if _signing_works "$CN"; then
        echo "  and codesign can use it — nothing to do"
        exit 0
    fi
    echo
    echo "  it is installed but codesign cannot use it yet:"
    echo "  the private key's access-control list does not grant"
    echo "  codesign, so every signing attempt blocks on a keychain"
    echo "  dialog. Continuing on to repair it."
fi

mkdir -p "$WORK"

# A throwaway password for the PKCS#12 handoff into the keychain. It
# only protects the file in transit and is not kept; the keychain's own
# ACL takes over once the item is imported.
PW="$(openssl rand -base64 18)"

echo "→ generating a self-signed code-signing certificate (10 years)"
openssl req -x509 -newkey rsa:2048 \
    -keyout "$WORK/key.pem" -out "$WORK/cert.pem" \
    -days 3650 -nodes \
    -subj "/CN=$CN/O=Lazy to Text/C=US" \
    -addext "keyUsage=digitalSignature" \
    -addext "extendedKeyUsage=codeSigning" 2>/dev/null

# OpenSSL 3 writes PKCS#12 with a KDF that macOS SecKeychainItemImport
# does not accept — it fails with "MAC verification failed" whatever the
# password. ``-legacy`` restores the RC2/3DES scheme macOS still reads.
openssl pkcs12 -export -legacy \
    -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
    -out "$WORK/identity.p12" -passout "pass:$PW" 2>/dev/null

echo "→ importing into the login keychain"
security import "$WORK/identity.p12" \
    -k "$KEYCHAIN" -P "$PW" \
    -T /usr/bin/codesign -T /usr/bin/security >/dev/null

# A self-signed certificate is untrusted by default, which is enough for
# codesign to sign but not for macOS to treat the identity as valid.
echo "→ trusting the certificate for code signing"
echo "  (macOS will ask for the login keychain password)"
security add-trusted-cert -r trustRoot -p codeSign \
    -k "$KEYCHAIN" "$WORK/cert.pem"

# This step is what makes signing work at all, and it is the one that
# silently never ran for a long time.
#
# ``codesign -s <identity>`` against a key whose access-control list does
# not already grant it raises a blocking keychain prompt that has **no
# timeout of its own**. On an interactive desktop someone eventually
# clicks it; from a script, a shell, or CI nobody ever does, so the
# call appears to hang — measured here at ~19 s to sign a one-byte file.
# The partition list is what makes the authorization pre-granted.
#
# It previously passed ``-k "$(security show-keychain-info … | sed -n
# 's/.*password: //p')"``. That command prints
#
#     Keychain "…/login.keychain-db" no-timeout
#
# — there is no ``password:`` in the output at all, so the substitution
# yielded the empty string, ``-k ""`` failed, and the ``|| { … }`` arm
# printed "skipped" and continued. Every later build therefore either
# hung waiting for a dialog or fell back to ad-hoc, which is the thing
# this whole script exists to prevent.
#
# Two changes:
#   * no ``-k`` — let macOS prompt for the password itself, which keeps
#     it out of shell history and out of this file;
#   * ``-l "$CN"`` — scope the grant to this one identity rather than
#     rewriting every private key's ACL in the keychain.
#
# It only works from an interactive session: ``launchctl managername``
# must report ``Aqua``. From a Background session the Security framework
# cannot draw the dialog and reports "User interaction is not allowed."
# rather than hanging, so the failure is honest there.
echo "→ allowing codesign to use the private key without prompting"
echo "  (macOS will ask for the login keychain password — run this from"
echo "   Terminal, not from a background shell)"
if security set-key-partition-list \
        -S apple-tool:,apple:,codesign: -s -l "$CN" "$KEYCHAIN"; then
    echo "  partition list set"
else
    echo "✗ could not set the partition list." >&2
    echo >&2
    echo "  Until this succeeds, codesign will hang on a keychain prompt" >&2
    echo "  that no script can answer, and builds fall back to ad-hoc —" >&2
    echo "  which is what resets Accessibility and Microphone grants." >&2
    echo >&2
    echo "  Run this from a Terminal window in a logged-in session:" >&2
    echo "    security set-key-partition-list \\" >&2
    echo "      -S apple-tool:,apple:,codesign: -s -l \"$CN\" \\" >&2
    echo "      \"$KEYCHAIN\"" >&2
    exit 1
fi

echo
echo "✓ done. Verify with:"
echo "    security find-identity -v -p codesigning"
echo
echo "Next build will sign with it; check the anchor is no longer a"
echo "cdhash:"
echo "    codesign -d -r- \"dist/Lazy to Text.app\""
