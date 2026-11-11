#!/bin/bash
# =================================================================
#                 MADMIN - Release build
# =================================================================
# Builds an UNSIGNED release from a git checkout:
#
#   dist/madmin-<version>+<build>.unsigned.tar
#       manifest.json     what the release is (version, build, schema, OS...)
#       payload.tar.gz    backend/ frontend/ scripts/ wheels/<os>/
#
# Sign it on the offline machine with scripts/sign-release.sh, which adds
# manifest.json.sig and writes madmin-<version>+<build>.release: the file
# uploaded to the manager. The signature covers the manifest, the manifest
# carries the sha256 of the payload, so nothing is unpacked before both are
# checked.
#
# Run on the OS the release is for (the wheels are built for its Python):
#   bash scripts/build-release.sh [--allow-dirty] [--out DIR]
# Code comes from `git archive HEAD`: untracked or uncommitted files are
# never in a release (--allow-dirty only lets the build run, for tests, and
# marks the build "-dirty").
# =================================================================
set -euo pipefail
umask 022

ALLOW_DIRTY="false"
OUT=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --allow-dirty) ALLOW_DIRTY="true" ;;
        --out) OUT="$2"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${OUT:-$PROJECT_DIR/dist}"
cd "$PROJECT_DIR"

git -c safe.directory="$PROJECT_DIR" rev-parse --git-dir >/dev/null
BUILD="$(git -c safe.directory="$PROJECT_DIR" rev-parse --short=12 HEAD)"
if ! git -c safe.directory="$PROJECT_DIR" diff --quiet HEAD; then
    [ "$ALLOW_DIRTY" = "true" ] || { echo "Uncommitted changes: commit them (or --allow-dirty for a test build)" >&2; exit 1; }
    BUILD="$BUILD-dirty"
fi
VERSION="$(sed -n 's/^MADMIN_VERSION = "\(.*\)"/\1/p' backend/config.py)"
[ -n "$VERSION" ] || { echo "MADMIN_VERSION not found in backend/config.py" >&2; exit 1; }
. /etc/os-release
OS_ID="${ID}-${VERSION_ID}"
RELEASE_ID="$VERSION+$BUILD"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/payload"
mkdir -p "$STAGE" "$OUT"

echo "Building MADMIN $RELEASE_ID for $OS_ID"

# Code: committed files only
git -c safe.directory="$PROJECT_DIR" archive HEAD backend frontend scripts | tar -x -C "$STAGE"

# Wheels: core requirements and every module's pip dependencies, pinned by
# requirements.lock, so an update never depends on PyPI
python3 - "$STAGE/backend" > "$WORK/requirements.txt" <<'PY'
import glob, json, os, sys
backend = sys.argv[1]
lines = [l.strip() for l in open(os.path.join(backend, "requirements.txt"))
         if l.strip() and not l.lstrip().startswith("#")]
for path in sorted(glob.glob(os.path.join(backend, "modules", "*", "manifest.json"))):
    lines += json.load(open(path)).get("system_dependencies", {}).get("pip", [])
print("\n".join(dict.fromkeys(lines)))
PY
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q --upgrade pip wheel
"$WORK/venv/bin/pip" wheel -q -r "$WORK/requirements.txt" -c "$STAGE/backend/requirements.lock" \
    -w "$STAGE/wheels/$OS_ID"
cp "$WORK/requirements.txt" "$STAGE/wheels/requirements.txt"

tar -C "$STAGE" -czf "$WORK/payload.tar.gz" .

# Manifest
python3 - "$STAGE" "$WORK/payload.tar.gz" "$VERSION" "$BUILD" "$OS_ID" > "$WORK/manifest.json" <<'PY'
import glob, hashlib, json, os, re, sys
from datetime import datetime, timezone
stage, payload, version, build, os_id = sys.argv[1:6]
backend = os.path.join(stage, "backend")

def last_step(directory):
    nums = [int(m.group(1)) for f in glob.glob(os.path.join(directory, "*.py"))
            if (m := re.match(r"(\d{4})_", os.path.basename(f)))]
    return max(nums, default=0)

modules, schema_modules, apt = {}, {}, []
for path in sorted(glob.glob(os.path.join(backend, "modules", "*", "manifest.json"))):
    m = json.load(open(path))
    modules[m["id"]] = m["version"]
    schema_modules[m["id"]] = last_step(os.path.join(os.path.dirname(path), "upgrades"))
    apt += m.get("system_dependencies", {}).get("apt", [])
config = open(os.path.join(backend, "config.py")).read()
min_from = re.search(r'^MIN_UPGRADE_FROM = "(.*)"', config, re.M)
h = hashlib.sha256()
with open(payload, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(json.dumps({
    "format": 1,
    "version": version,
    "build": build,
    "release_id": f"{version}+{build}",
    "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "min_from": min_from.group(1) if min_from else version,
    "layout": 1,
    "os": [os_id],
    "schema": {"core": last_step(os.path.join(backend, "core", "migrations")), "modules": schema_modules},
    "modules": modules,
    "apt": sorted(set(apt)),
    "allow_downgrade_from": [],
    "payload_sha256": h.hexdigest(),
    "payload_size": os.path.getsize(payload),
}, indent=2))
PY

DEST="$OUT/madmin-$RELEASE_ID.unsigned.tar"
tar -C "$WORK" -cf "$DEST" manifest.json payload.tar.gz
echo "Built: $DEST"
echo "Sign it with: bash scripts/sign-release.sh $DEST <private-key.pem>"
