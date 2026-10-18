# 0006. GeoIP: own lookup with a recorded database, plus Wazuh GeoLocation for search

Date: 2026-10-18 · Status: accepted; database choice open (see Consequences)

## Context
CTX-01 asks for location context with a recorded provider and version. CTX-02 forbids invented locations for private or unknown IPs.

Wazuh's ingest pipeline already adds `GeoLocation`, but only for fixed fields (`data.srcip`, AWS, Office 365, …). It doesn't record the database version, and for private IPs it silently adds nothing. Nextcloud's IP fields (`remoteAddr`, `request.client_ip`) aren't among those fields, so no Nextcloud event had a location.

## Decision
- **Analysis:** the normalizer looks up `client_ip` itself (`ueba.adapters.mmdb_geo`) in a `.mmdb` city database. Each event's `geo.provider` names the database type and build date, and `geo.status` says `resolved`, `private`, `not_found`, `invalid` or `missing`.
- **Search:** Caddy also logs the client IP as `srcip`, so Wazuh's pipeline fills `GeoLocation` on proxy alerts for dashboard maps (verified: 16/16 proxy alerts in the final sample run).
- **Database for now:** the `GeoLite2-City.mmdb` shipped in `wazuh/wazuh-indexer:4.14.9`. `setup.sh` copies it to `data/geoip/` (git-ignored), so nothing is downloaded.
- **Reader:** `python3-maxminddb` from Ubuntu (2.5.2) on the VPS, `maxminddb==2.6.3` on the development PC. The reader version doesn't affect results; the database does.

## Consequences
- **The bundled database was built on 2019-11-12** (from its metadata; the file date in the image is only the image build date). It is most likely the last GeoLite2 release that could be redistributed freely before MaxMind's licence change at the end of 2019, so it is about seven years out of date, and both the normalizer and Wazuh's `GeoLocation` use it. IP blocks reassigned since 2019 can resolve to the wrong country or city. For the thesis, either:
  - use a current database: DB-IP City Lite (monthly, CC BY 4.0, no account) or GeoLite2 (free MaxMind account and licence key); or
  - keep the 2019 database and state its age as a limitation.

  Switching changes only the `--geoip` file; `geo.provider` records whichever is used.
- The GeoLite2 licence restricts redistribution: no `.mmdb` file may be committed to the public repository.
- A location is an estimate for an IP, not proof of a person's location (PRD CTX-01 note).
