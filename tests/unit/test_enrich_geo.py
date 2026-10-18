from datetime import UTC, datetime

from ueba.application.enrich_geo import enrich_geo
from ueba.domain.events import Action, NormalizedEvent, Outcome, Provenance, SourceSystem
from ueba.domain.geo import GeoContext, GeoStatus

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


class FakeLookup:
    provider = "fake-geo 2026-10"

    def __init__(self, table):
        self.table = table
        self.queried = []

    def lookup(self, ip):
        self.queried.append(ip)
        return self.table.get(ip)


def event(ip):
    return NormalizedEvent(
        event_time=T0,
        ingest_time=T0,
        action=Action.LOGIN,
        outcome=Outcome.SUCCESS,
        provenance=Provenance(SourceSystem.NEXTCLOUD_AUDIT, "doc", None),
        client_ip=ip,
    )


def test_private_and_missing_ips_are_never_looked_up():
    lookup = FakeLookup({})
    results = list(enrich_geo([event("10.0.0.5"), event(None)], lookup))
    assert [e.geo.status for e in results] == [GeoStatus.PRIVATE, GeoStatus.MISSING]
    assert lookup.queried == []


def test_public_ip_is_resolved_or_marked_not_found():
    jakarta = GeoContext(
        status=GeoStatus.RESOLVED, country="ID", city="Jakarta", provider=FakeLookup.provider
    )
    lookup = FakeLookup({"36.86.63.1": jakarta})
    found, missing = enrich_geo([event("36.86.63.1"), event("8.8.8.8")], lookup)
    assert found.geo == jakarta
    assert missing.geo.status is GeoStatus.NOT_FOUND and missing.geo.city is None
    assert missing.geo.provider == "fake-geo 2026-10"
