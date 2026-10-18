#!/usr/bin/env bash
# Phase 1 verification (PRD section 10). Prints PASS / FAIL / WARN / SKIP per
# check and saves a report (no secrets) under reports/.
#
#   sudo ./scripts/verify-phase1.sh             # all checks
#   sudo ./scripts/verify-phase1.sh --recreate  # also recreate every container and
#                                               # prove data + agent identity survive (INF-04, INF-08)
#
# Read-only apart from: a test account "thesis-check", small test files in its
# Nextcloud home, and (with --recreate) container recreation. Never deletes volumes.
set -uo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NC_DIR="$DEPLOY_DIR/nextcloud"; SIEM_DIR="$DEPLOY_DIR/siem"
REPORT_DIR="$DEPLOY_DIR/reports"; mkdir -p "$REPORT_DIR"; chmod 700 "$REPORT_DIR"
TS=$(date -u +%Y%m%d-%H%M%S)
REPORT="$REPORT_DIR/phase1-$TS.txt"
RECREATE=0; [[ "${1:-}" == "--recreate" ]] && RECREATE=1

[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
exec > >(tee "$REPORT") 2>&1

P=0; F=0; W=0; S=0
pass() { P=$((P+1)); printf '  [PASS] %s\n' "$*"; }
fail() { F=$((F+1)); printf '  [FAIL] %s\n' "$*"; }
warn() { W=$((W+1)); printf '  [WARN] %s\n' "$*"; }
skip() { S=$((S+1)); printf '  [SKIP] %s\n' "$*"; }
section() { printf '\n== %s\n' "$*"; }

env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
ncc()   { (cd "$NC_DIR" && docker compose "$@"); }
siemc() { (cd "$SIEM_DIR" && docker compose "$@"); }
occ()   { ncc exec -T -u www-data app php occ "$@"; }

NCD=$(env_get "$NC_DIR/.env" NEXTCLOUD_DOMAIN)
WZD=$(env_get "$NC_DIR/.env" WAZUH_DOMAIN)
CADDY_IP=$(env_get "$NC_DIR/.env" CADDY_IP)
AGENT_NAME=$(env_get "$NC_DIR/.env" WAZUH_AGENT_NAME)
IPW=$(env_get "$SIEM_DIR/.env" INDEXER_PASSWORD)
BIND_IP=$(env_get "$SIEM_DIR/.env" HOST_BIND_IP)
DPORT=$(env_get "$SIEM_DIR/.env" DASHBOARD_PORT)

idx() { curl -sk -u "admin:$IPW" -H 'Content-Type: application/json' "https://127.0.0.1:9200$1" "${@:2}"; }

echo "Phase 1 verification report"
echo "Generated (UTC): $(date -u +%FT%TZ)   host: $(hostname)   mode: $([[ $RECREATE == 1 ]] && echo recreate || echo standard)"
echo "Nextcloud: $NCD   Wazuh: $WZD   bridge: $BIND_IP"

# ------------------------------------------------------------------ INF-12
section "Versions (INF-12)"
echo "  docker: $(docker --version | cut -d' ' -f3 | tr -d ,)   compose: $(docker compose version --short)"
echo "  kernel: $(uname -r)   os: $(. /etc/os-release; echo "$PRETTY_NAME")"
echo "  vm.max_map_count: $(sysctl -n vm.max_map_count)"
for d in "$NC_DIR" "$SIEM_DIR"; do
  (cd "$d" && docker compose config --images 2>/dev/null | sort -u | sed 's/^/  image: /')
done

# ------------------------------------------------------------------ INF-01
section "Compose projects (INF-01)"
for d in "$NC_DIR" "$SIEM_DIR"; do
  if (cd "$d" && docker compose config -q 2>/dev/null); then pass "$(basename "$d")/docker-compose.yml validates"
  else fail "$(basename "$d")/docker-compose.yml does not validate"; fi
done
proj_nets() {
  docker ps -q --filter "label=com.docker.compose.project=$1" | xargs -r docker inspect \
    -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' | sed '/^$/d' | sort -u
}
NC_NETS=$(proj_nets nextcloud); SIEM_NETS=$(proj_nets siem)
SHARED=$(comm -12 <(echo "$NC_NETS") <(echo "$SIEM_NETS"))
if [[ -n "$NC_NETS" && -n "$SIEM_NETS" && -z "$SHARED" ]]; then
  pass "no shared Docker network (nextcloud: $(echo $NC_NETS); siem: $(echo $SIEM_NETS))"
else fail "shared or missing networks (shared: '${SHARED}')"; fi

# ------------------------------------------------------------------ INF-02 / INF-05
check_services() {   # check_services <label> <compose-fn> <services...>
  local label="$1" fn="$2"; shift 2
  local lines; lines=$($fn ps --format '{{.Service}}|{{.State}}|{{.Health}}' 2>/dev/null)
  local s line state health
  for s in "$@"; do
    line=$(grep -E "^${s//./\\.}\|" <<<"$lines" | head -1)
    state=$(cut -d'|' -f2 <<<"$line"); health=$(cut -d'|' -f3 <<<"$line")
    if [[ "$state" == "running" && "$health" != "unhealthy" && "$health" != "starting" ]]; then
      pass "$label/$s running${health:+ ($health)}"
    else fail "$label/$s state='${state:-missing}' health='${health:-n/a}'"; fi
  done
}
section "Services (INF-02, INF-05)"
check_services nextcloud ncc db redis app cron caddy wazuh-agent
check_services siem siemc wazuh.manager wazuh.indexer wazuh.dashboard

# ------------------------------------------------------------------ exposure
section "Published endpoints (connectivity requirements)"
LISTEN=$(ss -tlnH | awk '{print $4}')
chk_bind() {  # chk_bind <port> <expected-ip>
  local got; got=$(grep -E ":$1\$" <<<"$LISTEN" | sed -E 's/:[0-9]+$//' | tr -d '[]' | sort -u | tr '\n' ' ')
  if [[ "$got" == "$2 " ]]; then pass "port $1 bound only to $2"
  elif [[ -z "$got" ]]; then fail "port $1 not listening"
  else fail "port $1 bound to: $got (expected $2 only)"; fi
}
chk_bind 1514 "$BIND_IP"; chk_bind 1515 "$BIND_IP"; chk_bind "$DPORT" "$BIND_IP"; chk_bind 9200 127.0.0.1
for p in 5432 6379 55000; do
  if grep -qE ":$p\$" <<<"$LISTEN"; then fail "port $p is published on the host"; else pass "port $p not published on the host"; fi
done

# ------------------------------------------------------------------ INF-03
section "HTTPS and proxy settings (INF-03)"
PUB_CODE=$(curl -4 -s -o /tmp/thesis-status.json -w '%{http_code}' --max-time 20 "https://$NCD/status.php")
if [[ "$PUB_CODE" == "200" ]] && jq -e '.installed == true' /tmp/thesis-status.json >/dev/null 2>&1; then
  pass "https://$NCD/status.php -> 200, installed, version $(jq -r .versionstring /tmp/thesis-status.json)"
  CURL=(curl -4 -s --max-time 60); BASE="https://$NCD"; VIA_CF=1
  if curl -4 -sI --max-time 20 "https://$NCD/status.php" | grep -i '^cf-ray:' >/dev/null; then pass "served through Cloudflare (cf-ray header present)"; fi
else
  fail "https://$NCD via public DNS returned HTTP '${PUB_CODE}' (check Cloudflare SSL/TLS mode = Full, and ports 80/443 in the provider firewall)"
  CURL=(curl -4 -s -k --max-time 60 --resolve "$NCD:443:127.0.0.1"); BASE="https://$NCD"; VIA_CF=0
  ORIG=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/status.php")
  [[ "$ORIG" == "200" ]] && warn "origin answers directly (HTTP 200); remaining checks use the origin path" \
                        || fail "origin also failing (HTTP '$ORIG'); see: cd nextcloud && docker compose logs caddy app"
fi
chk_sys() {  # chk_sys <key> <expected>
  local v; v=$(occ config:system:get "$1" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
  [[ "$v" == "$2" ]] && pass "config $1 = $v" || fail "config $1 = '$v' (expected '$2')"
}
chk_sys overwriteprotocol https
chk_sys overwritehost "$NCD"
chk_sys trusted_proxies "$CADDY_IP"
chk_sys forwarded_for_headers HTTP_X_FORWARDED_FOR
TD=$(occ config:system:get trusted_domains 2>/dev/null | tr '\n' ' ')
grep -qw "$NCD" <<<"$TD" && pass "trusted_domains includes $NCD" || fail "trusted_domains = '$TD'"

# ------------------------------------------------------------------ INF-09 / INF-10
section "Logging and cron configuration (INF-09, INF-10)"
chk_sys log_type file
chk_sys logfile /var/log/nextcloud/nextcloud.log
chk_sys logfile_audit /var/log/nextcloud/audit.log
occ app:list --enabled 2>/dev/null | grep 'admin_audit' >/dev/null && pass "admin_audit app enabled" || fail "admin_audit app not enabled"
MODE=$(occ config:app:get core backgroundjobs_mode 2>/dev/null)
[[ "$MODE" == "cron" ]] && pass "background jobs mode = cron" || fail "background jobs mode = '$MODE'"
LAST=$(occ config:app:get core lastcron 2>/dev/null || echo 0); NOW=$(date +%s)
if [[ "$LAST" =~ ^[0-9]+$ ]] && (( LAST > 0 && NOW - LAST < 900 )); then
  pass "cron ran $(( NOW - LAST ))s ago"
else warn "cron has not run in the last 15 min (it runs every 5 min; re-run this script in a few minutes)"; fi

# ------------------------------------------------------------------ test account + transfer
section "Test account and file transfer (INF-02)"
CHECK_USER=thesis-check
CRED="$REPORT_DIR/.thesis-check.pass"
if [[ ! -s "$CRED" ]]; then
  python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(24)))' > "$CRED"
  chmod 600 "$CRED"
