"""`ueba features`: user-window feature rows from normalized events (Phase 4)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ueba.adapters.feature_store import file_sha256, write_manifest, write_rows
from ueba.adapters.jsonl_store import read_events
from ueba.application.build_features import FeatureConfig, FeatureStats, build_features


def cmd_features(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = FeatureConfig.from_dict(raw)

    inputs = [Path(p) for p in args.events]
    events = [e for p in inputs for e in read_events(p)]
    stats = FeatureStats()
    rows = build_features(events, cfg, stats)

    out = Path(args.out)
    rows_sha = write_rows(out, rows)
    summary = {
        "input_events": stats.input_events,
        "used_events": stats.used_events,
        "skipped_events": dict(stats.skipped),
        "users": stats.users,
        "windows": stats.windows,
        "warmup_windows": stats.warmup_windows,
        "training_eligible_windows": stats.windows - stats.warmup_windows,
        "missing_values": dict(stats.missing),
    }
    manifest = out.with_suffix(".manifest.json")
    write_manifest(
        manifest,
        inputs={str(p): file_sha256(p) for p in inputs},
        config={k: v for k, v in raw.items() if not k.startswith("$")},
        config_hash=cfg.config_hash,
        rows_sha256=rows_sha,
        stats=summary,
    )
    print(f"{stats.windows} feature rows ({stats.users} users) -> {out}")
    print(f"manifest -> {manifest}")
    print(json.dumps(summary, indent=2))
    return 0


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("features", help="build user-window feature rows (Phase 4, FE-01..FE-03)")
    p.add_argument(
        "--events", required=True, nargs="+", metavar="JSONL", help="normalized events file(s)"
    )
    p.add_argument("--config", default="config/features/default.json", help="feature config JSON")
    p.add_argument(
        "--out", required=True, metavar="FILE", help="output .jsonl (manifest beside it)"
    )
    p.set_defaults(func=cmd_features)
