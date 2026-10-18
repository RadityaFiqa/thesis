# 0005. Free-form JSON subtrees are stored but not indexed

Date: 2026-10-18 · Status: accepted · Supersedes [0003](0003-audit-data-mapping.md)

## Context
0003 mapped `data.data` as `object` so audit events would index. Phase 2 sampling then showed:
- Application-log lines sometimes carry `"data": []`, which the object mapping rejects.
- Exception traces (`data.exception.Trace.args`) mix strings and objects.

23 application-log alerts in 3 hours were rejected silently; only the manager's Filebeat log showed `mapper_parsing_exception`. Any type the indexer guesses for free-form JSON rejects the other shapes.

## Decision
The `thesis-nextcloud-overrides` template maps `data.data` and `data.exception` with `"enabled": false`, so they are kept in `_source` but not parsed. Tested on a throwaway index with every observed shape: object, empty array, string, mixed trace arguments.

## Consequences
- No alert is rejected for these fields. The raw line stays in `full_log`, which is what the normalizer reads.
- Analysts can't search inside these two subtrees; neither carries a field the research uses.
- Applies to daily indices created after the template. The 2026-10-18 index keeps the 0003 mapping, so application-log lines are missing from that one index. They are still in the log file, and the normalizer doesn't use the application log.
