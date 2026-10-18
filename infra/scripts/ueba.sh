#!/usr/bin/env bash
# Run the ueba CLI on the VPS from this git checkout, against the local indexer.
#   sudo ./scripts/ueba.sh normalize --indexer --since 2026-10-18T10:00Z --out ../data/events.jsonl \
#        --geoip ../data/geoip/GeoLite2-City.mmdb      (copied there by setup.sh)
#   sudo ./scripts/ueba.sh trace --manifest reports/<sample>/manifest.jsonl --events ../data/events.jsonl
# The indexer password is read from siem/.env at run time and never written elsewhere.
# The package needs only the Python standard library (python3 >= 3.11).
set -Eeuo pipefail
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(dirname "$DEPLOY_DIR")"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
export UEBA_INDEXER_URL="https://127.0.0.1:9200"
export UEBA_INDEXER_USER="admin"
export UEBA_INDEXER_PASSWORD="$(env_get "$DEPLOY_DIR/siem/.env" INDEXER_PASSWORD)"
export UEBA_INDEXER_CA="$DEPLOY_DIR/siem/config/wazuh_indexer_ssl_certs/root-ca.pem"
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$REPO_DIR/data"
exec python3 -m ueba.entrypoints.cli "$@"