fi
CPW=$(cat "$CRED")
if occ user:info "$CHECK_USER" >/dev/null 2>&1; then
  pass "test account $CHECK_USER exists"
else
  if ncc exec -T -u www-data -e OC_PASS="$CPW" app php occ user:add --password-from-env --display-name "Phase 1 check" "$CHECK_USER" >/dev/null 2>&1
  then pass "test account $CHECK_USER created"; else fail "could not create $CHECK_USER"; fi
fi
DAV="$BASE/remote.php/dav/files/$CHECK_USER"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
FILE="phase1-$TS.txt"
printf 'Phase 1 verification %s %s\n' "$TS" "$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')" > "$TMP/$FILE"
UP=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -u "$CHECK_USER:$CPW" -T "$TMP/$FILE" "$DAV/$FILE")
[[ "$UP" == "201" || "$UP" == "204" ]] && pass "upload $FILE -> HTTP $UP" || fail "upload -> HTTP '$UP'"
"${CURL[@]}" -u "$CHECK_USER:$CPW" -o "$TMP/down.txt" "$DAV/$FILE"
if cmp -s "$TMP/$FILE" "$TMP/down.txt"; then pass "download matches upload (sha256 $(sha256sum "$TMP/$FILE" | cut -c1-16)...)"
else fail "downloaded file differs from upload"; fi

