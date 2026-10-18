# Roadmap

Phases and milestones come from the PRD (section 9). The week estimates are suggestions for one person part-time, not PRD requirements; adjust them to the thesis deadline.

| Phase | Milestone | Deliverable | Release gate | Status | Estimate |
|---|---|---|---|---|---|
| 1 | M1 Environment | Two Compose stacks + docs | Phase 1 checks pass | ✅ 53/53 on 2026-10-18. Still to do: `--recreate` check, restore drill | Week 0 |
| 2 | M2 Data pipeline | Mapped, searchable real activity | Normal + suspicious samples traced end to end | ✅ 13/13 traced from the index on 2026-10-18 ([evidence](evidence/phase2.md)). Open: GeoIP database choice, retention | Weeks 1–2 |
| 3 | M3 Simulator | Workloads + independent ground truth | Repeated runs give expected verified operations | ⏳ next | Weeks 3–4 |
| 4 | M4 Features | Versioned user-window dataset | Feature correctness + leakage checks pass | — | Weeks 5–6 |
| 5 | M5 Model | Isolation Forest + fixed threshold | Reproducible validation | — | Week 7 |
| 6 | M6 Integration | Searchable detection records | Controlled scenario → traceable detection | — | Week 8 |
| 7 | M7 Evaluation | Comparison tables, thesis evidence | Frozen-test evaluation + limitations documented | — | Weeks 9–10 |

## Phase 3 plan

1. Simulation path: a Caddy listener on 127.0.0.1 only, trusting `X-Sim-Client-IP` and logging `X-Sim-Time`, so the simulator can set client IP and virtual time without weakening the public path (CTX-03).
2. `effective_time` in the normalizer from the logged virtual time; `event_time` stays the server's clock.
3. Simulator CLI (`ueba simulate`) with YAML profiles, seeds, and a ground-truth store kept apart from the pipeline (SIM-04); records each request id the proxy returns.
4. Warm up new synthetic users before a run (first login copies ~60 skeleton files).
5. Normal profiles with legitimate bursts; scenarios: mass download, mass upload, broad file access (SIM-02/03).
6. Read-only dashboard over runs, ground truth and observed events (local Streamlit).

## Decisions

| Phase | Decision | Status |
|---|---|---|
| 2 | Index rule matches, not archives; field mapping; join by request id | ✅ decisions 0004, 0005 |
| 2 | GeoIP database: bundled 2019 GeoLite2, or a current one (DB-IP Lite / GeoLite2 with account) | open (0006) |
| 2 | Index retention | open; nothing is deleted until decided |
| 3 | Simulated users, run length, volumes, scenario repetitions | open |
| 4 | Window length, history warm-up | open |
| 5 | Chronological train/validation/test split | open |
| 6 | Risk formula; detector-to-Wazuh ingestion | open |
| 7 | Evaluation unit (user-window default), partial-overlap labeling | open |
