#!/usr/bin/env bash
# Phase 2 sampling (LOG-01, LOG-03): perform each user action once through the
# public HTTPS path, then collect the log lines it produced in all three sources.
#   sudo ./scripts/phase2-sample-actions.sh
#
# Uses a synthetic account "p2-sampler" (created if missing; password kept in
# .p2-sampler.pass, root-only, git-ignored). Output, no secrets:
#   reports/phase2-samples-<UTC time>/manifest.jsonl   what was done (ground truth)
#   reports/phase2-samples-<UTC time>/{audit,app,access}.jsonl   what was logged
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NC_DIR="$DEPLOY_DIR/nextcloud"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }

env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
ncc() { (cd "$NC_DIR" && docker compose "$@"); }
occ() { ncc exec -T -u www-data "${OCC_ENV[@]}" app php occ "$@"; }
OCC_ENV=()

NCD=$(env_get "$NC_DIR/.env" NEXTCLOUD_DOMAIN)
BASE="https://$NCD"
USER_ID=p2-sampler
PASS_FILE="$DEPLOY_DIR/.p2-sampler.pass"
OUT="$DEPLOY_DIR/reports/phase2-samples-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"; chmod 700 "$DEPLOY_DIR/reports" "$OUT"
JAR=$(mktemp); trap 'rm -f "$JAR"' EXIT

# ---------------------------------------------------------------- account
if [[ ! -f "$PASS_FILE" ]]; then
  python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(24)))' > "$PASS_FILE"
  chmod 600 "$PASS_FILE"
fi
PASS=$(cat "$PASS_FILE")
if ! occ user:info "$USER_ID" >/dev/null 2>&1; then
  OCC_ENV=(-e "OC_PASS=$PASS")
  occ user:add --password-from-env --display-name "Phase 2 sampler" "$USER_ID" >/dev/null
  OCC_ENV=()
  echo "created synthetic user $USER_ID"
fi

# ---------------------------------------------------------------- actions
# step <name> <expected_action> <expected_outcome> <curl args...>
# Records one manifest line with the request id the proxy returned.
step() {
  local name=$1 action=$2 expect=$3; shift 3
  local start end hdr code rid
  hdr=$(mktemp)
  start=$(date -u +%FT%T.%3NZ)
  code=$(curl -4 -s -o /dev/null -D "$hdr" -w '%{http_code}' -b "$JAR" -c "$JAR" \
              -A "thesis-phase2-sampler/1.0" "$@" || echo 000)
  end=$(date -u +%FT%T.%3NZ)
  rid=$(awk 'tolower($1)=="x-request-id:" {print $2}' "$hdr" | tr -d '\r' | tail -1)
  rm -f "$hdr"
  jq -cn --arg step "$name" --arg action "$action" --arg expect "$expect" --arg user "$USER_ID" \
        --arg start "$start" --arg end "$end" --argjson code "$code" --arg rid "$rid" \
        '{step:$step, expected_action:$action, expected_outcome:$expect, user:$user,
          start:$start, end:$end, http_status:$code, request_id:$rid}' >> "$OUT/manifest.jsonl"
  printf '  %-22s HTTP %s  request_id=%s\n' "$name" "$code" "${rid:-none}"
  sleep 1
}

DAV="$BASE/remote.php/dav/files/$USER_ID"
DIR="phase2-$(date -u +%H%M%S)"
FILE="$DIR/sample.txt"
AUTH=(-u "$USER_ID:$PASS")
BAD=(-u "$USER_ID:wrong-$RANDOM")
OCS=(-H "OCS-APIRequest: true" -H "Accept: application/json")
T0=$(date -u +%FT%TZ)

echo "Sampling actions as $USER_ID against $BASE"
# Web login like a browser: session cookies + CSRF token, and an Origin header,
# which Nextcloud's login CSRF check requires. Without it the login is rejected.
WEB=(-H "Origin: $BASE" -H "Referer: $BASE/login")
token() { curl -4 -s -b "$JAR" -c "$JAR" "$BASE/csrftoken" | jq -r .token; }
RT=$(token)
step login_web_failed  login  failure "${WEB[@]}" -X POST --data-urlencode "user=$USER_ID" --data-urlencode "password=wrong-$RANDOM" --data-urlencode "requesttoken=$RT" "$BASE/login"
RT=$(token)
step login_web         login  success "${WEB[@]}" -X POST --data-urlencode "user=$USER_ID" --data-urlencode "password=$PASS" --data-urlencode "requesttoken=$RT" "$BASE/login"
RT=$(token)
step logout_web        logout success "${WEB[@]}" "$BASE/logout?requesttoken=$(printf %s "$RT" | jq -sRr @uri)"
# WebDAV / API with basic auth (how sync clients and scripts work)
step dav_auth_failed   auth   failure "${BAD[@]}" -X PROPFIND -H "Depth: 0" "$DAV/"
step mkdir             mkdir  success "${AUTH[@]}" -X MKCOL "$DAV/$DIR"
head -c 4096 /dev/urandom | base64 > "$OUT/.payload"
step upload            upload success "${AUTH[@]}" -T "$OUT/.payload" "$DAV/$FILE"
rm -f "$OUT/.payload"
step list              access success "${AUTH[@]}" -X PROPFIND -H "Depth: 1" "$DAV/$DIR"
step download          download success "${AUTH[@]}" "$DAV/$FILE"
step download_missing  download failure "${AUTH[@]}" "$DAV/$DIR/does-not-exist.txt"
step rename            rename success "${AUTH[@]}" -X MOVE -H "Destination: $DAV/$DIR/renamed.txt" "$DAV/$FILE"
step share_link        share  success "${AUTH[@]}" "${OCS[@]}" -X POST -d "path=/$DIR/renamed.txt" -d "shareType=3" "$BASE/ocs/v2.php/apps/files_sharing/api/v1/shares"
step delete            delete success "${AUTH[@]}" -X DELETE "$DAV/$DIR/renamed.txt"
step delete_folder     delete success "${AUTH[@]}" -X DELETE "$DAV/$DIR"

# ---------------------------------------------------------------- logs
sleep 3
echo "Collecting log lines since $T0"
ncc exec -T app sh -c 'cat /var/log/nextcloud/audit.log' | jq -c --arg t0 "$T0" 'select(.time >= $t0)' > "$OUT/audit.jsonl" || true
ncc exec -T app sh -c 'cat /var/log/nextcloud/nextcloud.log' | jq -c --arg t0 "$T0" 'select(.time >= $t0)' > "$OUT/app.jsonl" || true
# Caddy logs epoch seconds in "ts"
T0_EPOCH=$(date -u -d "$T0" +%s)
ncc exec -T wazuh-agent cat /var/log/caddy/access.log | jq -c --argjson t0 "$T0_EPOCH" 'select(.ts >= $t0)' > "$OUT/access.jsonl" || true
chmod 600 "$OUT"/*

printf '\n  manifest %s lines, audit %s, app %s, access %s\n' \
  "$(wc -l < "$OUT/manifest.jsonl")" "$(wc -l < "$OUT/audit.jsonl")" "$(wc -l < "$OUT/app.jsonl")" "$(wc -l < "$OUT/access.jsonl")"
echo "  saved in $OUT"
