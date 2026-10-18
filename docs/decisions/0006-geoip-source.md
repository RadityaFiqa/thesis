# 0006. GeoIP: own lookup with DB-IP City Lite, plus Wazuh GeoLocation for search

Date: 2026-10-18 · Status: accepted (database revised the same day, see History)

## Context
CTX-01 asks for location context with a recorded provider and version. CTX-02 forbids invented locations for private or unknown IPs.

Wazuh's ingest pipeline already adds `GeoLocation`, but only for fixed fields (`data.srcip`, AWS, Office 365, …). It doesn't record the database version, and for private IPs it silently adds nothing. Nextcloud's IP fields (`remoteAddr`, `request.client_ip`) aren't among those fields.

## Decision
- **Analysis:** the normalizer looks up `client_ip` itself (`ueba.adapters.mmdb_geo`). Each event's `geo.provider` names the database type, build date and file, and `geo.status` says `resolved`, `private`, `not_found`, `invalid` or `missing`.
- **Database: DB-IP City Lite**, monthly, CC BY 4.0, no account needed. `infra/scripts/update-geoip.sh [YYYY-MM]` downloads one edition into `data/geoip/dbip-city-lite-YYYY-MM.mmdb`, checks its size against the server, the gzip and the database type, and keeps every month under its own name. The normalizer is given one file explicitly (`--geoip`), so a run can be reproduced with the same edition. `setup.sh` never downloads it; it only warns if none is present. Current: **2026-10** (built 2026-10-01).
- **Attribution** (required by CC BY 4.0): "IP Geolocation by DB-IP" (https://db-ip.com), in the repository README and wherever location results are shown, including the thesis.
- **Search:** Caddy logs the client IP as `srcip`, so Wazuh's pipeline fills `GeoLocation` on proxy alerts for dashboard maps. That uses the indexer's own bundled GeoLite2 from 2019, so dashboard maps can differ from the dataset. The dataset is authoritative.
- **Reader:** `python3-maxminddb` from Ubuntu (2.5.2) on the VPS, `maxminddb==2.6.3` on the development PC. The reader version doesn't affect results; the database does.

## Comparison (2026-10-18)

| IP | DB-IP 2026-10 | GeoLite2 2019 (bundled with Wazuh) |
|---|---|---|
| 43.173.6.37 (the VPS) | ID, Jakarta | JP |
| 110.136.10.20 | ID, West Java / Teluknaga | ID, Jakarta |
| 8.8.8.8 | US, California / Mountain View | US |
| 185.220.100.250 | DE, Bavaria / Haßfurt | DE, Hesse |

The 2019 database placed the VPS in the wrong country, and it rarely has city data.

## Consequences
- Locations come from an edition seven years newer, with region and city for most IPs.
- DB-IP City Lite is less precise than commercial databases, especially at city level. Analysis should rely on country, and on region only with care.
- The simulation IP pools (`config/simulation/default.json`) were checked against this edition. Two ranges first chosen as Indonesian resolved elsewhere (China; half Australia) and were replaced. Re-check the pools whenever they or the database change.
- The `.mmdb` (127 MB) stays out of git: it is large, and regenerable with the script.
- A location is an estimate for an IP, not proof of a person's location (PRD CTX-01 note).

## History
- Earlier on 2026-10-18 this record chose the GeoLite2-City file bundled with `wazuh/wazuh-indexer:4.14.9`. Its metadata showed a build date of 2019-11-12, likely the last freely redistributable GeoLite2 release, so it was replaced by DB-IP City Lite. The Phase 2 evidence run (`docs/evidence/phase2.md`) used the 2019 file.