# Persistence marker: created once, checked on every run and after --recreate
MARK=persistence-marker.txt; MARK_SHA="$REPORT_DIR/.marker.sha256"
if [[ ! -s "$MARK_SHA" ]]; then
  printf 'persistence marker created %s\n' "$TS" > "$TMP/$MARK"
  "${CURL[@]}" -o /dev/null -u "$CHECK_USER:$CPW" -T "$TMP/$MARK" "$DAV/$MARK"
  sha256sum "$TMP/$MARK" | cut -d' ' -f1 > "$MARK_SHA"
fi
marker_ok() {
  "${CURL[@]}" -u "$CHECK_USER:$CPW" -o "$TMP/mark.dl" "$DAV/$MARK" && [[ "$(sha256sum "$TMP/mark.dl" | cut -d' ' -f1)" == "$(cat "$MARK_SHA")" ]]
}
marker_ok && pass "persistence marker present and intact" || fail "persistence marker missing or changed"

# ------------------------------------------------------------------ logs
section "Persistent logs and agent mounts (INF-06, INF-09)"
sleep 3
for f in /var/log/nextcloud/audit.log /var/log/nextcloud/nextcloud.log /var/log/caddy/access.log; do
  if ncc exec -T wazuh-agent test -s "$f"; then pass "agent can read $f ($(ncc exec -T wazuh-agent wc -l "$f" 2>/dev/null | awk '{print $1}') lines)"
  else fail "agent cannot read $f (missing or empty)"; fi
done
if ncc exec -T wazuh-agent sh -c 'touch /var/log/nextcloud/.rw-test' 2>/dev/null; then
  fail "agent log mount is writable (should be read-only)"
