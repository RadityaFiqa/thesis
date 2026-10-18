"""Ports: what the use cases need from the outside world.

Adapters in ueba.adapters implement these. Add a port when a use case needs it,
not before.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Protocol

from ueba.domain.detections import Detection
from ueba.domain.events import NormalizedEvent
from ueba.domain.geo import GeoContext


class EventSource(Protocol):
    """Yields parsed (not yet correlated) events from one place: log files or the indexer.

    `skipped` counts records that were read but are not user actions, by reason,
    and `duplicates` counts identical raw records seen more than once (LOG-04, LOG-05).
    """

    skipped: Counter
    duplicates: int

    def events(self) -> Iterator[NormalizedEvent]: ...


class EventSink(Protocol):
    """Stores normalized events (Phase 2 output, Phase 4 input)."""

    def write(self, events: Iterable[NormalizedEvent]) -> int: ...


class GeoLookup(Protocol):
    """Looks up a public IP (Phase 2, CTX-01). Returns None when the database has no entry."""

    @property
    def provider(self) -> str: ...  # database name + version

    def lookup(self, ip: str) -> GeoContext | None: ...


class DetectionSink(Protocol):
    """Publishes detections so analysts can find them in Wazuh (Phase 6, UI-01)."""

    def publish(self, detections: Iterable[Detection]) -> None: ...
