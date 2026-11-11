#!/bin/bash
# =================================================================
#                 MADMIN - Release signing key
# =================================================================
#   bash scripts/release-key.sh <name>
#
# Creates an Ed25519 key pair for signing releases (see docs/RELEASING.md):
#   <name>.key.pem   private key, encrypted with a passphrase (asked twice).
#                    Never on a networked disk, never in the repository.
#   <name>.pub.pem   public key: commit it in scripts/release-keys/ so that
#                    instances trust releases signed with this key.
# =================================================================
set -euo pipefail
umask 077

NAME="${1:?key name, e.g. primary or reserve}"
[ ! -e "$NAME.key.pem" ] || { echo "$NAME.key.pem already exists" >&2; exit 1; }
openssl genpkey -algorithm ed25519 -aes-256-cbc -out "$NAME.key.pem"
openssl pkey -in "$NAME.key.pem" -pubout -out "$NAME.pub.pem"
chmod 644 "$NAME.pub.pem"
echo "Private key: $NAME.key.pem (keep it offline)"
echo "Public key:  $NAME.pub.pem -> scripts/release-keys/$NAME.pem"
echo "Key id:      $(openssl pkey -pubin -in "$NAME.pub.pem" -outform DER | sha256sum | cut -c1-16)"
