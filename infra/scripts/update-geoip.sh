#!/usr/bin/env bash
# Download a DB-IP City Lite database (CTX-01) into data/geoip/.
#   sudo ./scripts/update-geoip.sh            this month's edition (UTC)
#   sudo ./scripts/update-geoip.sh 2026-10    a specific month, to reproduce a run
#
# DB-IP City Lite: https://db-ip.com/db/download/ip-to-city-lite, monthly,
# licence CC BY 4.0 (attribution: "IP Geolocation by DB-IP", https://db-ip.com).
# Each month is kept under its own name; the normalizer is pointed at one file
# explicitly (--geoip), and every event records the database it used.
set -Eeuo pipefail
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(dirname "$DEPLOY_DIR")"
DEST="$REPO_DIR/data/geoip"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

MONTH="${1:-$(date -u +%Y-%m)}"
[[ "$MONTH" =~ ^[0-9]{4}-(0[1-9]|1[0-2])$ ]] || { echo "month must look like 2026-10"; exit 1; }
NAME="dbip-city-lite-$MONTH.mmdb"
URL="https://download.db-ip.com/free/$NAME.gz"

if [[ -f "$DEST/$NAME" ]]; then echo "already present: data/geoip/$NAME"; exit 0; fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "downloading $URL"
EXPECTED=$( { curl -sfI "$URL" || true; } | awk 'tolower($1)=="content-length:" {print $2}' | tr -d '\r')
[[ -n "$EXPECTED" ]] || { echo "not available: $URL (new editions appear on the 1st of each month)"; exit 1; }
curl -sf -o "$TMP/$NAME.gz" "$URL"
GOT=$(stat -c %s "$TMP/$NAME.gz")
[[ "$GOT" == "$EXPECTED" ]] || { echo "size mismatch: got $GOT bytes, expected $EXPECTED"; exit 1; }
gzip -t "$TMP/$NAME.gz"
gunzip "$TMP/$NAME.gz"

# Check it is the expected kind of database before keeping it
PROVIDER=$(PYTHONPATH="$REPO_DIR/src" python3 -c '
import sys
from pathlib import Path
from ueba.adapters.mmdb_geo import MmdbGeoLookup
print(MmdbGeoLookup(Path(sys.argv[1])).provider)' "$TMP/$NAME")
[[ "$PROVIDER" == DBIP-City-Lite* ]] || { echo "unexpected database: $PROVIDER"; exit 1; }

mkdir -p "$DEST"
install -m 644 "$TMP/$NAME" "$DEST/$NAME"
echo "saved data/geoip/$NAME ($PROVIDER, sha256 $(sha256sum "$DEST/$NAME" | cut -c1-16)...)"
