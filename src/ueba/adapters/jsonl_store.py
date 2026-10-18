"""JSON Lines storage for normalized events, plus a reader for sample folders."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ueba.adapters.nextcloud_logs import AUDIT_LOCATION, PROXY_LOCATION, parse_record
from ueba.domain.events import Action, NormalizedEvent, Outcome, Provenance, SourceSystem
from ueba.domain.geo import GeoContext, GeoStatus

SCHEMA_VERSION = "normalized-event/1"


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def event_to_dict(event: NormalizedEvent) -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, **_plain(asdict(event))}


def event_from_dict(d: dict[str, Any]) -> NormalizedEvent:
    prov = d["provenance"]
    geo = d.get("geo")
    return NormalizedEvent(
        event_time=datetime.fromisoformat(d["event_time"]),
        ingest_time=datetime.fromisoformat(d["ingest_time"]) if d.get("ingest_time") else None,
        action=Action(d["action"]),
        outcome=Outcome(d["outcome"]),
        provenance=Provenance(
            SourceSystem(prov["source"]), prov["raw_ref"], prov["source_event_id"]
        ),
        user_id=d.get("user_id"),
        client_ip=d.get("client_ip"),
        resource=d.get("resource"),
        user_agent=d.get("user_agent"),
        session_id=d.get("session_id"),
        response_code=d.get("response_code"),
        bytes_transferred=d.get("bytes_transferred"),
        geo=GeoContext(**{**geo, "status": GeoStatus(geo["status"])}) if geo else None,
        parse_issues=tuple(d.get("parse_issues") or ()),
    )


class JsonlEventSink:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, events: Iterable[NormalizedEvent]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with self.path.open("w", encoding="utf-8", newline="\n") as f:
            for event in events:
                f.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")
                n += 1
        return n


def read_events(path: Path) -> Iterator[NormalizedEvent]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield event_from_dict(json.loads(line))


class SampleFolderSource:
    """EventSource over a sampler output folder (audit.jsonl, access.jsonl).

    Files carry no SIEM ingest time, so ingest_time stays None.
    """

    FILES = {"audit.jsonl": AUDIT_LOCATION, "access.jsonl": PROXY_LOCATION}

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.skipped: Counter = Counter()
        self.duplicates = 0

    def events(self) -> Iterator[NormalizedEvent]:
        seen: set[str] = set()
        for name, location in self.FILES.items():
            path = self.folder / name
            if not path.exists():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                digest = hashlib.sha256(f"{location}\n{line}".encode()).hexdigest()
                if digest in seen:
                    self.duplicates += 1
                    continue
                seen.add(digest)
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    self.skipped["invalid_json"] += 1
                    continue
                result = parse_record(location, rec, raw_ref=f"{name}:{lineno}")
                if result.event is None:
                    self.skipped[result.skip_reason] += 1
                else:
                    yield result.event
