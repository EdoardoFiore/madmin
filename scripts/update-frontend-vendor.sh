#!/bin/bash
#
# Refresh the third-party frontend libraries in frontend/assets/vendor/.
#
# The UI used to load them from cdn.jsdelivr.net at every page view: a slow or
# unreachable CDN left pages without styles or icons, and an unversioned URL
# (apexcharts) swapped the library under us whenever upstream released.
# They are now committed to the repository, so an installed VM serves them
# itself and needs no internet access to render its UI.
#
# To upgrade a library: bump its version below, run this script from the repo
# root, then update the paths in frontend/*.html. Every library lives in a
# directory named after its version, so a new version is a new URL and the
# long-lived cache nginx sets on /static never serves a stale copy.
#
# Requires: curl, tar.

set -euo pipefail

TABLER_VERSION="1.6.0"
TABLER_ICONS_VERSION="3.48.0"
# 4.7.0 is the last MIT release. From 5.2.0 ApexCharts is dual-licensed (free
# only below $2M yearly revenue, OEM license for products used by others):
# check the license before moving past 4.x.
APEXCHARTS_VERSION="4.7.0"
SORTABLEJS_VERSION="1.15.7"
# Calendar engine behind tabler.Datepicker (it reads window.VanillaCalendarPro).
# Keep it on the version the Tabler release ships in dist/libs; its styles are
# already part of tabler.min.css.
VANILLA_CALENDAR_VERSION="3.3.2"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_DIR/frontend/assets/vendor"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# fetch <npm package> <version> → prints the directory holding the unpacked package
fetch() {
    local name="$1" version="$2"
    local dest="$TMP_DIR/${name//\//_}"
    mkdir -p "$dest"
    curl -fsSL "https://registry.npmjs.org/$name/-/${name#*/}-$version.tgz" | tar xz -C "$dest"
    echo "$dest/package"
}

rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR"

# Tabler: CSS + JS. tabler.min.js bundles Bootstrap, so Bootstrap is not vendored separately.
# The package ships no LICENSE file: the MIT notice is in the banner of both files.
pkg="$(fetch @tabler/core "$TABLER_VERSION")"
dest="$VENDOR_DIR/tabler-$TABLER_VERSION"
mkdir -p "$dest"
cp "$pkg/dist/css/tabler.min.css" "$pkg/dist/js/tabler.min.js" "$dest/"

# Tabler Icons webfont: outline set, woff2 only (every supported browser reads it).
# The filled set is not an add-on: its CSS redefines .ti to the filled font, so
# loading it next to the outline set would turn every icon filled.
pkg="$(fetch @tabler/icons-webfont "$TABLER_ICONS_VERSION")"
dest="$VENDOR_DIR/tabler-icons-$TABLER_ICONS_VERSION"
mkdir -p "$dest/fonts"
cp "$pkg/dist/fonts/tabler-icons.woff2" "$dest/fonts/"
sed -E 's#src:url\("\./fonts/tabler-icons\.woff2\?v[0-9.]+"\) format\("woff2"\)[^;}]*#src:url("./fonts/tabler-icons.woff2") format("woff2")#' \
    "$pkg/dist/tabler-icons.min.css" > "$dest/tabler-icons.min.css"
if grep -qE '\.(woff|ttf)[?"]' "$dest/tabler-icons.min.css"; then
    echo "ERROR: could not rewrite the @font-face of tabler-icons.min.css to woff2 only" >&2
    exit 1
fi
cp "$pkg/LICENSE" "$dest/"

pkg="$(fetch apexcharts "$APEXCHARTS_VERSION")"
dest="$VENDOR_DIR/apexcharts-$APEXCHARTS_VERSION"
mkdir -p "$dest"
cp "$pkg/dist/apexcharts.min.js" "$pkg/LICENSE" "$dest/"

pkg="$(fetch sortablejs "$SORTABLEJS_VERSION")"
dest="$VENDOR_DIR/sortablejs-$SORTABLEJS_VERSION"
mkdir -p "$dest"
cp "$pkg/Sortable.min.js" "$pkg/LICENSE" "$dest/"

pkg="$(fetch vanilla-calendar-pro "$VANILLA_CALENDAR_VERSION")"
dest="$VENDOR_DIR/vanilla-calendar-pro-$VANILLA_CALENDAR_VERSION"
mkdir -p "$dest"
cp "$pkg/index.js" "$pkg/LICENSE" "$dest/"

# Source map comments point at files we do not ship: drop them so devtools
# does not log a 404 for each library.
find "$VENDOR_DIR" \( -name "*.min.js" -o -name "*.min.css" \) -exec \
    sed -i -E -e 's#/\*[#@] sourceMappingURL=[^*]*\*/##' -e 's#^//[#@] sourceMappingURL=.*$##' {} +

echo "Vendored libraries in $VENDOR_DIR:"
(cd "$VENDOR_DIR" && find . -type f | sort)