else pass "agent log mounts are read-only"; fi
AUDIT_LINE=$(ncc exec -T wazuh-agent grep -F "$FILE" /var/log/nextcloud/audit.log 2>/dev/null | tail -1)
[[ -n "$AUDIT_LINE" ]] && pass "audit log recorded the test upload: $(jq -r .message <<<"$AUDIT_LINE" 2>/dev/null | cut -c1-80)" \
                       || fail "test upload not found in audit.log"

# ------------------------------------------------------------------ CTX-03 (early check)
section "Client IP preservation (CTX-03, early check)"
if [[ "$VIA_CF" == "1" ]]; then
  MYIP=$(curl -4 -s --max-time 10 https://www.cloudflare.com/cdn-cgi/trace | awk -F= '$1=="ip"{print $2}')
  GOT=$(jq -r '.remoteAddr // empty' <<<"$AUDIT_LINE" 2>/dev/null)
  [[ -n "$MYIP" && "$GOT" == "$MYIP" ]] && pass "Nextcloud logged the real client IP ($GOT) through Cloudflare + proxy" \
                                          || fail "Nextcloud logged '$GOT', expected client IP '$MYIP'"
else skip "real-client-IP check needs the Cloudflare path"; fi
# Spoofing attempt that bypasses Cloudflare: forged headers must be ignored
SPOOF=203.0.113.66; SFILE="spoofcheck-$TS.txt"; echo spoof > "$TMP/$SFILE"
curl -4 -s -k --max-time 30 --resolve "$NCD:443:127.0.0.1" -H "CF-Connecting-IP: $SPOOF" -H "X-Forwarded-For: $SPOOF" \
  -o /dev/null -u "$CHECK_USER:$CPW" -T "$TMP/$SFILE" "https://$NCD/remote.php/dav/files/$CHECK_USER/$SFILE"
sleep 2
SGOT=$(ncc exec -T wazuh-agent grep -F "$SFILE" /var/log/nextcloud/audit.log 2>/dev/null | tail -1 | jq -r '.remoteAddr // empty' 2>/dev/null)
if [[ -z "$SGOT" ]]; then warn "spoof test request not found in audit.log"
elif [[ "$SGOT" == "$SPOOF" ]]; then fail "forged client IP was accepted ($SPOOF)"
else pass "forged CF-Connecting-IP/X-Forwarded-For ignored (logged $SGOT, not $SPOOF)"; fi

# ------------------------------------------------------------------ INF-07 / INF-08
section "Agent enrollment and connection (INF-07, INF-08)"
ADDR=$(ncc exec -T wazuh-agent sed -n 's:.*<address>\(.*\)</address>.*:\1:p' /var/ossec/etc/ossec.conf 2>/dev/null | head -1)
case "$ADDR" in
  localhost|127.*|wazuh.manager|"") fail "agent manager address is '$ADDR' (must be a host endpoint)";;
  *) pass "agent manager address = $ADDR (resolves to host $(ncc exec -T wazuh-agent getent hosts "$ADDR" | awk '{print $1}'))";;
esac
for p in 1514 1515; do
  if ncc exec -T wazuh-agent bash -c "timeout 5 bash -c '</dev/tcp/$ADDR/$p'" 2>/dev/null; then pass "agent container reaches $ADDR:$p"
  else fail "agent container cannot reach $ADDR:$p"; fi
done
agent_list() { siemc exec -T wazuh.manager /var/ossec/bin/agent_control -l 2>/dev/null; }
AGENT_ID=$(ncc exec -T wazuh-agent awk '{print $1; exit}' /var/ossec/etc/client.keys 2>/dev/null)
NAMED=$(agent_list | grep -c "Name: $AGENT_NAME,")
if agent_list | grep "Name: $AGENT_NAME," | grep 'Active' >/dev/null; then pass "agent '$AGENT_NAME' (ID $AGENT_ID) is Active on the manager"
else fail "agent '$AGENT_NAME' not Active: $(agent_list | grep "Name: $AGENT_NAME," | head -1)"; fi
[[ "$NAMED" == "1" ]] && pass "exactly one agent named $AGENT_NAME" || warn "$NAMED agents named $AGENT_NAME"

