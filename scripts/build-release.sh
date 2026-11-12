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
#   bash scripts/build-release.sh [--allow-dirty] [--out DIR] [--skip-osv]
# The wheels are checked against OSV (PyPI advisories): a critical one stops
# the build unless it is waived, with a reason, in scripts/osv-waivers.txt
# ("<advisory id> <reason>"); the others are listed. --skip-osv only for a
# build machine without network (recorded in the manifest).
# Code comes from `git archive HEAD`: untracked or uncommitted files are
# never in a release (--allow-dirty only lets the build run, for tests, and
# marks the build "-dirty").
# =================================================================
set -euo pipefail
umask 022

ALLOW_DIRTY="false"
OUT=""
SKIP_OSV="false"
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --allow-dirty) ALLOW_DIRTY="true" ;;
        --out) OUT="$2"; shift ;;
        --skip-osv) SKIP_OSV="true" ;;
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
# In a subshell: os-release defines VERSION too
OS_ID="$(. /etc/os-release && echo "${ID}-${VERSION_ID}")"
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
# pip itself: the venv gets the release's pip, not the OS's
print("\n".join(dict.fromkeys(lines + ["pip"])))
PY
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q --upgrade pip wheel
"$WORK/venv/bin/pip" wheel -q -r "$WORK/requirements.txt" -c "$STAGE/backend/requirements.lock" \
    -w "$STAGE/wheels/$OS_ID"
cp "$WORK/requirements.txt" "$STAGE/wheels/requirements.txt"

# Known vulnerabilities of the wheels (OSV, PyPI)
if [ "$SKIP_OSV" = "true" ]; then
    echo '{"checked": false}' > "$WORK/osv.json"
    echo "WARNING: OSV check skipped" >&2
else
    python3 - "$STAGE/wheels/$OS_ID" "$PROJECT_DIR/scripts/osv-waivers.txt" > "$WORK/osv.json" <<'PY'
import glob, json, os, re, sys, urllib.request
from datetime import datetime, timezone
wheels, waivers_file = sys.argv[1:3]
pkgs = {}
for w in glob.glob(os.path.join(wheels, "*.whl")) + glob.glob(os.path.join(wheels, "*.tar.gz")):
    m = re.match(r"^(.+?)-(\d[^-]*?)(-|\.tar\.gz$)", os.path.basename(w))
    if m:
        pkgs[m.group(1)] = m.group(2)
waivers = {}
if os.path.exists(waivers_file):
    for line in open(waivers_file):
        parts = line.split(None, 1)
        if parts and not parts[0].startswith("#"):
            if len(parts) < 2 or not parts[1].strip():
                sys.exit(f"osv-waivers.txt: {parts[0]} has no reason")
            waivers[parts[0]] = parts[1].strip()

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))

names = sorted(pkgs)
res = post("https://api.osv.dev/v1/querybatch",
           {"queries": [{"package": {"ecosystem": "PyPI", "name": n}, "version": pkgs[n]} for n in names]})
found = []
for n, r in zip(names, res.get("results", [])):
    for v in (r or {}).get("vulns") or []:
        d = json.load(urllib.request.urlopen(f"https://api.osv.dev/v1/vulns/{v['id']}", timeout=60))
        sev = str((d.get("database_specific") or {}).get("severity") or "unknown").lower()
        found.append({"id": v["id"], "package": n, "version": pkgs[n], "severity": sev,
                      "aliases": [a for a in d.get("aliases", []) if a.startswith("CVE-")],
                      "waived": waivers.get(v["id"]) or next((waivers[a] for a in d.get("aliases", []) if a in waivers), None)})
blocking = [f for f in found if f["severity"] == "critical" and not f["waived"]]
for f in found:
    tag = "BLOCKING" if f in blocking else ("waived: " + f["waived"] if f["waived"] else "")
    print(f"OSV {f['severity']:9} {f['id']:22} {f['package']} {f['version']} {' '.join(f['aliases'])} {tag}", file=sys.stderr)
if blocking:
    sys.exit("Critical vulnerabilities in the wheels: update the packages (requirements.lock) or waive them in scripts/osv-waivers.txt")
print(json.dumps({"checked": True, "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "packages": len(names), "advisories": found}))
PY
fi

tar -C "$STAGE" -czf "$WORK/payload.tar.gz" .

# Manifest
python3 - "$STAGE" "$WORK/payload.tar.gz" "$VERSION" "$BUILD" "$OS_ID" "$WORK/osv.json" > "$WORK/manifest.json" <<'PY'
import glob, hashlib, json, os, re, sys
from datetime import datetime, timezone
stage, payload, version, build, os_id, osv_file = sys.argv[1:7]
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
    # Informative (the instance ignores it): OSV check of the wheels at build time
    "osv": json.load(open(osv_file)),
}, indent=2))
PY

DEST="$OUT/madmin-$RELEASE_ID.unsigned.tar"
tar -C "$WORK" -cf "$DEST" manifest.json payload.tar.gz
echo "Built: $DEST"
echo "Sign it with: bash scripts/sign-release.sh $DEST <private-key.pem>"
