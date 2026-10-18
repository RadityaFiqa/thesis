"""Phase 4 features: determinism (FE-01), missing values (FE-02), no leakage (FE-03)."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from ueba.adapters.feature_store import read_rows, write_rows
from ueba.application.build_features import (
    FeatureConfig,
    FeatureStats,
    build_features,
    window_start,
)
from ueba.domain.events import Action, NormalizedEvent, Outcome, Provenance, SourceSystem
from ueba.domain.features import (
    BASIC_FEATURES,
    CONTEXTUAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_SPECS,
)
from ueba.domain.geo import GeoContext, GeoStatus

CFG = FeatureConfig(min_history_windows=2, min_history_events=4)
T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # 16:00 WIB, a Monday
_seq = iter(range(10**9))


def ev(at, action=Action.DOWNLOAD, outcome=Outcome.SUCCESS, *, user="alice", ip="36.86.63.1",
       resource="/a.txt", size=100, country="ID", effective=None):  # fmt: skip
    geo = (
        GeoContext(status=GeoStatus.RESOLVED, country=country)
        if country
        else GeoContext(status=GeoStatus.PRIVATE)
    )
    return NormalizedEvent(
        event_time=at,
        effective_time=effective,
        action=action,
        outcome=outcome,
        provenance=Provenance(SourceSystem.NEXTCLOUD_AUDIT, f"ref-{next(_seq):06d}", None),
        user_id=user,
        client_ip=ip,
        resource=resource,
        bytes_transferred=size,
        geo=geo,
    )


def history(user="alice", hours=(0, 1, 2), **kw):
    """One download per hour, same IP/country/file: an established normal pattern."""
    return [ev(T0 + timedelta(hours=h, minutes=5), user=user, **kw) for h in hours]


def row_at(rows, at, user="alice"):
    (row,) = [r for r in rows if r.user_id == user and r.window_start <= at < r.window_end]
    return row


# ------------------------------------------------------------------ windows (FE-01)
def test_windows_align_to_local_clock():
    t = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)  # 07:30 WIB
    assert window_start(t, FeatureConfig(window_minutes=60)) == datetime(
        2026, 11, 2, 0, 0, tzinfo=UTC
    )
    # a day window starts at local (WIB) midnight, i.e. 17:00 UTC the day before
    assert window_start(t, FeatureConfig(window_minutes=1440)) == datetime(
        2026, 11, 1, 17, 0, tzinfo=UTC
    )


def test_virtual_time_decides_the_window_and_the_hour():
    virtual = datetime(2026, 11, 20, 20, 15, tzinfo=UTC)  # 03:15 WIB
    (row,) = build_features([ev(T0, effective=virtual)], CFG)
    assert row.window_start == datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
    assert row.values["hour_of_day"] == 3


def test_same_input_in_any_order_gives_identical_rows(tmp_path):
    events = (
        history() + history(user="bob", hours=(0, 5)) + [ev(T0 + timedelta(hours=3), ip="5.39.1.1")]
    )
    shuffled = events[:]
    random.Random(7).shuffle(shuffled)
    a, b = build_features(events, CFG), build_features(shuffled, CFG)
    assert a == b
    assert write_rows(tmp_path / "a.jsonl", a) == write_rows(tmp_path / "b.jsonl", b)


# ------------------------------------------------------------------ no leakage (FE-03)
def test_future_events_never_change_earlier_rows():
    past = history(hours=range(6))
    future = [  # an "attack" later on: many downloads from a new country
        ev(T0 + timedelta(hours=8, minutes=m), ip="5.39.1.1", country="FR", resource=f"/x{m}")
        for m in range(30)
    ]
    only_past = build_features(past, CFG)
    with_future = build_features(past + future, CFG)
    cutoff = T0 + timedelta(hours=8)
    assert [r for r in with_future if r.window_start < cutoff] == only_past


def test_history_features_use_only_earlier_windows():
    rows = build_features(history() + [ev(T0 + timedelta(hours=3, minutes=5), ip="5.39.1.1",
                                            country="FR", resource="/new.txt")], CFG)  # fmt: skip
    first, second, third, fourth = rows
    # not enough history yet: unknown, not zero (FE-02)
    assert first.values["n_new_ips"] is None and second.values["n_new_ips"] is None
    # the third window has two earlier windows of history
    assert third.values["n_new_ips"] == 0 and third.values["n_new_resources"] == 0
    assert fourth.values["n_new_ips"] == 1
    assert fourth.values["n_new_countries"] == 1
    assert fourth.values["n_new_resources"] == 1
    assert fourth.values["actions_vs_user_mean"] == 1.0
    assert fourth.values["hours_since_last_activity"] == 1.0


def test_off_hours_needs_history_and_compares_with_the_users_own_hours():
    office = [ev(T0 + timedelta(days=d, minutes=10)) for d in range(5)]  # 16:xx WIB daily
    night = ev(T0 + timedelta(days=5, hours=12))  # 04:00 WIB
    rows = build_features(office + [night], CFG)
    assert rows[0].values["off_hours_ratio"] is None  # no history yet
    assert row_at(rows, night.event_time).values["off_hours_ratio"] == 1.0
    assert rows[4].values["off_hours_ratio"] == 0.0


# ------------------------------------------------------------------ missing values (FE-02)
def test_unmeasured_transfer_is_none_not_zero():
    (unmeasured,) = build_features([ev(T0, size=None)], CFG)
    assert unmeasured.values["bytes_downloaded"] is None
    assert unmeasured.values["n_transfers_unmeasured"] == 1
    (no_transfer,) = build_features([ev(T0, Action.ACCESS, size=None)], CFG)
    assert no_transfer.values["bytes_downloaded"] == 0  # nothing transferred: a real zero
    (failed,) = build_features([ev(T0, outcome=Outcome.FAILURE, size=None)], CFG)
    assert failed.values["bytes_downloaded"] == 0 and failed.values["n_failed_file_ops"] == 1


def test_private_or_unresolved_locations_never_count_as_new_countries():
    rows = build_features(
        history() + [ev(T0 + timedelta(hours=3), ip="10.0.0.5", country=None)], CFG
    )
    assert rows[-1].values["n_new_countries"] == 0


def test_rejected_credentials_count_as_failed_logins_but_not_as_actions():
    (row,) = build_features([ev(T0, Action.AUTH, Outcome.FAILURE, resource=None, size=None)], CFG)
    assert row.values["n_failed_logins"] == 1
    assert row.values["n_actions"] == 0
    assert row.values["failure_ratio"] == 1.0


def test_per_request_auth_other_and_userless_events_are_skipped():
    stats = FeatureStats()
    rows = build_features(
        [
            ev(T0, Action.AUTH),
            ev(T0, Action.OTHER),
            ev(T0, user=None),
            ev(T0, Action.UPLOAD),
        ],
        CFG,
        stats,
    )
    assert stats.used_events == 1 and len(rows) == 1
    assert dict(stats.skipped) == {"action_auth": 1, "action_other": 1, "no_user": 1}


# ------------------------------------------------------------------ rows and metadata
def test_warmup_windows_are_flagged():
    events = [ev(T0), ev(T0 + timedelta(days=6, hours=23)), ev(T0 + timedelta(days=8))]
    rows = build_features(events, FeatureConfig(warmup_days=7))
    assert [r.warmup for r in rows] == [True, True, False]


def test_every_feature_is_defined_and_no_ground_truth_leaks_in():
    assert len(FEATURE_SPECS) == len(set(FEATURE_NAMES))
    assert set(BASIC_FEATURES) | set(CONTEXTUAL_FEATURES) == set(FEATURE_NAMES)
    for spec in FEATURE_SPECS:
        assert spec.definition and spec.sources
    forbidden = ("label", "scenario", "episode", "attack", "phase", "malicious")
    assert not [n for n in FEATURE_NAMES if any(f in n for f in forbidden)]


def test_config_validation():
    with pytest.raises(ValueError):
        FeatureConfig(window_minutes=7)
    with pytest.raises(ValueError):
        FeatureConfig.from_dict({"window_minutes": 60, "window": 60})
    assert FeatureConfig().config_hash != FeatureConfig(window_minutes=15).config_hash


def test_rows_round_trip_through_the_store(tmp_path):
    rows = build_features(history() + [ev(T0 + timedelta(hours=3), size=None)], CFG)
    write_rows(tmp_path / "rows.jsonl", rows)
    assert list(read_rows(tmp_path / "rows.jsonl")) == rows
