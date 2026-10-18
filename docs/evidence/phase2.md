# Phase 2 evidence (M2 Data pipeline)

Date: 2026-10-18 · Environment: VPS `VM-17-129-ubuntu`, stack from `infra/` at the commit that adds this file.

## How to reproduce

On the VPS, from `~/thesis/infra`:

```bash
START=$(date -u +%FT%TZ)
sudo ./scripts/phase2-sample-actions.sh          # one of each action, through the public HTTPS path
sleep 45                                          # let the agent, manager and indexer catch up
S=$(sudo sh -c "ls -d reports/phase2-samples-* | tail -1")
sudo ./scripts/ueba.sh normalize --indexer --since "$START" \
     --out ../data/phase2-final.jsonl --geoip ../data/geoip/GeoLite2-City.mmdb
sudo ./scripts/ueba.sh trace --manifest "$S/manifest.jsonl" --events ../data/phase2-final.jsonl
```

Outputs (git-ignored, on the VPS): `reports/phase2-samples-20261018-125540/` (manifest and raw log lines), `data/phase2-final.jsonl` (normalized events), `data/phase2-final.quality.json` (quality report).

## Results (final run, 12:55 UTC)

| Measure | Result |
|---|---|
| Actions traced from the Wazuh indexer to the expected normalized event | **13 / 13** |
| Normalized events | 15 (12 actions + 3 per-request WebDAV authentications) |
| Outcomes | 12 success, 3 failure (failed web login, rejected WebDAV credential, download of a missing file) |
| Collection lag, source → manager | min 0.14 s, p50 0.66 s, p95 1.58 s, max 1.99 s (n = 15) |
| Duplicate raw records | 0 observed; drop-and-count path covered by `test_repeated_raw_lines_are_counted_and_dropped` |
| Records skipped, all with a reason | login_attempt_precursor 5, not_a_user_action 3, application_log 3, system_actor 1, session_churn 1, share_interaction_duplicate 1 |
| Missing required fields | none |
| GeoIP | 15 / 15 resolved; database `GeoLite2-City built 2019-11-12`. Replaced afterwards by DB-IP City Lite 2026-10, which places the same client IP (the VPS) in ID/Jakarta instead of JP (decision 0006) |
| Wazuh `GeoLocation` on proxy alerts | 16 / 16 since the run started |
| Phase 1 regression (`verify-phase1.sh`) | 53 pass, 0 fail, 0 warn |
| Unit tests | 34 pass; layer contract kept; lint clean |

Earlier runs at 10:50 UTC (13/13, lag p50 0.74 s) and from the sample files (13/13) agree.

## Requirement check

| ID | Priority | Acceptance criterion | Status | Evidence |
|---|---|---|---|---|
| LOG-01 | Must | Login, upload, download and failure samples correlated where supported | ✅ | `ueba trace` 13/13, joined by request id |
| LOG-02 | Must | Known normal actions searchable through a configured ingestion path | ✅ | Parent rule per log, level 3 (decision 0004); every action found in the index |
| LOG-03 | Must | Timestamp, actor, action, source, outcome, provenance have documented mappings | ✅ | `docs/data/field-mapping.md` |
| LOG-04 | Must | Raw source reference and missing/invalid-field indicators retained | ✅ | `provenance.raw_ref` → index document (`full_log`); `parse_issues`; skip reasons; `missing_fields` in the quality report |
| LOG-05 | Must | Duplicate handling and source-to-index delay measured | ✅ with limits | Lag above; duplicates handled and tested, none occurred live. Lag is measured to the manager's processing time, not to search visibility |
| CTX-01 | Should | Provider/version, lookup status, approximate geography recorded | ✅ with limit | `geo.provider`, `geo.status`; the database is from 2019 |
| CTX-02 | Must | Private/unresolved IPs stay unknown | ✅ | `classify_ip`, `GeoContext` rejects a location without `resolved`; unit tests. Live runs had only public IPs |
| CTX-03 | Must | Trusted proxy passes a client-IP check | ✅ | `verify-phase1.sh`: real IP logged, forged headers ignored |

**Release gate M2** ("normal and suspicious-action samples traced end to end"): normal actions ✅. Suspicious samples traced: failed web login, rejected WebDAV credential (triggered Nextcloud brute-force protection), failed download. Volume scenarios (mass download, mass upload, broad file access) are generated in Phase 3 (SIM-03) and will reuse this trace.

## Problems found and fixed during Phase 2

| Problem | Effect | Fix |
|---|---|---|
| Built-in rule 2501 claims "Login failed" | Failed logins lost Nextcloud groups | Selection by `location`; rules 100114/100202 (0004) |
| Child rules don't inherit parent groups | Upload events not under `nextcloud_audit` | Source group on each child rule |
| Rule with static field `status` | Manager down ~9 min | Rules tested before reload (0007) |
| `data: []` and mixed exception traces | Application-log alerts rejected silently | Free-form subtrees not indexed (0005) |
| Single-file bind mounts keep old content | Caddy and manager ran stale config after edits | `setup.sh` detects and recreates (0007) |
| `grep -q` / `wazuh-control status` exit codes under `pipefail` | False failures in checks | Output captured before matching |
| Web form login needs an `Origin` header | Scripted logins rejected by CSRF check | Sampler sends `Origin` like a browser |
| Basic-auth requests log "Login successful" / "Logout occurred" each time | Login counts would measure request volume | Separate `auth` action; `session_churn` skipped |
| New user's first request copies ~60 skeleton files | Looks like a mass upload | `side_effect_write`; Phase 3 must warm up new users |

## Storage

`wazuh-alerts-4.x-2026.10.18`: 727 alerts, 2.8 MB after a day of setup and testing. Raw logs: 532 KB (Nextcloud), 320 KB (Caddy). Disk: 58 GB free of 79 GB. No retention policy is configured: indices are kept until a decision is made (open, see roadmap).

## Limits to state in the thesis

- Lag is measured to the manager's `timestamp`; indexing adds a further delay that this measure doesn't include.
- The sampled actions come from one synthetic user and one client IP (the VPS itself), so the geography in these samples is not varied.
- The GeoIP results in this run come from the 2019 database; later runs use DB-IP City Lite 2026-10.
- The 2026-10-18 index predates decision 0005, so application-log lines are missing from that one index (still in the log file).
