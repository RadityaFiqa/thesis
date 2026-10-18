# Field mapping: raw logs → `NormalizedEvent` (LOG-03, LOG-04)

Schema `normalized-event/2` (/2 added `effective_time`). Behavioral features use `analysis_time` = `effective_time` if present, else `event_time`. Code: `src/ueba/adapters/nextcloud_logs.py` (parsing) and `src/ueba/application/normalize.py` (correlation). Every rule below comes from real samples taken with `infra/scripts/phase2-sample-actions.sh`; the samples behind the tests are in `tests/fixtures/phase2-samples/`.

## Sources

| Source | File | Used for |
|---|---|---|
| Nextcloud audit (`admin_audit`) | `/var/log/nextcloud/audit.log` | Who did what to which file, authentication results |
| Caddy access log | `/var/log/caddy/access.log` | HTTP status, bytes, user agent, actions the audit log doesn't record |
| Nextcloud application log | `/var/log/nextcloud/nextcloud.log` | Explains failures (brute-force, exceptions); no user actions of its own, not normalized |

All three carry the same **request id**: Caddy generates a UUID for each request, writes it to its log as `request_id`, and sends it upstream as `X-Request-Id`. Apache sets it as `UNIQUE_ID`, which Nextcloud uses as `reqId`. Clients can't choose it: Caddy overwrites the header.

## Fields

| Field | Audit log | Proxy log | Missing-value policy |
|---|---|---|---|
| `event_time` | `time` (ISO 8601, UTC) | `ts` (epoch seconds) | Record skipped as `invalid_record` |
| `ingest_time` | Wazuh alert `timestamp` (manager processing time) | same | `None` when read from files |
| `effective_time` | from the proxy record of the same request | `sim_time`, logged only by the simulation listener (decision 0008) | `None` for real traffic; unparsable or timezone-less values → `None` + flag `invalid_sim_time` |
| `action` | from `message` + HTTP method, see below | from method + path | — |
| `outcome` | `success` / `failure` from message | status < 400 → success, else failure | `unknown`, never assumed success (proxy login: both outcomes answer 303) |
| `user_id` | `user`; for auth lines, the name in the message | user in `/remote.php/dav/files/<user>/` (flag `user_from_url`) | `None` ("--" in the log means none) |
| `client_ip` | `remoteAddr` | `request.client_ip` | `None` |
| `resource` | path in the message, relative to the user's files | DAV path; query string dropped | `None` |
| `user_agent` | `userAgent` | `request.headers.User-Agent[0]` | `None` |
| `response_code` | from the proxy record of the same request | `status` | `None` |
| `bytes_transferred` | from the proxy record, uploads and downloads only | upload: `bytes_read`; download: `size`; successful transfers only | `None`; error pages are not file data |
| `geo` | from `client_ip`, see GeoIP below | same | explicit status, never an invented location |
| `provenance` | source, `index/_id` or `file:line`, `reqId` | source, ref, `request_id` | — |
| `parse_issues` | quality flags (below) | | empty when none |

The raw line is never copied into the normalized event; `provenance.raw_ref` points to it in the index (`full_log`) or the file.

## Actions

| Audit message | Condition | Action |
|---|---|---|
| `Login successful: "<u>"` / `Login failed: "<u>"` | URL is `/login` | `login` (interactive) |
| same | any other URL (WebDAV, API) | `auth`: per-request authentication, **not a login** |
| `Logout occurred` | URL is `/logout` | `logout` |
| `Logout occurred` | anything else | skipped `session_churn` (basic-auth requests end a temporary session) |
| `File with id "N" written to/created: "<p>"` | `PUT` to that path, or `MOVE` from `/dav/uploads/` (chunked) | `upload` |
| same | `MKCOL` to that path | `mkdir` |
| same | anything else | `other` + flag `side_effect_write` (e.g. ~60 skeleton files copied on a user's first login) |
| `File with id "N" accessed: "<p>"` | `GET` | `download`; other methods → `access` |
| `File with id "N" deleted: "<p>"` | | `delete` |
| `File renamed with id "N" from "<a>" to "<b>"` | | `rename` (resource = old path) |
| `The file "<p>" ... has been shared via <x>` | | `share` |
| any other message | | `other` + flag `unmapped_message` |

| Proxy request | Action |
|---|---|
| `GET` / `PUT` / `PROPFIND` / `MKCOL` / `MOVE` / `DELETE` on `/remote.php/dav/files/<user>/…` | `download` / `upload` / `access` / `mkdir` / `rename` / `delete` |
| `POST /login`, `GET /logout`, `POST …/files_sharing/api/v1/shares` | `login` / `logout` / `share` |
| other DAV methods (`OPTIONS`, `PROPPATCH`, …) | skipped `dav_protocol_request` |
| pages, scripts, styles, polling | skipped `not_a_user_action` |

## Correlation (one request → events)

1. Audit events are the user's actions. Identical ones within a request are merged (an upload logs "created" and "written to").
2. The proxy record of the same request adds `response_code`, `bytes_transferred`, `user_agent`.
3. If the audit log has no user action for the request (failed download, folder listing), the proxy event is kept, flagged `proxy_only`. Without this, failures would be invisible (SIM-05).
4. A rejected credential (`auth` / `failure`) is already the event; the 401 proxy record is not added.

Every input event ends up exactly once as output, merged duplicate, or superseded proxy record (checked by `tests/unit/test_phase2_samples.py`).

## Skipped records (counted, never silent)

`internal_cache` (Cache entry …), `login_attempt_precursor` (its outcome follows in its own line), `share_interaction_duplicate`, `session_churn`, `system_actor` (file events without a user: cron, occ, previews), `not_a_user_action`, `dav_protocol_request`, `application_log`, `invalid_record`, `invalid_json`. Counts are in each run's `*.quality.json`.

## Quality flags (`parse_issues`)

`user_from_url`, `proxy_only`, `no_proxy_record`, `side_effect_write`, `unmapped_message`, `missing_status`, `invalid_sim_time`.

## GeoIP (CTX-01, CTX-02)

- Database: DB-IP City Lite, one monthly edition per file in `data/geoip/` (git-ignored), downloaded with `infra/scripts/update-geoip.sh`; current 2026-10. `geo.provider` records the database type, build date and file on every event (decision 0006). IP Geolocation by DB-IP (https://db-ip.com), CC BY 4.0.
- Private, loopback and link-local IPs are never looked up: `private`. No IP: `missing`. Not an IP: `invalid`. Public but unknown to the database: `not_found`. Only `resolved` carries a location.
- A location is the database's estimate for an IP. It is not proof of where a person is: VPNs, proxies, NAT and mobile networks limit it.
- For analysts, Caddy also logs the client IP as `srcip`, which Wazuh's ingest pipeline turns into `GeoLocation` for dashboard maps. That uses the indexer's bundled 2019 GeoLite2, so maps can differ; the normalized dataset uses its own lookup above.

## Known limits

- `audit.log` has no byte counts; transfer volume relies on the proxy log.
- Folder listings (`PROPFIND`) and failed operations appear only in the proxy log.
- WebDAV clients authenticate on every request, so `auth` counts measure request volume, not sessions.
- Timestamps are the server's clock (UTC); local-time context for features is applied in Phase 4.
