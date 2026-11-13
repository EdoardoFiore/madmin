# Changelog

All notable changes to MADMIN. Versions follow [Semantic Versioning](https://semver.org/):

- **patch** (1.3.1): fixes only;
- **minor** (1.4.0): new features, or a change to a module (modules ship inside MADMIN);
- **major**: a break of compatibility (installation layout, manager protocol v1): not planned.

Every block of work that is pushed bumps the version (`MADMIN_VERSION` in `backend/config.py`), adds an entry here and is tagged `vX.Y.Z`. Only some versions become a signed release; a release id is `<version>+<git commit>`, so two builds of the same version are told apart by the commit (`-dirty` = uncommitted changes, test builds only).

## [1.4.1] - 2026-11-13

### Fixed
- The apt policy (never reboot) was not installed by an update run by an older updater: the agent puts the release's `/etc` files in place at start.
- `os_status.autoupdate.next_run` was always empty.

## [1.4.0] - 2026-11-13

### Added
- The router never reboots by itself: `Unattended-Upgrade::Automatic-Reboot "false"` (`scripts/etc/apt/apt.conf.d/99madmin-unattended-upgrades`). Files under `scripts/etc/` are installed by the installer and by every update (kept for rollback like the units).
- `os.autoupdate.set`: the daily time (and time zone, random delay) of the automatic security updates, set by the manager (`apt-daily-upgrade.timer` drop-in).
- `os.services.restart`: restarts the services needrestart lists (MADMIN last, in a transient unit).
- Facts: `os_status.restart_services`, `kernel_outdated`, `microcode_outdated`, `autoupdate`.

## [1.3.0] - 2026-11-13

First tracked version after 1.2.0. Builds `1.2.0+<commit>` made between 1.2.0 and this version were development builds of this work.

### Added
- Signed releases (`build-release.sh`, `sign-release.sh`, `release-key.sh`), releases layout (`/opt/madmin/releases/<id>`, `current`/`previous`) and `madmin-update`: verify, install with snapshot and health gate, automatic rollback, recover at boot.
- Numbered schema steps (`backend/core/migrations/`, `modules/<id>/upgrades/`).
- `madmin.update` from the manager; `madmin-rescue` reports to the manager when MADMIN is down and runs one action (restart, rollback, install).
- systemd units shipped in the release (`scripts/systemd/`), installed by every update and restored on rollback.
- Agent: OS state in the facts (kernels, reboot required, pending updates, unattended-upgrades), package inventory by digest (`packages`, `python`, `upgrades`), `inventory.get`.
- Agent: OS actions `os.refresh`, `os.upgrade` (security | all), `os.reboot` (a newer kernel boots on trial, `madmin-boot-check.timer` falls back after 15 minutes), `os.reboot.cancel`.
- `upgrades` section: what each OS action would install (security pocket as unattended-upgrade picks it, phased/held/kept back packages).
- Release build checks the wheels against OSV; a critical advisory stops it unless waived in `scripts/osv-waivers.txt`.
- Installer: `GRUB_DEFAULT=saved`, `panic=10`.

### Fixed
- Rollback restored an empty database (dump not readable by postgres) and reported success.
- Boot recovery waited for MADMIN, which waited for it.
- A full disk during the snapshot left the update journal at "running" (16 MB reserve, partial snapshot removed).
- `os.reboot` re-sent after the boot rebooted a second time.
- The venv got the OS's pip (with known advisories) instead of the release's.

### Security
- certifi 2026.10.23, dnspython 2.9.2, pillow 13.0.0, pip 26.3 (OSV advisories).

## [1.2.0] - 2026-11-11

Start of version tracking (tag `agent-v1-baseline`): manager agent with protocol v1 frozen. Instances installed before it are reinstalled, not updated.
