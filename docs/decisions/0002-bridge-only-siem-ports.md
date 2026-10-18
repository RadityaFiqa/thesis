# 0002. SIEM ports on the Docker bridge address only

Date: 2026-10-18 · Status: accepted

## Context
The agent needs a reachable host endpoint for 1514/1515 (INF-07), and Caddy needs to reach the dashboard. Ports published by Docker bypass `ufw`, so relying on the firewall would expose them to the internet.

## Decision
- 1514, 1515 and 5601 are bound to `172.17.0.1` (docker0).
- 9200 is bound to `127.0.0.1`.
- 55000, 5432 and 6379 are not published.

## Consequences
- Nothing SIEM-related is reachable from the internet, without depending on the firewall.
- An agent on another machine would need a separately secured path (VPN or allow-listed public bind), as the PRD notes for a future remote detector.
