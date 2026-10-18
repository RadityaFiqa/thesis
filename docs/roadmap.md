# Roadmap

Phases and milestones come from the PRD (section 9). The week estimates are suggestions for one person part-time, not PRD requirements; adjust them to the thesis deadline.

| Phase | Milestone | Deliverable | Release gate | Status | Estimate |
|---|---|---|---|---|---|
| 1 | M1 Environment | Two Compose stacks + docs | Phase 1 checks pass | ✅ 53/53 on 2026-10-18. Still to do: `--recreate` check, restore drill | Week 0 |
| 2 | M2 Data pipeline | Mapped, searchable real activity | Normal + suspicious samples traced end to end | ⏳ next | Weeks 1–2 |
| 3 | M3 Simulator | Workloads + independent ground truth | Repeated runs give expected verified operations | — | Weeks 3–4 |
| 4 | M4 Features | Versioned user-window dataset | Feature correctness + leakage checks pass | — | Weeks 5–6 |
| 5 | M5 Model | Isolation Forest + fixed threshold | Reproducible validation | — | Week 7 |
| 6 | M6 Integration | Searchable detection records | Controlled scenario → traceable detection | — | Week 8 |
| 7 | M7 Evaluation | Comparison tables, thesis evidence | Frozen-test evaluation + limitations documented | — | Weeks 9–10 |

## Phase 2 plan

1. Sample real actions (login, failed login, upload, download, share, delete) and record which fields each log really has.
2. Field mapping table: source field → `NormalizedEvent` field, missing-value policy (LOG-03/04).
3. Per-action Wazuh decoders/rules replacing the level-3 smoke rules (LOG-01/02).
4. Add the request ID to the Caddy log so proxy and audit events can be joined.
5. Measure lag and duplicates (LOG-05).
6. GeoIP adapter with recorded database version (CTX-01/02).

## Open decisions (PRD section 12)

| Needed by | Decision |
|---|---|
| Phase 2 | Index all events (archives) vs rule matches only; field mapping; GeoIP source; retention |
| Phase 3 | Simulated users, run length, volumes, scenario repetitions |
| Phase 4 | Window length, history warm-up |
| Phase 5 | Chronological train/validation/test split |
| Phase 6 | Risk formula; detector-to-Wazuh ingestion |
| Phase 7 | Evaluation unit (user-window default), partial-overlap labeling |
