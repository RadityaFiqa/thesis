# Architecture

## System

```
Users / simulator ─HTTPS─> Cloudflare ─> Caddy ─> Nextcloud ─┬─ PostgreSQL
                                           │        cron ────┘  └─ Redis
                                           │
                       nextcloud project   │   logs (read-only) ─> Wazuh agent
  ─────────────────────────────────────────┼──────────────────────────│── host bridge 172.17.0.1:1514/1515
                       siem project        └─> dashboard              ▼
                                                   ▲        manager ─> indexer ─> ueba detector (Phase 6)
                                                   └──────────────────────┘            │
                                                                     detections ◄──────┘
```

Two independent Compose projects (PRD INF-01) with no shared Docker network. Details, ports and design notes: [infra/README.md](../infra/README.md).

## Code (`src/ueba`)

Clean architecture: dependencies point inward only.

```
entrypoints ──> adapters ──> application ──> domain
   (CLI)       (Wazuh,       (use cases,     (events, geo,
               Nextcloud,     ports)          detections)
               GeoIP, files)
```

| Layer | Contains | May import | Must not |
|---|---|---|---|
| `domain` | Frozen dataclasses and pure functions for the PRD's data contracts: `NormalizedEvent`, `GeoContext`, `Detection` | standard library only | do I/O, know about Wazuh/Nextcloud formats |
| `application` | One module per use case (`enrich_geo`, later `normalize`, `build_features`, `train`, `score`) and `ports.py` (Protocols) | `domain` | import an adapter or SDK |
| `adapters` | Port implementations: indexer reader, GeoLite2 lookup, WebDAV client, Parquet store, detection publisher | `application`, `domain`, third-party SDKs | contain research logic |
| `entrypoints` | `ueba` CLI: reads config, picks adapters, calls a use case | everything | contain logic beyond wiring |

`lint-imports` enforces these rules (contract in `pyproject.toml`), so they can't erode quietly.

### Why this helps the thesis

- **Reproducibility.** The feature, model and scoring logic is pure and tested without a running SIEM. Same input + config = same output (FE-01, ML-01).
- **No leakage by construction.** The simulator's ground truth goes through its own port and never reaches feature code (PRD section 6: no labels as features).
- **Swap without rewrites.** Changing from alerts to archives, or from the indexer to exported files, touches one adapter.

## Phase → module map

| Phase | Domain | Application | Adapters |
|---|---|---|---|
| 2 Collection | `events` ✅, `geo` ✅ | `normalize` ✅, `enrich_geo` ✅, `trace` ✅, `quality` ✅ | `nextcloud_logs` ✅, `wazuh_indexer` ✅, `jsonl_store` ✅, `mmdb_geo` ✅ |
| 3 Simulation | `scenarios`, ground-truth records | `simulate` | `nextcloud_dav`, ground-truth store |
| 4 Features | `features` (window, definitions) | `build_features` | `parquet_store` |
| 5 Model | model metadata | `train`, `calibrate` | model registry (files) |
| 6 Integration | `detections` ✅, `risk` | `score`, checkpointing | `wazuh_detections` |
| 7 Evaluation | metrics | `evaluate` | report export |

✅ = exists now.
