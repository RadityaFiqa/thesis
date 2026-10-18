"""Normalized event contract (PRD section 6, LOG-03, LOG-04)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ueba.domain.geo import GeoContext


class Action(StrEnum):
    LOGIN = "login"  # interactive web login (POST /login)
    AUTH = "auth"  # per-request authentication by WebDAV/API clients; not a login
    LOGOUT = "logout"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    ACCESS = "access"  # listing / metadata (PROPFIND)
    MKDIR = "mkdir"
    RENAME = "rename"
    DELETE = "delete"
    SHARE = "share"
    OTHER = "other"


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"  # never assume success when the log doesn't say (PRD section 6)


class SourceSystem(StrEnum):
    NEXTCLOUD_AUDIT = "nextcloud_audit"
    NEXTCLOUD_APP = "nextcloud_app"
    PROXY_ACCESS = "proxy_access"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where an event came from, so every derived value can be traced to raw evidence."""

    source: SourceSystem
    raw_ref: str  # e.g. indexer document id, or file path + offset
    source_event_id: str | None  # Nextcloud reqId, proxy request id, ...


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """One observed action. Unknown values stay None; they are never filled with defaults."""

    event_time: datetime  # UTC, from the source
    action: Action
    outcome: Outcome
    provenance: Provenance
    ingest_time: datetime | None = None  # UTC, when the SIEM processed it; None if unknown
    user_id: str | None = None
    client_ip: str | None = None
    resource: str | None = None  # file path or other resource reference
    user_agent: str | None = None
    session_id: str | None = None
    response_code: int | None = None
    bytes_transferred: int | None = None  # only when the log really measures it
    geo: GeoContext | None = None
    parse_issues: tuple[str, ...] = field(default_factory=tuple)  # LOG-04 quality flags

    def __post_init__(self) -> None:
        for name in ("event_time", "ingest_time"):
            value: datetime | None = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware (UTC)")

    @property
    def request_id(self) -> str | None:
        return self.provenance.source_event_id

    @property
    def collection_lag_seconds(self) -> float | None:
        """Source-to-SIEM delay (LOG-05); None when the ingest time is unknown."""
        if self.ingest_time is None:
            return None
        return (self.ingest_time - self.event_time).total_seconds()
