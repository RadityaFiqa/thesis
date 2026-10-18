"""JSON Lines storage for feature rows, with a manifest for reproducibility (FE-01, EVAL-03)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ueba.domain.features import (
    BASIC_FEATURES,
    CONTEXTUAL_FEATURES,
    FEATURE_SPECS,
    FEATURE_VERSION,
    FeatureRow,
)

ROW_SCHEMA = "feature-row/1"


def row_to_dict(row: FeatureRow) -> dict[str, Any]:
    return {
        "schema": ROW_SCHEMA,
        "feature_version": FEATURE_VERSION,
        "user_id": row.user_id,
        "window_start": row.window_start.isoformat(),
        "window_end": row.window_end.isoformat(),
        "warmup": row.warmup,
        "features": row.values,
        "event_refs": list(row.event_refs),
    }


def row_from_dict(d: dict[str, Any]) -> FeatureRow:
    if d.get("feature_version") != FEATURE_VERSION:
        raise ValueError(f"rows are {d.get('feature_version')}, this code reads {FEATURE_VERSION}")
    return FeatureRow(
        user_id=d["user_id"],
        window_start=datetime.fromisoformat(d["window_start"]),
        window_end=datetime.fromisoformat(d["window_end"]),
        warmup=d["warmup"],
        values=d["features"],
        event_refs=tuple(d.get("event_refs") or ()),
    )


def _line(row: FeatureRow) -> str:
    # sort_keys keeps the bytes stable for the content hash
    return json.dumps(row_to_dict(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_rows(path: Path, rows: Iterable[FeatureRow]) -> str:
    """Write rows; return the sha256 of the written content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            line = _line(row) + "\n"
            h.update(line.encode())
            f.write(line)
    return h.hexdigest()


def read_rows(path: Path) -> Iterator[FeatureRow]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield row_from_dict(json.loads(line))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    path: Path,
    *,
    inputs: dict[str, str],
    config: dict[str, Any],
    config_hash: str,
    rows_sha256: str,
    stats: dict[str, Any],
) -> None:
    manifest = {
        "schema": "feature-manifest/1",
        "feature_version": FEATURE_VERSION,
        "config": config,
        "config_hash": config_hash,
        "inputs": inputs,  # path -> sha256
        "rows_sha256": rows_sha256,
        "features": {
            "basic": list(BASIC_FEATURES),
            "contextual": list(CONTEXTUAL_FEATURES),
            "definitions": [
                {**asdict(s), "group": s.group.value, "missing": s.missing.value}
                for s in FEATURE_SPECS
            ],
        },
        "stats": stats,
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
