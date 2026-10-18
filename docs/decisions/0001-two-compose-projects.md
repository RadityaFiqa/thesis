# 0001. Two independent Compose projects

Date: 2026-10-18 · Status: accepted

## Context
PRD INF-01 requires `nextcloud/docker-compose.yml` and `siem/docker-compose.yml` with no shared Docker network. The monitored system and the monitoring system should fail, restart and upgrade independently, as they would in a real deployment.

## Decision
- The Wazuh agent lives in the `nextcloud` project and reads its logs through read-only volume mounts.
- It reaches the manager through ports the `siem` project publishes on the host (`wazuh-manager.host` → `host-gateway`), never through a service name.
- One Caddy instance in the `nextcloud` project serves both domains; it reaches the dashboard through the same host-published path.

## Consequences
- Either stack can be recreated without touching the other; `verify-phase1.sh` checks there is no shared network.
- The dashboard's availability depends on the `nextcloud` project's proxy. Accepted for a single-VPS thesis setup; a second proxy would remove it.
