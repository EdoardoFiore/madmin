# Release signing keys

Public halves of the Ed25519 keys that sign MADMIN releases (`<name>.pem`).
An instance accepts an update only if its manifest is signed by one of the
keys installed with its current release (`/opt/madmin/updater/keys/`), or by
a key root placed in `/etc/madmin/release-keys.d/` (a test key, for example).

A key is added or removed by a release signed with a key the instances
already trust. See `docs/RELEASING.md`.
