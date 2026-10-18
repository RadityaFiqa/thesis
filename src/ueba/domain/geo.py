"""Location context for client IPs (PRD CTX-01, CTX-02).

A lookup result is enrichment, not proof of where a user physically is.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import StrEnum


class GeoStatus(StrEnum):
    RESOLVED = "resolved"
    PRIVATE = "private"        # RFC 1918, loopback, link-local, ...: no lookup is attempted
    NOT_FOUND = "not_found"    # public, but the database has no entry
    INVALID = "invalid"        # not an IP address
    MISSING = "missing"        # the event had no client IP


@dataclass(frozen=True, slots=True)
class GeoContext:
    status: GeoStatus
    country: str | None = None
    region: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    provider: str | None = None    # database name + version, recorded for reproducibility

    def __post_init__(self) -> None:
        located = any(v is not None for v in (self.country, self.region, self.city,
                                               self.latitude, self.longitude))
        if located and self.status is not GeoStatus.RESOLVED:
            raise ValueError(f"a {self.status} result must not carry a location (CTX-02)")


def classify_ip(value: str | None) -> GeoStatus | None:
    """Status for IPs that must not be looked up, or None if a lookup is appropriate."""
    if not value:
        return GeoStatus.MISSING
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return GeoStatus.INVALID
    if not ip.is_global:
        return GeoStatus.PRIVATE
    return None
