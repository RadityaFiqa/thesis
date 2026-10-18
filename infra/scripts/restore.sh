#!/usr/bin/env bash
# Restore a backup made by backup.sh (PRD INF-11). DESTRUCTIVE for the
# current state: it replaces volume contents and the database with the backup.
#   sudo ./scripts/restore.sh /var/backups/thesis/<timestamp>
# Asks for confirmation. Run from the deploy folder that matches the backup
# (or first extract config.tar.gz from the backup to get the same .env/certs).
set -Eeuo pipefail
SRC="${1:?usage: restore.sh <backup-dir>}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NC_DIR="$DEPLOY_DIR/nextcloud"; SIEM_DIR="$DEPLOY_DIR/siem"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
ncc()   { (cd "$NC_DIR" && docker compose "$@"); }
siemc() { (cd "$SIEM_DIR" && docker compose "$@"); }

( cd "$SRC" && sha256sum -c --quiet SHA256SUMS ) || { echo "checksum mismatch in $SRC"; exit 1; }
echo "This will REPLACE current Nextcloud files, database, logs, agent identity and"
echo "Wazuh state with the backup in $SRC."
read -r -p "Type RESTORE to continue: " ans; [[ "$ans" == "RESTORE" ]] || { echo aborted; exit 1; }

ncc stop; siemc stop

vol_restore() {  # vol_restore <volume>
  local f="$SRC/vol-$1.tar.gz"; [[ -f "$f" ]] || { echo "  (no $f, skipping)"; return; }
  docker volume create "$1" >/dev/null
  docker run --rm -v "$1":/v -v "$SRC":/in:ro busybox:1.37.0 sh -c "find /v -mindepth 1 -delete && tar xzf /in/vol-$1.tar.gz -C /v"
  echo "  restored volume $1"
}
for f in "$SRC"/vol-*.tar.gz; do v=$(basename "$f" .tar.gz); vol_restore "${v#vol-}"; done

# Database: recreate empty, then load the dump
ncc up -d db
for i in $(seq 1 30); do ncc exec -T db pg_isready -q && break; sleep 2; done
U=$(env_get "$NC_DIR/.env" POSTGRES_USER); DB=$(env_get "$NC_DIR/.env" POSTGRES_DB)
ncc exec -T db psql -q -U "$U" -d postgres -c "DROP DATABASE IF EXISTS \"$DB\";" -c "CREATE DATABASE \"$DB\" OWNER \"$U\";"
gunzip -c "$SRC/nextcloud-db.sql.gz" | ncc exec -T db psql -q -U "$U" -d "$DB" >/dev/null
echo "  database restored"

siemc up -d; ncc up -d
echo "Waiting 60s, then turning maintenance mode off and scanning files"
sleep 60
ncc exec -T -u www-data app php occ maintenance:mode --off || true
ncc exec -T -u www-data app php occ files:scan --all >/dev/null || true
echo "Restore complete. Run: sudo ./scripts/verify-phase1.sh"
