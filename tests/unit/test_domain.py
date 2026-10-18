from datetime import UTC, datetime, timedelta

import pytest

from ueba.domain.detections import Detection, ScoreDirection, Severity
from ueba.domain.events import Action, NormalizedEvent, Outcome, Provenance, SourceSystem
from ueba.domain.geo import GeoContext, GeoStatus, classify_ip

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


def make_event(**overrides):
    values = dict(
        event_time=T0,
        ingest_time=T0 + timedelta(seconds=4),
        action=Action.UPLOAD,
        outcome=Outcome.SUCCESS,
        provenance=Provenance(SourceSystem.NEXTCLOUD_AUDIT, "doc-1", "req-1"),
    )
    values.update(overrides)
    return NormalizedEvent(**values)


def test_event_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_event(event_time=datetime(2026, 10, 18, 9, 0))


def test_event_reports_collection_lag():
    assert make_event().collection_lag_seconds == 4


def test_unknown_fields_stay_none():
    event = make_event()
    assert event.user_id is None and event.bytes_transferred is None


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        (None, GeoStatus.MISSING),
        ("", GeoStatus.MISSING),
        ("not-an-ip", GeoStatus.INVALID),
        ("172.30.10.1", GeoStatus.PRIVATE),
        ("127.0.0.1", GeoStatus.PRIVATE),
        ("fe80::1", GeoStatus.PRIVATE),
        ("8.8.8.8", None),
    ],
)
def test_classify_ip(ip, expected):
    assert classify_ip(ip) is expected


def test_unresolved_geo_cannot_carry_a_location():
    with pytest.raises(ValueError, match="CTX-02"):
        GeoContext(status=GeoStatus.PRIVATE, city="Jakarta")


def make_detection(**overrides):
    values = dict(
        user_id="alice",
        window_start=T0,
        window_end=T0 + timedelta(hours=1),
        model_version="if-1",
        feature_version="f-1",
        anomaly_score=0.7,
        score_direction=ScoreDirection.HIGHER_IS_MORE_ANOMALOUS,
        threshold=0.6,
        risk=0.8,
        severity=Severity.HIGH,
        created_at=T0 + timedelta(hours=1, minutes=1),
        evidence=("new source IP",),
        source_event_refs=("doc-1",),
    )
    values.update(overrides)
    return Detection(**values)


def test_detection_id_is_stable_across_reruns():
    first = make_detection()
    rerun = make_detection(created_at=T0 + timedelta(days=1), anomaly_score=0.71)
    assert first.detection_id == rerun.detection_id


def test_detection_id_changes_with_model_version():
    assert make_detection().detection_id != make_detection(model_version="if-2").detection_id


def test_detection_window_must_be_positive():
    with pytest.raises(ValueError):
        make_detection(window_end=T0)
