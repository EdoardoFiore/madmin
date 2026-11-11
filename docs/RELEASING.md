# Releasing MADMIN

An installed instance is updated in place by `madmin-update` (installed in
`/opt/madmin/updater/`) from a **signed release**. The manager stores and
distributes releases but cannot create one: an instance installs only a
release whose manifest is signed by a key it trusts.

## Keys (once)

Two Ed25519 keys, each in a passphrase-protected file kept offline: the
primary in the company vault, the reserve with the second, independent
method. Never on the manager, never in CI, never in the repository.

```bash
bash scripts/release-key.sh primary     # primary.key.pem (secret), primary.pub.pem
bash scripts/release-key.sh reserve
cp primary.pub.pem scripts/release-keys/primary.pem
cp reserve.pub.pem scripts/release-keys/reserve.pem
git add scripts/release-keys/*.pem && git commit -m "chore(release): release signing keys"
```

The keys in `scripts/release-keys/` are installed with every release
(`/opt/madmin/updater/keys/`); a release is verified with the keys of the
release **already installed**, never with the ones it brings. To replace a
key, publish a release signed with a key the instances trust that carries
the new set of public keys.

A test key can be trusted on a single instance by root:
`/etc/madmin/release-keys.d/<name>.pem`.

The public keys can also be pasted in the manager (Impostazioni > Release):
an upload not signed by one of them is refused there too.

## Version

- `MADMIN_VERSION` in `backend/config.py`: semver. A module change bumps the
  module's version **and** MADMIN's (minor, or patch for a fix).
- `MIN_UPGRADE_FROM`: the oldest installed version this release can update in
  place. Older instances are reinstalled.
- A change to an existing table or column needs a schema step:
  `backend/core/migrations/NNNN_<name>.py` or
  `backend/modules/<id>/upgrades/NNNN_<name>.py`, with
  `async def upgrade(conn)` (see `backend/core/migrations/__init__.py`).

## Build, sign, upload

1. Commit and tag (`git tag v1.3.0`), then test on the test server.
2. On an Ubuntu 24.04 machine (the wheels are built for its Python):
   `bash scripts/build-release.sh` → `dist/madmin-<version>+<build>.unsigned.tar`.
3. Copy the `.unsigned.tar` to the offline machine and sign it:
   `bash scripts/sign-release.sh dist/madmin-<id>.unsigned.tar primary.key.pem`.
   It shows the manifest first: check version, build and `payload_sha256`
   against the build output.
4. Upload `madmin-<id>.release` in the manager (Release > Carica release). It
   is a `candidate`: install it on a test instance (Istanze > Aggiorna), then
   promote it to `stable`.

## What an update does

`madmin-update install <file.release>` (the agent starts it after downloading
the release from its manager; root can run it by hand):

1. verify: signature, payload hash, OS, layout, `min_from`, no downgrade, no
   database schema newer than the release
2. unpack into `/opt/madmin/releases/<id>/`, venv from the release's wheels
   only, apt packages of the modules if missing
3. preflight: the new code imports with the current settings
4. snapshot: MADMIN stopped, `pg_dump` and `etc/` + `data/` copied to
   `/opt/madmin/state/snapshots/` (kept 7 days)
5. switch `current` (and `previous`), start MADMIN (schema steps run)
6. health gate (default 5 minutes): service active, `/api/health` 200, and,
   when enrolled, the manager's confirmation after the reconnection
7. commit, or roll back: previous release, database and files restored

Before the snapshot nothing has changed. An update cut by a reboot is
finished or undone at boot (`madmin-update-recover.service`).

```bash
/opt/madmin/updater/madmin-update status
/opt/madmin/updater/madmin-update rollback      # to the previous release, with its snapshot
```
