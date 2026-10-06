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

cd "$(dirname "${BASH_SOURCE[0]}")/.."

CN="Lazy to Text Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
WORK="$HOME/.cache/l2t-scratch/signing-setup"

# The keychain already has it? Then nothing to do.
if security find-identity -p codesigning 2>/dev/null | grep -q "\"$CN\""; then
    echo "✓ signing identity \"$CN\" is already installed"
    security find-identity -p codesigning | sed 's/^/  /'
    exit 0
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

# Without this, every codesign invocation pops a dialog asking to use
# the private key. Partition-list lets the tooling use it silently.
echo "→ allowing codesign to use the private key without prompting"
echo "  (macOS will ask for the login keychain password again)"
security set-key-partition-list \
    -S apple-tool:,apple:,codesign: -s \
    -k "$(security show-keychain-info "$KEYCHAIN" 2>&1 | sed -n 's/.*password: //p')" \
    "$KEYCHAIN" >/dev/null 2>&1 || {
        echo "  skipped — if codesign asks for the key on every build,"
        echo "  run this manually with your keychain password:"
        echo "    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k <password> \"$KEYCHAIN\""
    }

echo
echo "✓ done. Verify with:"
echo "    security find-identity -v -p codesigning"
echo
echo "Next build will sign with it; check the anchor is no longer a"
echo "cdhash:"
echo "    codesign -d -r- \"dist/Lazy to Text.app\""
