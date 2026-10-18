#!/usr/bin/env bash
# Backup of both projects (PRD INF-11). Non-destructive: it only reads.
#   sudo ./scripts/backup.sh [target-dir]      (default: /var/backups/thesis)
#
# Contents of backups/<timestamp>/:
#   nextcloud-db.sql.gz       PostgreSQL dump (consistent, taken in maintenance mode)
#   vol-<name>.tar.gz         Docker volumes (Nextcloud files/config, logs, agent identity,
#                             Wazuh manager state, indexer data, Caddy certificates)
#   config.tar.gz             this deploy folder incl. .env and certificates (SECRETS!)
# Nextcloud is in maintenance mode for the duration; the SIEM indexer is
# stopped briefly so its data files are consistent.
set -Eeuo pipefail
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NC_DIR="$DEPLOY_DIR/nextcloud"; SIEM_DIR="$DEPLOY_DIR/siem"
TARGET="${1:-/var/backups/thesis}/$(date -u +%Y%m%d-%H%M%S)"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
ncc()   { (cd "$NC_DIR" && docker compose "$@"); }
siemc() { (cd "$SIEM_DIR" && docker compose "$@"); }

mkdir -p "$TARGET"; chmod 700 "$TARGET"
echo "Backing up to $TARGET"

maint_off() { ncc exec -T -u www-data app php occ maintenance:mode --off >/dev/null 2>&1 || true; }
trap 'maint_off; siemc start wazuh.indexer >/dev/null 2>&1 || true' EXIT

ncc exec -T -u www-data app php occ maintenance:mode --on
ncc exec -T db pg_dump -U "$(env_get "$NC_DIR/.env" POSTGRES_USER)" "$(env_get "$NC_DIR/.env" POSTGRES_DB)" | gzip > "$TARGET/nextcloud-db.sql.gz"
echo "  database dumped"

vol_tar() {  # vol_tar <volume>
  docker run --rm -v "$1":/v:ro -v "$TARGET":/out busybox:1.37.0 tar czf "/out/vol-$1.tar.gz" -C /v .
  echo "  volume $1"
}
for v in nextcloud_nc_html nextcloud_nc_data nextcloud_nc_logs nextcloud_caddy_data nextcloud_caddy_logs nextcloud_agent_etc; do
  vol_tar "$v"
done
maint_off; echo "  Nextcloud back online"

siemc stop wazuh.indexer >/dev/null
for v in siem_wazuh-indexer-data siem_wazuh_etc siem_wazuh_api_configuration siem_wazuh_queue siem_wazuh_logs siem_filebeat_var; do
  vol_tar "$v"
done
siemc start wazuh.indexer >/dev/null; echo "  indexer restarted"

tar czf "$TARGET/config.tar.gz" -C "$(dirname "$DEPLOY_DIR")" --exclude='reports' "$(basename "$DEPLOY_DIR")"
chmod 600 "$TARGET"/*
( cd "$TARGET" && sha256sum ./* > SHA256SUMS )
echo "Done: $(du -sh "$TARGET" | cut -f1) in $TARGET"
echo "config.tar.gz contains passwords and private keys; copy it off the VPS securely."
