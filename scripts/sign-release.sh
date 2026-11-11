#!/bin/bash
# =================================================================
#                 MADMIN - Release signing (offline machine)
# =================================================================
#   bash scripts/sign-release.sh [--yes] madmin-<id>.unsigned.tar <private-key.pem>
#
# Signs manifest.json with the Ed25519 release key (asks for its
# passphrase, twice: signing and the check) and writes madmin-<id>.release
# next to the input: the file to upload to the manager. Needs only openssl
# and tar.
#
# The manifest is shown first: check version, build and payload hash
# against the build output before typing the passphrase.
# =================================================================
set -euo pipefail
umask 077

YES="false"
if [ "${1:-}" = "--yes" ]; then YES="true"; shift; fi
IN="${1:?unsigned release (.unsigned.tar)}"
KEY="${2:?private key (.pem)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

NAMES="$(tar -tf "$IN" | sort | tr '\n' ' ')"
[ "$NAMES" = "manifest.json payload.tar.gz " ] || { echo "Not an unsigned release: $NAMES" >&2; exit 1; }
tar -xf "$IN" -C "$WORK" manifest.json
cat "$WORK/manifest.json"
if [ "$YES" != "true" ]; then
    read -r -p "Sign this release? [y/N] " ans
    [[ "$ans" =~ ^[yY]$ ]] || exit 1
fi

openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$WORK/manifest.json" -out "$WORK/manifest.json.sig"
# Check the signature with the public half before handing the file out
openssl pkey -in "$KEY" -pubout -out "$WORK/pub.pem"
openssl pkeyutl -verify -pubin -inkey "$WORK/pub.pem" -rawin -in "$WORK/manifest.json" \
    -sigfile "$WORK/manifest.json.sig" >/dev/null

RELEASE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_id"])' "$WORK/manifest.json")"
OUT="$(dirname "$IN")/madmin-$RELEASE_ID.release"
cp "$IN" "$OUT.part"
tar -rf "$OUT.part" -C "$WORK" manifest.json.sig
chmod 644 "$OUT.part"
mv "$OUT.part" "$OUT"
echo "Signed: $OUT"
echo "Key: $(openssl pkey -pubin -in "$WORK/pub.pem" -outform DER | sha256sum | cut -c1-16)"
