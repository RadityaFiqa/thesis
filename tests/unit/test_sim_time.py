"""Virtual time from the simulation path (decision 0008)."""

from datetime import UTC, datetime

from ueba.adapters import nextcloud_logs
from ueba.application.normalize import correlate

DAV = "/remote.php/dav/files/alice"


def proxy(sim_time=None, *, method="GET", status=200):
    rec = {
        "ts": 1792318800.25,
        "request_id": "r1",
        "status": status,
        "size": 10,
        "request": {"client_ip": "36.86.63.1", "method": method, "uri": f"{DAV}/a.txt"},
    }
    if sim_time is not None:
        rec["sim_time"] = sim_time
    return nextcloud_logs.parse_proxy(rec, raw_ref="p").event


def audit():
    return nextcloud_logs.parse_audit(
        {
            "reqId": "r1",
            "time": "2026-10-18T10:00:00.5+00:00",
            "remoteAddr": "36.86.63.1",
            "user": "alice",
            "method": "GET",
            "url": f"{DAV}/a.txt",
            "message": 'File with id "5" accessed: "/alice/files/a.txt"',
        },
        raw_ref="a",
    ).event


def test_real_traffic_has_no_virtual_time():
    event = proxy()
    assert event.effective_time is None
    assert event.analysis_time == event.event_time


def test_sim_time_becomes_effective_time_and_keeps_the_real_clock():
    event = proxy("2026-11-02T03:15:00+07:00")
    assert event.effective_time == datetime(2026, 11, 1, 20, 15, tzinfo=UTC)
    assert event.analysis_time == event.effective_time
    assert event.event_time == datetime.fromtimestamp(1792318800.25, tz=UTC)


def test_audit_event_inherits_the_requests_virtual_time():
    (merged,) = correlate([audit(), proxy("2026-11-02T03:15:00+07:00")])
    assert merged.provenance.source.value == "nextcloud_audit"
    assert merged.effective_time == datetime(2026, 11, 1, 20, 15, tzinfo=UTC)
    # lag stays on real clocks
    assert merged.collection_lag_seconds is None


def test_invalid_or_naive_sim_time_is_flagged_not_used():
    for bad in ("tomorrow", "2026-11-02T03:15:00"):
        event = proxy(bad)
        assert event.effective_time is None
        assert "invalid_sim_time" in event.parse_issues
    (merged,) = correlate([audit(), proxy("tomorrow")])
    assert merged.effective_time is None and "invalid_sim_time" in merged.parse_issues


def test_empty_header_from_the_listener_means_no_virtual_time():
    # Caddy logs an empty string when the simulator sent no X-Sim-Time
    event = proxy("")
    assert event.effective_time is None and "invalid_sim_time" not in event.parse_issues
