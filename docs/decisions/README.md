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
| [0003](0003-audit-data-mapping.md) | Index template mapping `data.data` as an object for Nextcloud audit events |
