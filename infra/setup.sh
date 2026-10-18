#!/usr/bin/env bash
# Phase 1 setup for the Nextcloud UEBA research platform.
# Usage (on the VPS, from this folder):   sudo ./setup.sh
#
# Safe to re-run: it never deletes volumes, never overwrites an existing .env,
# secret, certificate or user file, and only starts/updates containers.
# Options (environment variables):
#   SKIP_UFW=1      don't touch the host firewall
#   SKIP_VERIFY=1   don't run the Phase 1 checks at the end
set -Eeuo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NC_DIR="$DEPLOY_DIR/nextcloud"
SIEM_DIR="$DEPLOY_DIR/siem"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m %s\n' "$*"; }
warn() { printf '    \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
trap 'die "setup failed at line $LINENO (command: $BASH_COMMAND)"' ERR

[[ $EUID -eq 0 ]] || die "run with sudo: sudo ./setup.sh"

# Files copied from Windows can lose the executable bit or gain CRLF endings
fix_files() {
  find "$DEPLOY_DIR" -type f \( -name '*.sh' -o -name '*.yml' -o -name '*.conf' -o -name '*.xml' \
       -o -name 'Caddyfile' -o -name '*.example' -o -name '*.template' \) -exec sed -i 's/\r$//' {} +
  find "$DEPLOY_DIR" -type f -name '*.sh' -exec chmod 0755 {} +
}

# ---------------------------------------------------------------- preflight
preflight() {
  log "Preflight"
  . /etc/os-release
  [[ "$ID" == "ubuntu" ]] || warn "tested on Ubuntu 24.04; found $PRETTY_NAME"
  local mem_mb; mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  (( mem_mb >= 7000 )) || warn "only ${mem_mb} MB RAM; Wazuh + Nextcloud want about 8 GB"
  local disk_gb; disk_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  (( disk_gb >= 30 )) || warn "only ${disk_gb} GB free disk"
  ok "$PRETTY_NAME, ${mem_mb} MB RAM, ${disk_gb} GB free"
}

# ---------------------------------------------------------------- host prep
install_docker() {
  log "Docker Engine + Compose plugin"
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    ok "already installed: $(docker --version)"
  else
    apt-get update -q
    apt-get install -yq ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ok "installed: $(docker --version)"
  fi

  # Container log rotation, so docker logs can't fill the disk
  if [[ ! -f /etc/docker/daemon.json ]]; then
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
EOF
    systemctl restart docker
    ok "container log rotation configured"
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true

  if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]] && ! id -nG "$SUDO_USER" | grep -w docker >/dev/null; then
    usermod -aG docker "$SUDO_USER"
    ok "added $SUDO_USER to the docker group (log out and back in to use docker without sudo)"
  fi
}

host_packages() {
  log "Helper packages"
  # python3-maxminddb: GeoIP lookups in the ueba normalizer (scripts/ueba.sh)
  apt-get install -yq python3 python3-bcrypt python3-maxminddb jq curl >/dev/null
  ok "python3-bcrypt, python3-maxminddb, jq, curl"
}

kernel_and_swap() {
  log "Kernel settings and swap"
  # Required by the Wazuh indexer (OpenSearch)
  cat > /etc/sysctl.d/99-thesis-wazuh.conf <<'EOF'
vm.max_map_count=262144
vm.swappiness=10
EOF
  sysctl -q --system
  ok "vm.max_map_count=$(sysctl -n vm.max_map_count)"

  if [[ -z "$(swapon --show --noheadings)" ]]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "4 GB swap file created"
  else
    ok "swap already present"
  fi
}

