# 0007. Detect stale bind mounts and validate Wazuh rules before reloading

Date: 2026-10-18 · Status: accepted

## Context
Three failures during Phase 2 had one theme: config changes that didn't take effect, or took the service down.

1. **Stale single-file mounts.** A file bind mount pins the inode at container creation. `git pull`, `sed -i` and most editors replace files by renaming, so a running container keeps reading the old content, and `docker compose up -d` doesn't notice because the compose config is unchanged. Caddy and the Wazuh manager were both found running old copies.
2. **Manager config copy.** The manager copies `/wazuh-config-mount` into `/var/ossec` only when its container is created. On a plain restart its init script exits 1 before the copy.
3. **Bad rules stop the manager.** A rule using `<field name="status">` (a static field) made `wazuh-analysisd` refuse to start, and the manager was down for about 9 minutes (10:29–10:38 UTC). Agents buffered events meanwhile.

## Decision
`setup.sh` now:
- compares every bind-mounted file on the host with what its container sees, and recreates only the stale services (`recreate_stale_mounts`);
- if `local_rules.xml` on the host differs from the live rules, copies it into the running manager, runs `wazuh-analysisd -t`, restores the old file on failure, and stops with the error, leaving the manager untouched. Only valid rules lead to a recreate (`validate_manager_rules`).

## Consequences
- `git pull && sudo ./setup.sh` reliably applies config changes; `docker compose restart` does not, and isn't the documented way.
- A wrong rule is rejected with its error message before it can stop the manager (tested with a deliberately invalid rule).
- A recreate costs a short service restart, done only when something really changed.