# ------------------------------------------------------------------ INF-05 SIEM
section "SIEM health and search (INF-05)"
HEALTH=$(idx /_cluster/health | jq -r .status 2>/dev/null)
[[ "$HEALTH" == "green" || "$HEALTH" == "yellow" ]] && pass "indexer cluster health = $HEALTH" || fail "indexer health = '$HEALTH'"
RUNNING=$(siemc exec -T wazuh.manager /var/ossec/bin/wazuh-control status 2>/dev/null | grep -c 'is running')
(( RUNNING >= 8 )) && pass "manager: $RUNNING daemons running" || fail "manager: only $RUNNING daemons running"
DC=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$BIND_IP:$DPORT/")
[[ "$DC" =~ ^(200|302)$ ]] && pass "dashboard answers on $BIND_IP:$DPORT (HTTP $DC)" || fail "dashboard on $BIND_IP:$DPORT -> HTTP '$DC'"
WC=$(curl -4 -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$WZD/")
[[ "$WC" =~ ^(200|302)$ ]] && pass "https://$WZD reachable (HTTP $WC)" || warn "https://$WZD -> HTTP '$WC'"

search_count() {  # search_count <query_string>
  idx "/wazuh-alerts-*/_count" -d "$(jq -nc --arg q "$1" '{query:{query_string:{query:$q}}}')" | jq -r '.count // 0'
}
printf '  waiting for the test upload to be indexed'
FOUND=0
for i in $(seq 1 36); do
  if (( $(search_count "rule.id:100100 AND full_log:\"$FILE\"") > 0 )); then FOUND=1; break; fi
  printf '.'; sleep 5
done; echo
(( FOUND )) && pass "test upload is searchable in wazuh-alerts-* (rule 100100)" \
            || fail "test upload not found in the index after 3 min (check: cd siem && docker compose logs wazuh.manager | tail)"
for r in 100100 100101 100102; do
  echo "  indexed events, rule $r: $(search_count "rule.id:$r")"
done

# ------------------------------------------------------------------ INF-04 / INF-08 recreate
if [[ "$RECREATE" == "1" ]]; then
  section "Persistence across container recreation (INF-04, INF-08)"
  BEFORE_COUNT=$(search_count "rule.groups:nextcloud")
  echo "  before: agent ID $AGENT_ID, nextcloud events indexed $BEFORE_COUNT"
  siemc up -d --force-recreate >/dev/null 2>&1
  printf '  waiting for the indexer'; for i in $(seq 1 60); do [[ "$(idx /_cluster/health | jq -r .status 2>/dev/null)" =~ green|yellow ]] && break; printf '.'; sleep 5; done; echo
  ncc up -d --force-recreate >/dev/null 2>&1
  printf '  waiting for Nextcloud'; for i in $(seq 1 120); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$(ncc ps -q app)" 2>/dev/null)" == healthy ]] && break; printf '.'; sleep 5; done; echo
  sleep 30
  marker_ok && pass "file survives recreation" || fail "file lost after recreation"
  occ user:info "$CHECK_USER" >/dev/null 2>&1 && pass "account survives recreation" || fail "account lost after recreation"
  AFTER_COUNT=$(search_count "rule.groups:nextcloud")
  (( AFTER_COUNT >= BEFORE_COUNT && BEFORE_COUNT > 0 )) && pass "indexed events survive ($BEFORE_COUNT -> $AFTER_COUNT)" \
                                                       || fail "indexed events $BEFORE_COUNT -> $AFTER_COUNT"
  NEW_ID=$(ncc exec -T wazuh-agent awk '{print $1; exit}' /var/ossec/etc/client.keys 2>/dev/null)
  [[ -n "$NEW_ID" && "$NEW_ID" == "$AGENT_ID" ]] && pass "agent identity kept (ID $NEW_ID)" || fail "agent ID changed: $AGENT_ID -> $NEW_ID"
  for i in $(seq 1 12); do agent_list | grep "Name: $AGENT_NAME," | grep Active >/dev/null && break; sleep 5; done
  agent_list | grep "Name: $AGENT_NAME," | grep Active >/dev/null && pass "agent reconnected without manual registration" || fail "agent not Active after recreation"
  [[ "$(agent_list | grep -c "Name: $AGENT_NAME,")" == "1" ]] && pass "no duplicate agent identity" || fail "duplicate agent identities"
else
  section "Persistence across container recreation (INF-04, INF-08)"
  skip "run with --recreate to test (recreates all containers, keeps volumes)"
fi

section "Not covered by this script"
echo "  - Backup/restore (INF-11): run scripts/backup.sh; a restore drill is documented in README.md"
echo "  - Provider firewall / security group settings (outside the VPS)"

printf '\nSummary: %d pass, %d fail, %d warn, %d skip\nReport: %s\n' "$P" "$F" "$W" "$S" "$REPORT"
(( F == 0 ))
