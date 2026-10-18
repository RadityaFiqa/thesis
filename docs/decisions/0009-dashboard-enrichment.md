# 0009. Clean thesis.* fields and GeoIP in the Wazuh dashboard

Date: 2026-10-18 · Status: accepted

## Context
In the Wazuh dashboard, Nextcloud alerts were hard to read:
- **Audit alerts** (most of them) carried the client IP only as `data.remoteAddr`, with no location. Wazuh's GeoIP reads only fixed fields such as `data.srcip`.
- **Proxy alerts** had the injected IP, `data.sim_time` and a location, but each carried about 72 fields, one per HTTP header and TLS detail, so the useful ones were buried.
- The same idea had different names per source: `remoteAddr` vs `request.client_ip`, `user` vs a user inside the URL.

This is about search and display for analysts. The research dataset is unaffected: the normalizer reads the raw `full_log` (decision 0004).

## Decision
- **Ingest pipeline `thesis-nextcloud-enrich`** (`infra/siem/config/thesis/ingest-pipeline.json`). For alerts from the three Nextcloud log files it adds `thesis.source`, `thesis.client_ip`, `thesis.user`, `thesis.action`, `thesis.outcome`, `thesis.http_status`, `thesis.sim_time` and `thesis.user_agent`. It then runs GeoIP on `thesis.client_ip` when `GeoLocation` is missing, which covers audit events. Every step uses `ignore_failure`, so an enrichment error can never stop an alert from being indexed.
- **Hook.** A `pipeline` processor (tag `thesis_enrich`) is appended to Wazuh's `filebeat-*-wazuh-alerts-pipeline`. An `index.final_pipeline` was tried first and doesn't work here: Filebeat writes to its default index name and Wazuh's pipeline re-routes each alert (`date_index_name`), so the target index's settings are never consulted. A `filebeat-*` template didn't work either. Filebeat installs its pipeline only when it is missing, so the hook survives restarts. A Wazuh upgrade recreates the pipeline, and `setup.sh` adds the hook again (tested by resetting the pipeline).
- **Index template** (`index-template.json`): explicit types for `thesis.*` (`client_ip` as ip, `sim_time` as date, `http_status` as integer). `data.request.headers`, `data.request.tls` and `data.resp_headers` are stored but not indexed, in addition to the free-form subtrees from decision 0005. `setup.sh` also adds the `thesis.*` types to existing alert indices.
- **Saved search "Nextcloud activity"** (`saved-search.json`), with columns user, action, outcome, client IP, country, city, virtual time, HTTP status and source. It hides page and asset requests and successful per-request WebDAV authentication; failed authentication stays visible. `setup.sh` also refreshes the `wazuh-alerts-*` field list. Multitenancy is off, so saved objects are shared by all users.
- **Checks.** `verify-phase1.sh` fails if the hook is missing, or if its test upload's alert lacks `thesis.*`.

### Readable view: index pattern `nextcloud-activity` (added the same day)
- **`thesis.resource`**: the file or folder inside the user's files. Audit alerts take it from the message: the last quoted path, or the first one for share lines, which also give the user when the audit line has none. Proxy alerts take it from the WebDAV path.
- **`thesis.view`**: true for exactly one row per real user action. Hidden duplicates:
  - an upload's "created" line (its "written to" line stays), and a new folder's "written to" line;
  - proxy rows the audit log already records; proxy rows stay only for folder listings and failed requests, except 401, because the audit log records the rejected credential;
  - temporary-session logouts, "Login attempt" lines, successful per-request WebDAV authentication, `other`, and application-log lines (except brute-force detection).

  Checked on a sampler run: 42 alerts became 13 rows, one per performed action.
- **Filtered alias `nextcloud-activity`** (in the index template, so every new daily index gets it) shows `thesis.view: true` and only rows with a user. Nothing is copied: it is a view over the alert indices.
- **Index pattern `nextcloud-activity`** (`index-pattern-nextcloud-activity.json`) lists only 20 fields. Source filters hide the raw Wazuh and Nextcloud fields in the document view. The saved search "Nextcloud activity" uses it. The full raw alert stays available through `wazuh-alerts-*`.
- **Backfill:** today's 9,011 Nextcloud alerts were run through the pipeline once (`_update_by_query`, 0 failures). That only added `thesis.*`, `GeoLocation` and `thesis.view`; `full_log` and the Wazuh fields are unchanged.
- **Limit:** in this view, successful simulated actions are audit rows, so `thesis.sim_time` is mostly empty there. Virtual time per action lives in the normalized dataset.

## Verification (2026-10-18)
- `_simulate` on real alerts of every kind, then real indexing into a throwaway index: all accepted; IPv6 accepted; `sim_time` with microseconds and an offset queryable as a date; header subtrees no longer mapped.
- Live sim-path upload and download: audit alerts carry `thesis.*` and `GeoLocation`, and proxy alerts also carry `http_status` and `sim_time`. No audit or proxy alert was rejected.
- `verify-phase1.sh`: 57 pass, 0 fail.

## Consequences
- Each Nextcloud alert has one consistent set of fields and, for public IPs, a location.
- **Audit alerts still have no virtual time:** Nextcloud never logs `X-Sim-Time`, and alerts are indexed one at a time, so they can't be joined. Per-action virtual time lives in the normalized dataset (`effective_time`).
- **Dashboard locations use the GeoLite2 database bundled with the indexer (2019)**, so they can differ from the dataset, which uses DB-IP City Lite (decision 0006). For example, the VPS IP shows as Japan in the dashboard and Jakarta in the dataset.
- `thesis.action` here is a display label from rule groups and HTTP methods. The authoritative mapping is the normalizer's.
- The header cleanup applies from the next daily index; the 2026-10-18 index keeps the old mapping.
- Changing Wazuh's own pipeline is a dependency on its structure; `setup.sh` and `verify-phase1.sh` make the hook explicit and checked.