firewall() {
  log "Host firewall (ufw)"
  if [[ "${SKIP_UFW:-0}" == "1" ]]; then warn "skipped (SKIP_UFW=1)"; return; fi
  apt-get install -yq ufw >/dev/null
  # Keep every port sshd currently listens on open, so this can't lock you out
  # (Ubuntu 24.04 uses socket activation, so ask sshd for its configured ports too)
  local ssh_ports
  ssh_ports=$( { sshd -T 2>/dev/null | awk '$1=="port" {print $2}';
                 ss -tlnpH 2>/dev/null | awk '/sshd|ssh\.socket/ {n=split($4,a,":"); print a[n]}'; } | sort -u | tr '\n' ' ')
  [[ -n "${ssh_ports// /}" ]] || ssh_ports=22
  for p in $ssh_ports; do ufw allow "$p/tcp" comment 'ssh' >/dev/null; done
  ufw allow 80/tcp  comment 'http (ACME / redirect)' >/dev/null
  ufw allow 443/tcp comment 'https' >/dev/null
  ufw allow 443/udp comment 'https (HTTP/3)' >/dev/null
  # Containers -> SIEM ports on the host bridge (normally DNAT'd past ufw; this covers the userland-proxy path)
  local bip; bip=$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
  if [[ -n "$bip" ]]; then
    ufw allow from 172.16.0.0/12 to "$bip" port 1514,1515,5601 proto tcp comment 'containers -> wazuh (bridge only)' >/dev/null
  fi
  ufw --force enable >/dev/null
  ok "allowed ssh ($ssh_ports), 80, 443. Wazuh ports are bound to the Docker bridge only, not the public interface"
  warn "also open 80/tcp and 443/tcp in your VPS provider's security group / firewall panel"
}

# ---------------------------------------------------------------- secrets
gen_pw() { python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(int(__import__("sys").argv[1]))))' "$1"; }
# Wazuh API policy: upper, lower, digit and symbol; we use "." and "-" (shell/YAML/JSON-safe)
gen_api_pw() { python3 - <<'EOF'
import secrets, string
pool = string.ascii_letters + string.digits
core = [secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits), ".", "-"] + [secrets.choice(pool) for _ in range(19)]
secrets.SystemRandom().shuffle(core)
print("".join(core))
EOF
}
bcrypt_hash() { python3 -c 'import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(12)).decode().replace("$2b$","$2y$",1))' "$1"; }

env_get() { grep -E "^$2=" "$1" | tail -1 | cut -d= -f2-; }
env_set() { python3 - "$1" "$2" "$3" <<'EOF'
import sys, re
path, key, val = sys.argv[1:]
s = open(path).read()
s = re.sub(r'(?m)^' + re.escape(key) + r'=.*$', lambda m: key + '=' + val, s, count=1)
open(path, 'w').write(s)
EOF
}

make_env() {   # make_env <dir>: create .env from .env.example, filling CHANGE_ME values
  local dir="$1" f="$1/.env"
  if [[ -f "$f" ]]; then ok "$(basename "$dir")/.env exists, keeping it"; return; fi
  cp "$dir/.env.example" "$f"
  chmod 600 "$f"
  local key
  for key in $(grep -E '^[A-Z_]+=CHANGE_ME$' "$f" | cut -d= -f1); do
    if [[ "$key" == "API_PASSWORD" ]]; then env_set "$f" "$key" "$(gen_api_pw)"
    else env_set "$f" "$key" "$(gen_pw 32)"; fi
  done
  ok "created $(basename "$dir")/.env with random secrets"
}

secrets_and_config() {
  log "Secrets and generated configuration"
  make_env "$SIEM_DIR"
  make_env "$NC_DIR"

  # Host bridge address: SIEM publishes on it, agent and proxy reach it via host-gateway
  local bridge_ip
  bridge_ip=$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
  [[ -n "$bridge_ip" ]] || die "docker0 bridge not found; is Docker running?"
  if [[ "$(env_get "$SIEM_DIR/.env" HOST_BIND_IP)" != "$bridge_ip" ]]; then
    env_set "$SIEM_DIR/.env" HOST_BIND_IP "$bridge_ip"
    ok "HOST_BIND_IP set to $bridge_ip"
  fi
  local dport; dport=$(env_get "$SIEM_DIR/.env" DASHBOARD_PORT)
  env_set "$NC_DIR/.env" WAZUH_DASHBOARD_UPSTREAM "host.docker.internal:${dport}"

  # Enrollment password: one value shared by manager (authd.pass) and agent (.env)
  local reg; reg=$(env_get "$NC_DIR/.env" WAZUH_REGISTRATION_PASSWORD)
  local authd="$SIEM_DIR/config/wazuh_cluster/authd.pass"
  if [[ ! -f "$authd" ]]; then
    printf '%s\n' "$reg" > "$authd"; chmod 640 "$authd"
    ok "wrote enrollment password (siem/config/wazuh_cluster/authd.pass)"
  elif [[ "$(tr -d '\n' < "$authd")" != "$reg" ]]; then
    die "authd.pass differs from WAZUH_REGISTRATION_PASSWORD in nextcloud/.env; make them equal"
  fi

  local api; api=$(env_get "$SIEM_DIR/.env" API_PASSWORD)
  local wyml="$SIEM_DIR/config/wazuh_dashboard/wazuh.yml"
  if [[ ! -f "$wyml" ]]; then
    sed "s|__API_PASSWORD__|$api|" "$wyml.template" > "$wyml"
    ok "wrote dashboard API config (wazuh.yml)"
  fi

  local users="$SIEM_DIR/config/wazuh_indexer/internal_users.yml"
  if [[ ! -f "$users" ]]; then
    python3 - "$users.template" "$users" \
      "$(bcrypt_hash "$(env_get "$SIEM_DIR/.env" INDEXER_PASSWORD)")" \
      "$(bcrypt_hash "$(env_get "$SIEM_DIR/.env" DASHBOARD_PASSWORD)")" <<'EOF'
import sys, secrets, bcrypt
src, dst, admin_h, kib_h = sys.argv[1:]
s = open(src).read().replace("__ADMIN_HASH__", admin_h).replace("__KIBANASERVER_HASH__", kib_h)
while "__RANDOM_HASH__" in s:
    h = bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt(12)).decode().replace("$2b$", "$2y$", 1)
    s = s.replace("__RANDOM_HASH__", h, 1)
