"""GeoLookup over a MaxMind-format (.mmdb) city database (PRD CTX-01).

Works with GeoLite2-City or DB-IP City Lite. The provider string records the
database type and build date, so every enriched event says which data produced it.
Needs the optional dependency: pip install -e ".[geo]".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ueba.domain.geo import GeoContext, GeoStatus


class MmdbGeoLookup:
    def __init__(self, path: Path, reader: Any = None) -> None:
        if reader is None:
            import maxminddb  # optional dependency, imported only when used

            reader = maxminddb.open_database(str(path))
        self._reader = reader
        meta = reader.metadata()
        built = datetime.fromtimestamp(meta.build_epoch, tz=UTC).date().isoformat()
        self._provider = f"{meta.database_type} built {built} ({Path(path).name})"

    @property
    def provider(self) -> str:
        return self._provider

    def lookup(self, ip: str) -> GeoContext | None:
        try:
            rec = self._reader.get(ip)
        except ValueError:
            return None
        if not rec:
            return None
        location = rec.get("location") or {}
        subdivisions = rec.get("subdivisions") or [{}]
        country = (rec.get("country") or {}).get("iso_code")
        region = (subdivisions[0].get("names") or {}).get("en")
        city = ((rec.get("city") or {}).get("names") or {}).get("en")
        lat, lon = location.get("latitude"), location.get("longitude")
        if country is None and city is None and lat is None:
            return None
        return GeoContext(
            status=GeoStatus.RESOLVED,
            country=country,
            region=region,
            city=city,
            latitude=lat,
            longitude=lon,
            provider=self._provider,
        )
