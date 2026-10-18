# Infrastructure: Nextcloud + Wazuh

This folder (`infra/` in the repository, `~/thesis/infra` in the VPS's git clone) deploys the Phase 1 environment from the PRD (milestone M1) on a single Ubuntu 24.04 VPS:

- **two independent Compose projects**, `nextcloud/` and `siem/`, with no shared Docker network
- **persistent logs** read by a Wazuh agent
- **authenticated agent enrollment**
- **scripts** for setup, verification and backup/restore

Status: deployed on the VPS on 2026-10-18. `scripts/verify-phase1.sh` reported 53 pass, 0 fail, 0 warn. The `--recreate` persistence check and the restore drill haven't been run yet.

## What runs where

```
Internet ── Cloudflare ── :443 Caddy ──┬── nextcloud.gbb-landu.my.id ──> Nextcloud (app) ─┬─ PostgreSQL
                          (nextcloud    │                                  cron ─────────┘  └─ Redis
                           project)     └── wazuh.gbb-landu.my.id ──> 172.17.0.1:5601 ─┐
                                                                                         │
  Wazuh agent (nextcloud project) ── reads logs (read-only) ── 172.17.0.1:1514/1515 ──┐  │
                                                                                      ▼  ▼
                                                    siem project: manager ── indexer ── dashboard
```

| Project | Service | Image (pinned) | Published on host |
|---|---|---|---|
| nextcloud | caddy (reverse proxy, TLS) | `caddy:2.11.6-alpine` | 80, 443 (public) |
| nextcloud | app | `nextcloud:34.0.5-apache` | none |
| nextcloud | cron | `nextcloud:34.0.5-apache` (`/cron.sh`) | none |
| nextcloud | db | `postgres:17.11-alpine` | none |
| nextcloud | redis | `redis:7.4.11-alpine` | none |
| nextcloud | wazuh-agent | `wazuh/wazuh-agent:4.14.9` | none |
| nextcloud | logs-init (one-shot) | `busybox:1.37.0` | none |
| siem | wazuh.manager | `wazuh/wazuh-manager:4.14.9` | 1514, 1515 on 172.17.0.1 only |
| siem | wazuh.indexer | `wazuh/wazuh-indexer:4.14.9` | 9200 on 127.0.0.1 only |
| siem | wazuh.dashboard | `wazuh/wazuh-dashboard:4.14.9` | 5601 on 172.17.0.1 only |

`172.17.0.1` is the Docker host bridge (`docker0`). Containers in either project reach it through `host-gateway`, but it isn't reachable from the internet. So the Wazuh ports are "published on a reachable host address" (PRD INF-07) without public exposure. I tested this cross-project path on Docker 29 before writing these files.

## Before you start

1. **Cloudflare.** Both domains are proxied by Cloudflare (orange cloud). In the Cloudflare dashboard, under **SSL/TLS → Overview**, set the mode to **Full**. The default `CADDY_TLS=internal` uses a self-signed certificate between Cloudflare and the VPS. "Flexible" causes a redirect loop. For **Full (strict)**, see `nextcloud/caddy/certs/README.txt`.
2. **Provider firewall.** In your VPS provider's security group, allow inbound TCP 22, 80 and 443. Nothing else is needed.
3. **Credentials.** Change the VPS password you used to log in, and preferably switch to SSH keys.

## Install

The VPS runs from a git clone. First install:

```bash
git clone https://github.com/RadityaFiqa/thesis.git ~/thesis
cd ~/thesis/infra
sudo ./setup.sh
```

Updates: commit and push from your PC, then from the repository root:

```powershell
.\tools\deploy-to-vps.ps1
```

This runs `git pull --ff-only` in `~/thesis` and then `sudo ./setup.sh`. Files that exist only on the VPS (`.env`, certificates, `authd.pass`, generated users, `reports/`) are git-ignored, so a pull never touches them. Use `-NoSetup` to pull only. Never edit tracked files on the VPS; change them in the repository instead.

`setup.sh` takes about 10–15 minutes on first run, mostly image downloads and Nextcloud installation. It runs these steps:

1. Installs Docker Engine and the Compose plugin from Docker's apt repository.
2. Sets `vm.max_map_count=262144`, adds 4 GB swap and configures container log rotation.
3. Enables `ufw`, allowing your SSH port plus 80 and 443.
4. Generates random secrets into `nextcloud/.env` and `siem/.env` (mode 600). It also writes:
   - the enrollment password
   - the indexer user hashes; the Wazuh demo users get random passwords
   - the dashboard's API configuration
5. Generates the Wazuh TLS certificates.
6. Starts `siem` and waits for the indexer, then starts `nextcloud` and waits until it's healthy.
7. Runs `scripts/verify-phase1.sh` and prints where the passwords are.

The script is safe to re-run. It never overwrites an existing `.env`, secret, certificate or user file, and it never removes volumes.

Show the generated passwords:

```bash
sudo grep -E 'ADMIN_PASSWORD|INDEXER_PASSWORD' nextcloud/.env siem/.env
```

| Where | User | Password key |
|---|---|---|
| https://nextcloud.gbb-landu.my.id | `admin` | `NEXTCLOUD_ADMIN_PASSWORD` in `nextcloud/.env` |
| https://wazuh.gbb-landu.my.id | `admin` | `INDEXER_PASSWORD` in `siem/.env` |

## Verify Phase 1

```bash
sudo ./scripts/verify-phase1.sh             # every check in PRD section 10
sudo ./scripts/verify-phase1.sh --recreate  # plus: recreate all containers, prove data and agent identity survive
```

Each check prints PASS, FAIL, WARN or SKIP. A report without secrets is saved to `reports/phase1-<UTC time>.txt`, for use as thesis evidence. The script creates a test account `thesis-check` and small test files in its home; it changes nothing else.

| PRD item | What the script checks |
|---|---|
| INF-01 | both compose files validate; the two projects share no Docker network |
| INF-02 | db, redis, app, cron, caddy, agent running/healthy; WebDAV upload and byte-identical download |
| INF-03 | `status.php` over HTTPS through Cloudflare; `overwrite*`, `trusted_proxies`, `trusted_domains` |
| INF-04 | `--recreate`: file, account and indexed events survive container recreation |
| INF-05 | manager daemons, indexer health, dashboard response, upload searchable in `wazuh-alerts-*` |
| INF-06 | agent can read audit, application and proxy logs; the log mount is read-only |
| INF-07 | agent's manager address is a host endpoint (not localhost or `wazuh.manager`); TCP 1514/1515 reachable; agent Active |
| INF-08 | `--recreate`: same agent ID, reconnects without registration, no duplicate identity |
| INF-09 | file logging and `admin_audit` enabled; the test upload appears in `audit.log` |
| INF-10 | background jobs mode `cron`; last cron run under 15 minutes ago |
| INF-12 | Docker, OS and kernel versions and the pinned image list go into the report |
| CTX-03 (early) | real client IP logged through Cloudflare; forged `CF-Connecting-IP`/`X-Forwarded-For` ignored |
| Exposure | 1514/1515/5601 bound to the bridge only, 9200 to localhost, 5432/6379/55000 not published |

INF-11 (backup and restore) is covered by the scripts below. Run the restore drill at least once and record it in the thesis.

## Local test on Docker Desktop (Windows)

`local/run-local.cmd` runs the same two projects on your PC before (or instead of) the VPS:

- **Addresses:** `https://nextcloud.localhost:8443` and `https://wazuh.localhost:8443`, with self-signed certificates and no Cloudflare.
- **Wazuh ports** are bound to `127.0.0.1`.
- **Separate state:** it has its own secrets (`*.env.local`) and its own volumes.

It needs Docker Desktop running with about 6 GB of memory for Docker. It runs smoke checks: services, isolation, HTTPS, logging and audit, WebDAV transfer, read-only agent logs, agent enrollment, and the upload being searchable. The output is saved to `local/local-test-output.txt`. Stop it with `local/stop-local.cmd`.

What the local test can't show:
- **Cloudflare:** the client-IP behaviour through Cloudflare isn't exercised.
- **Firewall:** ufw and host setup (`setup.sh`) don't run.
- **File permissions:** Windows-mounted files are readable by every container user, so permission problems only show up on Linux.

## Day-to-day operations

Run these on the VPS from `~/thesis/infra`. Use `sudo`, or log out and back in once so your user is in the `docker` group.

| Task | Command |
|---|---|
| Status | `cd nextcloud && docker compose ps` / `cd siem && docker compose ps` |
| Logs | `docker compose logs -f app` (or `caddy`, `wazuh-agent`, `wazuh.manager`, …) |
| Stop (keeps data) | `cd nextcloud && docker compose stop`; `cd siem && docker compose stop` |
| Start | `cd siem && docker compose up -d`, then `cd nextcloud && docker compose up -d` |
| `occ` | `cd nextcloud && docker compose exec -u www-data app php occ <command>` |
| Agents on manager | `cd siem && docker compose exec wazuh.manager /var/ossec/bin/agent_control -l` |
| Backup | `sudo ./scripts/backup.sh` (to `/var/backups/thesis/<time>/`) |
| Restore | `sudo ./scripts/restore.sh /var/backups/thesis/<time>` (asks you to type RESTORE) |

**Never run `docker compose down -v`, `docker volume rm` or `docker system prune --volumes`.** They delete the data (PRD: data preservation). `docker compose down` without `-v` is safe.

**Upgrades.** Change one pinned image tag at a time, then run `docker compose pull && docker compose up -d`. Take a backup first. Nextcloud can only move up one major version at a time.

## Design notes and deviations to record in the thesis

- **One reverse proxy for both domains.** Caddy runs in the `nextcloud` project and also serves `wazuh.gbb-landu.my.id`. It forwards to the dashboard through its bridge-only host port, not through a shared network, so the two projects stay independent. To restrict who can open the dashboard, set `WAZUH_ALLOWED_CIDRS` in `nextcloud/.env` (e.g. your campus or home IP). Better still, put Cloudflare Access in front of that hostname.
- **Client IP.** Cloudflare's address ranges, in the Caddyfile, are the only trusted upstreams. Caddy takes the client from `CF-Connecting-IP` and overwrites `X-Forwarded-For` before Nextcloud sees it. Nextcloud trusts only the Caddy container (`172.30.10.10`). The Cloudflare ranges were checked on 2026-10-18; refresh them if Cloudflare changes them.
- **Logs collected** (JSON lines, all read-only to the agent):
  - `/var/log/nextcloud/audit.log` (admin_audit)
  - `/var/log/nextcloud/nextcloud.log` (application, `loglevel` 1, UTC timestamps)
  - `/var/log/caddy/access.log` (method, URI, status, bytes, client IP, user agent)
- **Indexing.** Wazuh indexes only events that match a rule. `siem/config/wazuh_cluster/local_rules.xml` contains level-3 smoke rules (100100–100102) so every Nextcloud and proxy event is searchable. Phase 2 (LOG-02 to LOG-05) should decide the final approach: field mapping, `logall_json`/archives, retention.
- **Index template `thesis-nextcloud-overrides`.** Nextcloud audit lines carry a nested `data` object, while the Wazuh template maps `data.data` as keyword. Without the override the indexer rejects every audit alert. `setup.sh` applies it, but it only affects daily indices created afterwards (see `docs/decisions/0003-audit-data-mapping.md`).
- **Resource choices for 2 vCPU / 8 GB:**
  - indexer heap 1 GB
  - Wazuh vulnerability detection off
  - container FIM, rootcheck, SCA and syscollector off in the agent, since they would scan the container, not the VPS
- **Docker and ufw.** Ports published by Docker bypass ufw. That's why the Wazuh ports are bound to `172.17.0.1` and `127.0.0.1` rather than relying on the firewall.
- **TLS between Cloudflare and the VPS** is self-signed by default (Cloudflare "Full"). Visitors still see a valid Cloudflare certificate. Use an Origin CA certificate for "Full (strict)".

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Browser shows "too many redirects" | Cloudflare SSL/TLS mode is Flexible; set it to Full |
| Cloudflare error 521/522 | ports 80/443 closed in the provider firewall, or `caddy` not running |
| Cloudflare error 525/526 | 526 means the mode is Full (strict) without an Origin CA cert; use Full, or install the cert |
| Indexer never ready | `cd siem && docker compose logs wazuh.indexer`; check `sysctl vm.max_map_count` and free RAM |
| Indexer rejects the admin password | the volume was initialized earlier with other passwords: `sudo ./scripts/apply-indexer-users.sh` |
| Agent never Active | `cd nextcloud && docker compose logs wazuh-agent`; compare `WAZUH_REGISTRATION_PASSWORD` with `siem/config/wazuh_cluster/authd.pass` |
| Upload over 100 MB fails in a script | Cloudflare's free plan limits request bodies to 100 MB. The web and desktop clients upload in chunks; scripts should too (Phase 3 simulator) |
| `cron` WARN right after setup | cron runs every 5 minutes; re-run the check later |

## Files

```
infra/                           (~/thesis/infra on the VPS)
├── setup.sh                     host prep, secrets, certificates, start, verify
├── scripts/
│   ├── verify-phase1.sh         PRD section 10 checks, writes reports/
│   ├── backup.sh / restore.sh   INF-11
│   └── apply-indexer-users.sh   re-apply indexer passwords to an existing volume
├── local/                       local test on Docker Desktop (run-local.cmd / stop-local.cmd)
├── nextcloud/
│   ├── docker-compose.yml, .env.example
│   ├── caddy/Caddyfile, caddy/certs/
│   ├── hooks/before-starting/10-thesis-config.sh   logging, audit, cron (idempotent, every start)
│   └── wazuh-agent/ossec.conf
└── siem/
    ├── docker-compose.yml, .env.example, generate-indexer-certs.yml
    └── config/  (from wazuh-docker v4.14.9 single-node; changes marked "Thesis")
```

Generated on the VPS and never committed: `*/.env`, `siem/config/wazuh_indexer_ssl_certs/`, `siem/config/wazuh_cluster/authd.pass`, `siem/config/wazuh_indexer/internal_users.yml`, `siem/config/wazuh_dashboard/wazuh.yml`, `reports/`.