open(dst, "w").write(s)
EOF
    ok "wrote indexer users (internal_users.yml); demo users get random passwords"
  fi

  # The indexer and dashboard run as uid 1000 inside their containers, so these
  # bind-mounted files must be world-readable (the deploy folder itself sits in
  # your home directory, which other host users can't enter).
  local f
  for f in "$users" "$wyml"; do
    if [[ "$(stat -c %a "$f")" != "644" ]]; then
      chmod 644 "$f"; SIEM_RECREATE=1
      ok "made $(basename "$f") readable by the container user"
    fi
  done
}

# ---------------------------------------------------------------- SIEM
siem_certs() {
  log "Wazuh TLS certificates"
  local d="$SIEM_DIR/config/wazuh_indexer_ssl_certs"
  if [[ -f "$d/root-ca.pem" && -f "$d/wazuh.indexer.pem" && -f "$d/wazuh.manager.pem" && -f "$d/wazuh.dashboard.pem" ]]; then
    ok "certificates exist, keeping them"; return
  fi
  (cd "$SIEM_DIR" && docker compose -f generate-indexer-certs.yml run --rm generator)
  [[ -f "$d/root-ca-manager.pem" ]] || die "certificate generation did not produce root-ca-manager.pem"
  ok "certificates generated in siem/config/wazuh_indexer_ssl_certs"
}

indexer_auth_ok() {
  curl -sk -o /dev/null -w '%{http_code}' -u "admin:$(env_get "$SIEM_DIR/.env" INDEXER_PASSWORD)" \
    https://127.0.0.1:9200/_cluster/health 2>/dev/null | grep '^200$' >/dev/null
}

siem_up() {
  log "Starting SIEM project (manager, indexer, dashboard)"
  (cd "$SIEM_DIR" && docker compose config -q && docker compose up -d)
  if [[ "${SIEM_RECREATE:-0}" == "1" ]]; then
    (cd "$SIEM_DIR" && docker compose up -d --force-recreate wazuh.indexer wazuh.dashboard)
    ok "recreated indexer and dashboard to pick up the fixed files"
  fi
  printf '    waiting for the indexer'
  local i initialized_once=0
  for i in $(seq 1 72); do
    if indexer_auth_ok; then printf '\n'; ok "indexer is up and accepts the admin password"; return; fi
    # After ~2 minutes, if the security index still isn't initialized, initialize it once
    if (( i >= 24 && initialized_once == 0 )) && \
       curl -sk https://127.0.0.1:9200/ 2>/dev/null | grep -i 'not yet initialized\|not initialized' >/dev/null; then
      printf '\n'; warn "security index not initialized; running securityadmin"
      "$DEPLOY_DIR/scripts/apply-indexer-users.sh" || true
      initialized_once=1
    fi
    printf '.'; sleep 5
  done
  printf '\n'
  warn "indexer did not accept the admin password within 5 minutes"
  warn "if the indexer data volume predates this .env, apply users with: sudo ./scripts/apply-indexer-users.sh"
  die "indexer not ready; check: cd siem && docker compose logs wazuh.indexer | tail -50"
}

