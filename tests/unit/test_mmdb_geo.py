from types import SimpleNamespace

from ueba.adapters.mmdb_geo import MmdbGeoLookup
from ueba.domain.geo import GeoStatus


class FakeReader:
    def __init__(self, table):
        self.table = table

    def metadata(self):
        return SimpleNamespace(database_type="DBIP-City-Lite", build_epoch=1790000000)

    def get(self, ip):
        if ip == "bad":
            raise ValueError("not an IP")
        return self.table.get(ip)


JAKARTA = {
    "country": {"iso_code": "ID"},
    "subdivisions": [{"names": {"en": "Jakarta"}}],
    "city": {"names": {"en": "Jakarta"}},
    "location": {"latitude": -6.2, "longitude": 106.8},
}


def lookup(table=None):
    return MmdbGeoLookup("dbip-city-lite.mmdb", reader=FakeReader(table or {}))


def test_provider_records_database_and_build_date():
    assert lookup().provider == "DBIP-City-Lite built 2026-09-21 (dbip-city-lite.mmdb)"


def test_resolved_record():
    geo = lookup({"36.86.63.1": JAKARTA}).lookup("36.86.63.1")
    assert (geo.status, geo.country, geo.city, geo.latitude) == (
        GeoStatus.RESOLVED,
        "ID",
        "Jakarta",
        -6.2,
    )


def test_unknown_or_empty_records_are_not_found():
    geo = lookup({"1.1.1.1": {"continent": {"code": "OC"}}})
    assert geo.lookup("1.1.1.1") is None
    assert geo.lookup("8.8.8.8") is None
    assert geo.lookup("bad") is None
