# Decision records

One file per decision the thesis may need to justify: `NNNN-short-title.md`, numbered in order, never renumbered. When a decision changes, add a new record that supersedes the old one instead of rewriting it.

Template:

```markdown
# NNNN. Title

Date: YYYY-MM-DD · Status: accepted | superseded by NNNN

## Context
What forced a choice.

## Decision
What we do.

## Consequences
What this costs, what it enables, what to watch.
```

| # | Decision |
|---|---|
| [0001](0001-two-compose-projects.md) | Two independent Compose projects connected through host-published ports |
| [0002](0002-bridge-only-siem-ports.md) | Publish SIEM ports on the Docker bridge address, not the public interface |
| [0003](0003-audit-data-mapping.md) | Index template mapping `data.data` as an object (superseded by 0005) |
| [0004](0004-ingestion-and-normalization.md) | Ingestion through rules, normalization in Python, joined by request id |
| [0005](0005-free-form-json-not-indexed.md) | Free-form JSON subtrees stored but not indexed |
| [0006](0006-geoip-source.md) | GeoIP: own lookup with DB-IP City Lite, plus Wazuh GeoLocation for search |
| [0007](0007-safe-config-deploys.md) | Detect stale bind mounts and validate Wazuh rules before reloading |
| [0008](0008-simulation-path.md) | Simulation path: injected client IP and virtual time on a local-only listener |
| [0009](0009-dashboard-enrichment.md) | Clean thesis.* fields and GeoIP in the Wazuh dashboard |