# A single-file bind mount pins the file's inode when the container is created.
# git pull, sed -i and most editors replace a file by renaming a new one into
# place, so the running container keeps seeing the OLD content, and docker
# compose up -d doesn't notice (the compose config is unchanged). Compare every
# bind-mounted file on the host with what the container sees, and recreate the
# services that are stale.
host_md5() { md5sum < "$1" | cut -d' ' -f1; }
ctr_md5()  { docker exec "$1" cat "$2" 2>/dev/null | md5sum | cut -d' ' -f1; }

recreate_stale_mounts() {   # recreate_stale_mounts <project dir>
  local dir="$1" ctr svc src dst stale=()
  for ctr in $(cd "$dir" && docker compose ps -q); do
    svc=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$ctr")
    while IFS=$'\t' read -r src dst; do
      [[ -f "$src" ]] || continue
      if [[ "$(host_md5 "$src")" != "$(ctr_md5 "$ctr" "$dst")" ]]; then
        warn "$svc sees an old copy of ${src#"$DEPLOY_DIR"/}"
        stale+=("$svc"); break
      fi
    done < <(docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\t"}}{{.Destination}}{{"\n"}}{{end}}{{end}}' "$ctr")
  done
  if (( ${#stale[@]} )); then
    (cd "$dir" && docker compose up -d --force-recreate "${stale[@]}")
    ok "recreated ${stale[*]} to pick up changed files"
  else
    ok "$(basename "$dir"): all mounted files are current"
  fi
}

# The manager copies /wazuh-config-mount into /var/ossec only when its container
# is created (on a plain restart its init script fails before the copy). And a
# rule file analysisd can't load stops the whole manager. So: if the rules on the
# host differ from the live ones, test them inside the running manager first
# (analysisd -t only reads files; the running daemon keeps its loaded rules),
# roll back on failure, and only then let the manager be recreated.
validate_manager_rules() {
  local host_rules="$SIEM_DIR/config/wazuh_cluster/local_rules.xml"
  local live; live=$(ctr_md5 siem-wazuh.manager-1 /var/ossec/etc/rules/local_rules.xml)
  if [[ "$(host_md5 "$host_rules")" == "$live" ]]; then ok "manager rules are current"; return; fi
  (cd "$SIEM_DIR" && docker compose cp "$host_rules" wazuh.manager:/tmp/candidate_rules.xml) >/dev/null
  local test_out
  if ! test_out=$(cd "$SIEM_DIR" && docker compose exec -T wazuh.manager sh -c '
        R=/var/ossec/etc/rules/local_rules.xml
        cp -p "$R" /tmp/local_rules.xml.bak
        cp /tmp/candidate_rules.xml "$R" && chown wazuh:wazuh "$R"
        if /var/ossec/bin/wazuh-analysisd -t >/tmp/rules-test.log 2>&1; then exit 0; fi
        cp -p /tmp/local_rules.xml.bak "$R"; grep -E "ERROR|CRITICAL" /tmp/rules-test.log | head -5; exit 1'); then
    printf '%s\n' "$test_out" >&2
    die "local_rules.xml does not load; the running manager was left untouched"
  fi
  ok "changed rules load cleanly (wazuh-analysisd -t)"
  # The live file now holds the new rules but the daemon still runs the old ones;
  # force the recreate even if the mount happens to be current.
  (cd "$SIEM_DIR" && docker compose up -d --force-recreate wazuh.manager)
  ok "recreated wazuh.manager to load the new rules"
}

wait_for_manager() {
  local i
  local status
  for i in $(seq 1 60); do
    # wazuh-control status exits 1 whenever any daemon is off, including ones that
    # are disabled on purpose (maild, agentlessd, ...), so check its output instead
    status=$(cd "$SIEM_DIR" && docker compose exec -T wazuh.manager /var/ossec/bin/wazuh-control status 2>/dev/null || true)
    if [[ "$status" == *"wazuh-analysisd is running"* ]]; then ok "manager is running"; return; fi
    sleep 3
  done
  die "wazuh-analysisd not running; check: cd siem && docker compose logs wazuh.manager | tail -50"
}

# Nextcloud's logs carry free-form JSON under "data" (object in audit lines, an
# empty array in some application lines) and "exception" (traces whose argument
# types vary). Any type the indexer guesses for them rejects the other shapes, and
# rejected alerts vanish silently. These subtrees are stored but not indexed
# ("enabled": false), so every shape is accepted; the raw line stays in full_log.
# Applies to daily indices created after it is installed (decision record 0005).
indexer_templates() {
  local code
  code=$(curl -sk -o /dev/null -w '%{http_code}' -u "admin:$(env_get "$SIEM_DIR/.env" INDEXER_PASSWORD)" \
    -H 'Content-Type: application/json' -X PUT https://127.0.0.1:9200/_template/thesis-nextcloud-overrides \
    -d '{"order":10,"index_patterns":["wazuh-alerts-4.x-*","wazuh-archives-4.x-*"],
         "mappings":{"properties":{"data":{"properties":{
           "data":{"type":"object","enabled":false},
           "exception":{"type":"object","enabled":false}}}}}}')
  [[ "$code" == "200" ]] || die "could not apply index template thesis-nextcloud-overrides (HTTP $code)"
  ok "index template thesis-nextcloud-overrides applied (data.data, data.exception not indexed)"
}

# GeoIP database for the normalizer (CTX-01): the GeoLite2-City file that ships
# with the Wazuh indexer image, so the normalizer and Wazuh's own GeoLocation use
# the same data and nothing is downloaded. MaxMind's licence restricts
# redistribution: the copy lives in data/ (git-ignored), never in the repository.
geoip_db() {
  local src=/usr/share/wazuh-indexer/modules/ingest-geoip/GeoLite2-City.mmdb
  local dst; dst="$(dirname "$DEPLOY_DIR")/data/geoip/GeoLite2-City.mmdb"
  mkdir -p "$(dirname "$dst")"
  if [[ -f "$dst" && "$(host_md5 "$dst")" == "$(ctr_md5 siem-wazuh.indexer-1 "$src")" ]]; then
    ok "GeoIP database is current (${dst#"$(dirname "$DEPLOY_DIR")"/})"; return
  fi
  docker cp "siem-wazuh.indexer-1:$src" "$dst" >/dev/null
  chmod 644 "$dst"
  ok "GeoIP database copied from the indexer image to ${dst#"$(dirname "$DEPLOY_DIR")"/}"
}

# ---------------------------------------------------------------- Nextcloud
nextcloud_up() {
  log "Starting Nextcloud project (proxy, app, db, redis, cron, agent)"
  (cd "$NC_DIR" && docker compose config -q && docker compose up -d)
  recreate_stale_mounts "$NC_DIR"
  printf '    waiting for Nextcloud to install and become healthy (first run takes a few minutes)'
  local i state
  for i in $(seq 1 120); do
    state=$(cd "$NC_DIR" && docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q app)" 2>/dev/null || echo starting)
    if [[ "$state" == "healthy" ]]; then printf '\n'; ok "Nextcloud is healthy"; return; fi
    printf '.'; sleep 5
  done
  printf '\n'
  die "Nextcloud not healthy after 10 minutes; check: cd nextcloud && docker compose logs app | tail -80"
}

summary() {
  local ncd wzd
  ncd=$(env_get "$NC_DIR/.env" NEXTCLOUD_DOMAIN); wzd=$(env_get "$NC_DIR/.env" WAZUH_DOMAIN)
  log "Done"
  cat <<EOF
    Nextcloud:  https://$ncd
                user: $(env_get "$NC_DIR/.env" NEXTCLOUD_ADMIN_USER)   password: in nextcloud/.env (NEXTCLOUD_ADMIN_PASSWORD)
    Wazuh:      https://$wzd
                user: admin   password: in siem/.env (INDEXER_PASSWORD)

    Show passwords:   sudo grep -E 'ADMIN_PASSWORD|INDEXER_PASSWORD' nextcloud/.env siem/.env
    Re-run checks:    sudo ./scripts/verify-phase1.sh
    Persistence test: sudo ./scripts/verify-phase1.sh --recreate
EOF
}

main() {
  fix_files
  preflight
  install_docker
  host_packages
  kernel_and_swap
  firewall
  secrets_and_config
  siem_certs
  siem_up
  validate_manager_rules
  recreate_stale_mounts "$SIEM_DIR"
  wait_for_manager
  indexer_templates
  geoip_db
  nextcloud_up
  if [[ "${SKIP_VERIFY:-0}" != "1" ]]; then
    "$DEPLOY_DIR/scripts/verify-phase1.sh" || warn "some checks did not pass; see the report above"
  fi
  summary
}

main "$@"
