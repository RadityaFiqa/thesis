"""Use case: add location context to events (PRD CTX-01, CTX-02)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import replace

from ueba.application.ports import GeoLookup
from ueba.domain.events import NormalizedEvent
from ueba.domain.geo import GeoContext, GeoStatus, classify_ip


def enrich_geo(events: Iterable[NormalizedEvent], lookup: GeoLookup) -> Iterator[NormalizedEvent]:
    """Attach a GeoContext to each event.

    Private, missing and invalid IPs are never looked up, and a failed lookup stays
    NOT_FOUND: no location is ever invented (CTX-02).
    """
    for event in events:
        status = classify_ip(event.client_ip)
        if status is not None:
            geo = GeoContext(status=status, provider=lookup.provider)
        else:
            geo = lookup.lookup(event.client_ip) or GeoContext(
                status=GeoStatus.NOT_FOUND, provider=lookup.provider
            )
        yield replace(event, geo=geo)
