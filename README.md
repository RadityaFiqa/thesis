# Nextcloud UEBA research platform

Undergraduate thesis: collect Nextcloud user activity, detect behavioral anomalies with Isolation Forest, and present the evidence in Wazuh. Requirements are in [docs/prd.md](docs/prd.md).

| | |
|---|---|
| Nextcloud | https://nextcloud.gbb-landu.my.id |
| Wazuh | https://wazuh.gbb-landu.my.id |
| VPS | `ubuntu@43.173.6.37`, git clone in `~/thesis`, stack runs from `~/thesis/infra` |

## Repository layout

```
.
├── docs/                 what and why
│   ├── prd.md            requirements (source of truth)
│   ├── architecture.md   system and code structure
│   ├── roadmap.md        phases M1–M7 and status
│   └── decisions/        one short record per design decision (ADR)
├── infra/                Phase 1: Docker Compose stacks, setup and ops scripts (deployed to the VPS)
├── src/ueba/             Phases 2–7: Python package, clean architecture
│   ├── domain/           pure data and rules (events, geo, detections)
│   ├── application/      use cases + ports (interfaces)
│   ├── adapters/         Wazuh, Nextcloud, GeoIP, storage implementations
│   └── entrypoints/      `ueba` CLI
├── tests/                unit tests (pure, fast) and integration tests
├── config/experiments/   versioned experiment configs (windows, seeds, splits)
├── tools/                developer helpers run from your PC (deploy-to-vps.ps1)
├── data/  artifacts/     generated datasets and models (git-ignored)
└── dist/                 build output (git-ignored)
```

Where things go:

| You are adding... | Put it in |
|---|---|
| A container, port or Wazuh rule/decoder | `infra/` |
| A rule about the data itself (field meaning, validity) | `src/ueba/domain/` |
| A pipeline step (normalize, simulate, build features, train, score) | `src/ueba/application/` |
| Code that talks to Wazuh, Nextcloud, files or a database | `src/ueba/adapters/` |
| A new command | `src/ueba/entrypoints/cli.py` |
| A design choice the thesis must justify | `docs/decisions/NNNN-title.md` |

## Common tasks

Python (once):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

| Task | Command |
|---|---|
| Run tests | `.venv\Scripts\pytest` |
| Lint | `.venv\Scripts\ruff check src tests` |
| Check layer boundaries | `.venv\Scripts\lint-imports` |
| Deploy infra to the VPS (after `git push`) | `.\tools\deploy-to-vps.ps1` |
| Verify Phase 1 on the VPS | `ssh ubuntu@43.173.6.37 "cd ~/thesis/infra && sudo ./scripts/verify-phase1.sh"` |
| Local test stack (Docker Desktop) | `infra\local\run-local.cmd` / `infra\local\stop-local.cmd` |

Operations, backup/restore and troubleshooting: [infra/README.md](infra/README.md).
