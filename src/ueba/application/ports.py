"""Ports: what the use cases need from the outside world.

Adapters in ueba.adapters implement these. Add a port when a use case needs it,
not before.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Protocol

from ueba.domain.detections import Detection
from ueba.domain.events import NormalizedEvent
from ueba.domain.geo import GeoContext


class EventSource(Protocol):
    """Reads normalized events for a time range (Phase 2; Wazuh indexer adapter)."""

    def read(self, start: datetime, end: datetime) -> Iterator[NormalizedEvent]: ...


class GeoLookup(Protocol):
    """Looks up a public IP (Phase 2, CTX-01). Returns None when the database has no entry."""

    @property
    def provider(self) -> str: ...   # database name + version

    def lookup(self, ip: str) -> GeoContext | None: ...


class DetectionSink(Protocol):
    """Publishes detections so analysts can find them in Wazuh (Phase 6, UI-01)."""

    def publish(self, detections: Iterable[Detection]) -> None: ...
