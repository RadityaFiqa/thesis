# 0008. Simulation path: injected client IP and virtual time on a local-only listener

Date: 2026-10-18 · Status: accepted

## Context
The simulator (Phase 3) runs on one machine with one IP, but behavioral features need varied source IPs and locations. A realistic history also spans weeks, which can't be run in real time for every experiment.

The public path deliberately ignores client-supplied IP headers (CTX-03), and timestamps come from the server's clock. Changing the clock would break TLS, cron and Wazuh.

## Decision
- **Second Caddy listener**, `https://localhost:8443`, published on `127.0.0.1` only, so only processes on the VPS can reach it. It shares the Nextcloud upstream with the public site (`import nextcloud_upstream`), so both behave identically apart from trust.
- **Per-listener trust.** `:443` trusts only Cloudflare's ranges, through `CF-Connecting-IP`. `:8443` trusts only the Docker network gateway (`SIM_TRUSTED_PROXY`, where connections to the published port come from), through `X-Sim-Client-IP`. Nextcloud then logs the injected IP as `remoteAddr`, exactly as for real traffic.
- **Virtual time.** The simulator sends `X-Sim-Time` (ISO 8601 with timezone). Only the simulation listener logs it, as `sim_time`. The normalizer sets `effective_time` from it for every event of that request (joined by request id). `event_time` stays the server's clock, and lag (LOG-05) is measured on real clocks. Features use `analysis_time` = `effective_time` if present, else `event_time`.
- The virtual time travels through the logs, not from the ground-truth store, so the detection pipeline never reads simulator records (PRD SIM-04, section 6).

## Verification (2026-10-18)
- Through `:8443`: proxy and audit logs show the injected `36.86.63.1`; `sim_time` is logged; normalized events carry `effective_time` 2026-11-01T20:15Z and location ID.
- Through `:443` with the same headers: real IP logged, `sim_time` empty.
- `verify-phase1.sh` keeps checking both permanently: port 8443 bound to 127.0.0.1 only, and forged `X-Sim-Client-IP` / `X-Sim-Time` ignored on the public path. Its test request reaches `:443` from the same gateway address `:8443` trusts.

## Consequences
- Varied IPs, locations and a compressed timeline are possible from one machine.
- IP, location and time of simulated traffic are synthetic context; the thesis must say so.
- The Wazuh dashboard shows real times. Virtual time exists only in the normalized dataset.
- Nextcloud-internal times (file mtime, share expiry) stay real.
- Nextcloud's brute-force protection works per injected IP, as it would for real clients.
- The simulation listener can be told apart in raw logs (`request.host` = `localhost:8443`). That is for auditing only and must never become a feature.
- Anyone with shell access to the VPS can inject IPs. That is acceptable: such a person already controls the logs.
