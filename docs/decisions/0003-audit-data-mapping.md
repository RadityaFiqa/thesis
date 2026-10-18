# 0003. Map `data.data` as an object for Nextcloud audit events

Date: 2026-10-18 · Status: accepted

## Context
Nextcloud `admin_audit` lines contain a nested object, `"data": {"app": "admin_audit"}`. Wazuh puts decoded JSON under `data.*`, so the field becomes `data.data`. The stock `wazuh-alerts` template maps that as `keyword`, so the indexer rejected every audit alert with `mapper_parsing_exception`.

The failure was silent: the manager's `alerts.json` had the events and the agent showed no drops, but nothing was searchable.

## Decision
`setup.sh` installs a legacy index template, `thesis-nextcloud-overrides` (order 10). It applies to `wazuh-alerts-4.x-*` and `wazuh-archives-4.x-*` and maps `data.data` as `object`.

The 2026-10-18 index was created before the template existed, so it was deleted; it held only setup smoke-test alerts.

## Consequences
- Audit events are indexed. `verify-phase1.sh` confirmed the test upload is searchable (rule 100100).
- The template affects only daily indices created after it is installed.
- Phase 2 should map Nextcloud fields to dedicated names (e.g. `nc.*`), so they don't collide with Wazuh's own `data.*` fields.
