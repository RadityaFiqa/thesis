# 0004. Ingestion through rules, normalization in Python, joined by request id

Date: 2026-10-18 · Status: accepted

## Context
LOG-02 needs normal activity searchable, not only alerts. Wazuh indexes an event only when a rule at level ≥ 3 matches it. The alternative, `logall_json` archives, indexes every line and roughly doubles storage.

LOG-03 needs one documented mapping from three log formats. Joining audit and proxy lines by time and user is ambiguous when one user makes parallel requests.

## Decision
- **Rules.** A parent rule per log file (audit 100100, application 100200, proxy 100300) keeps every line searchable. Child rules name the action for analysts (`nc_auth_success`, `nc_file_write`, `nc_share`, `nc_http_failure`, …), and each child repeats its source group, because Wazuh children don't inherit a parent's `<group>`. Internal "Cache entry" lines are level 0 (not indexed).
- **Selection by source, not by rule.** The normalizer selects alerts by `location` (the log file). Wazuh's built-in rule 2501 claims "Login failed" lines before the Nextcloud rules see them; rules 100114/100202 re-attach them for analysts, but the normalizer never depends on which rule fired.
- **Request id as the join key.** Caddy generates a UUID, logs it and sends it as `X-Request-Id`; Apache passes it to Nextcloud as `UNIQUE_ID`, which becomes `reqId`. Caddy also returns it to the client, so the simulator can record exactly which requests it made.
- **Authoritative mapping in Python** (`ueba.adapters.nextcloud_logs`, `ueba.application.normalize`), tested on real samples. The Wazuh rules mirror it for search, nothing more.

## Consequences
- 13/13 sampled actions trace from the index to the expected normalized event (`ueba trace`).
- WebDAV/API authentication becomes its own action (`auth`). Counting it as login would turn request volume into login counts.
- The normalizer and the Wazuh rules can drift apart. Only the normalizer feeds analysis, so drift affects search convenience, not results.
