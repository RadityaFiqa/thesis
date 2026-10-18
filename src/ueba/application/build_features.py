"""Use case: user-window feature rows from normalized events (FE-01, FE-02, FE-03).

Determinism (FE-01): events are sorted by (analysis_time, raw_ref) and users and
windows are processed in sorted order, so the same input and config always give
the same rows, whatever order the events arrive in.

No leakage (FE-03): each user's windows are processed in time order, and the
user's history (known IPs, countries, resources, usual hours, past volumes) is
updated only after a window's features are computed. A window therefore sees
only data from before it. Adding later events never changes earlier rows
(tested).

Only active windows (at least one counted event) produce a row.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from ueba.domain.events import Action, NormalizedEvent, Outcome
from ueba.domain.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    FILE_ACTIONS,
    USER_ACTIONS,
    FeatureRow,
)
from ueba.domain.geo import GeoStatus


@dataclass(frozen=True)
class FeatureConfig:
    window_minutes: int = 60
    warmup_days: int = 7
    utc_offset: str = "+07:00"  # local time for hour/day features; WIB has no DST
    rare_hour_share: float = 0.05  # an hour is "usual" if >= this share of past actions
    min_history_events: int = 20  # before off_hours_ratio is computed
    min_history_windows: int = 3  # before history features are computed

    def __post_init__(self) -> None:
        if self.window_minutes <= 0 or 1440 % self.window_minutes:
            raise ValueError("window_minutes must divide a day (e.g. 15, 60, 1440)")
        if self.warmup_days < 0 or self.min_history_windows < 1 or self.min_history_events < 1:
            raise ValueError("warmup_days >= 0, min_history_windows >= 1, min_history_events >= 1")
        if not 0 < self.rare_hour_share < 1:
            raise ValueError("rare_hour_share must be between 0 and 1")
        _ = self.tz  # validates utc_offset

    @property
    def tz(self) -> timezone:
        sign = -1 if self.utc_offset.startswith("-") else 1
        hh, mm = self.utc_offset.lstrip("+-").split(":")
        return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))

    @property
    def config_hash(self) -> str:
        canonical = json.dumps(
            {"feature_version": FEATURE_VERSION, **asdict(self)},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FeatureConfig:
        known = {k: v for k, v in d.items() if not k.startswith("$")}
        unknown = set(known) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown feature config keys: {sorted(unknown)}")
        return cls(**known)


@dataclass
class FeatureStats:
    input_events: int = 0
    used_events: int = 0
    skipped: Counter = field(default_factory=Counter)
    users: int = 0
    windows: int = 0
    warmup_windows: int = 0
    missing: Counter = field(default_factory=Counter)  # feature -> rows where it is None


@dataclass
class _History:
    """What is known about a user from windows before the current one."""

    ips: set[str] = field(default_factory=set)
    countries: set[str] = field(default_factory=set)
    resources: set[str] = field(default_factory=set)
    hour_counts: Counter = field(default_factory=Counter)
    window_actions: list[int] = field(default_factory=list)
    window_downloads: list[int] = field(default_factory=list)
    last_time: datetime | None = None


def window_start(t: datetime, cfg: FeatureConfig) -> datetime:
    """Start of the window containing t, aligned to local (configured offset) clock time."""
    offset = cfg.tz.utcoffset(None).total_seconds()
    width = cfg.window_minutes * 60
    local = t.timestamp() + offset
    return datetime.fromtimestamp((local // width) * width - offset, tz=UTC)


def _local_hour(t: datetime, cfg: FeatureConfig) -> int:
    return t.astimezone(cfg.tz).hour


def _parent(resource: str) -> str:
    head = resource.rstrip("/").rsplit("/", 1)[0]
    return head or "/"


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 6) if den else None


def _counted(e: NormalizedEvent) -> str | None:
    """None if the event is used, else the reason it is skipped."""
    if not e.user_id:
        return "no_user"
    if e.action in USER_ACTIONS:
        return None
    if e.action is Action.AUTH and e.outcome is Outcome.FAILURE:
        return None  # a rejected credential is a failed login
    return f"action_{e.action.value}"


def build_features(
    events: Iterable[NormalizedEvent], cfg: FeatureConfig, stats: FeatureStats | None = None
) -> list[FeatureRow]:
    stats = stats if stats is not None else FeatureStats()
    used: list[NormalizedEvent] = []
    for e in events:
        stats.input_events += 1
        reason = _counted(e)
        if reason:
            stats.skipped[reason] += 1
        else:
            used.append(e)
    stats.used_events = len(used)
    if not used:
        return []
    used.sort(key=lambda e: (e.analysis_time, e.provenance.raw_ref))

    first_window = window_start(used[0].analysis_time, cfg)
    warmup_end = first_window + timedelta(days=cfg.warmup_days)
    width = timedelta(minutes=cfg.window_minutes)

    by_user: dict[str, dict[datetime, list[NormalizedEvent]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for e in used:
        by_user[e.user_id][window_start(e.analysis_time, cfg)].append(e)

    rows: list[FeatureRow] = []
    for user in sorted(by_user):
        hist = _History()
        for ws in sorted(by_user[user]):
            evs = by_user[user][ws]
            values = _features(evs, ws, hist, cfg)
            rows.append(
                FeatureRow(
                    user_id=user,
                    window_start=ws,
                    window_end=ws + width,
                    warmup=ws < warmup_end,
                    values=values,
                    event_refs=tuple(e.provenance.raw_ref for e in evs),
                )
            )
            _remember(hist, evs, cfg)  # only now does this window become history

    rows.sort(key=lambda r: (r.window_start, r.user_id))
    stats.users = len(by_user)
    stats.windows = len(rows)
    stats.warmup_windows = sum(r.warmup for r in rows)
    for r in rows:
        for name, value in r.values.items():
            if value is None:
                stats.missing[name] += 1
    return rows


def _features(
    evs: list[NormalizedEvent], ws: datetime, hist: _History, cfg: FeatureConfig
) -> dict[str, Any]:
    actions = [e for e in evs if e.action in USER_ACTIONS]
    by_action = Counter(e.action for e in actions)
    file_evs = [e for e in evs if e.action in FILE_ACTIONS]
    resources = {e.resource for e in file_evs if e.resource}
    ips = {e.client_ip for e in evs if e.client_ip}
    countries = {
        e.geo.country
        for e in evs
        if e.geo is not None and e.geo.status is GeoStatus.RESOLVED and e.geo.country
    }
    failures = [e for e in evs if e.outcome is Outcome.FAILURE]
    known_outcome = [e for e in evs if e.outcome is not Outcome.UNKNOWN]

    def transfer(action: Action) -> tuple[int | None, int]:
        done = [e for e in evs if e.action is action and e.outcome is Outcome.SUCCESS]
        measured = [e.bytes_transferred for e in done if e.bytes_transferred is not None]
        if not done:
            return 0, 0  # truly nothing transferred
        return (sum(measured) if measured else None), len(done) - len(measured)

    up_bytes, up_unmeasured = transfer(Action.UPLOAD)
    down_bytes, down_unmeasured = transfer(Action.DOWNLOAD)

    local_start = ws.astimezone(cfg.tz)
    has_history = len(hist.window_actions) >= cfg.min_history_windows
    hour_total = sum(hist.hour_counts.values())
    if hour_total >= cfg.min_history_events and actions:
        usual = {h for h, c in hist.hour_counts.items() if c / hour_total >= cfg.rare_hour_share}
        off = sum(1 for e in actions if _local_hour(e.analysis_time, cfg) not in usual)
        off_hours_ratio = _ratio(off, len(actions))
    else:
        off_hours_ratio = None

    def vs_mean(value: int, past: list[int]) -> float | None:
        if not has_history:
            return None
        mean = sum(past) / len(past)
        return _ratio(value, mean)

    values: dict[str, Any] = {
        "n_actions": len(actions),
        "n_upload": by_action[Action.UPLOAD],
        "n_download": by_action[Action.DOWNLOAD],
        "n_access": by_action[Action.ACCESS],
        "n_delete": by_action[Action.DELETE],
        "n_rename": by_action[Action.RENAME],
        "n_mkdir": by_action[Action.MKDIR],
        "n_share": by_action[Action.SHARE],
        "n_login": by_action[Action.LOGIN],
        "n_distinct_resources": len(resources),
        "n_distinct_folders": len({_parent(r) for r in resources}),
        "n_distinct_ips": len(ips),
        "n_failed_logins": sum(1 for e in failures if e.action in (Action.LOGIN, Action.AUTH)),
        "n_failed_file_ops": sum(1 for e in failures if e.action in FILE_ACTIONS),
        "failure_ratio": _ratio(len(failures), len(known_outcome)),
        "bytes_uploaded": up_bytes,
        "bytes_downloaded": down_bytes,
        "n_transfers_unmeasured": up_unmeasured + down_unmeasured,
        "hour_of_day": local_start.hour,
        "day_of_week": local_start.weekday(),
        "is_weekend": int(local_start.weekday() >= 5),
        "off_hours_ratio": off_hours_ratio,
        "n_new_ips": len(ips - hist.ips) if has_history else None,
        "n_new_countries": len(countries - hist.countries) if has_history else None,
        "n_new_resources": len(resources - hist.resources) if has_history else None,
        "actions_vs_user_mean": vs_mean(len(actions), hist.window_actions),
        "downloads_vs_user_mean": vs_mean(by_action[Action.DOWNLOAD], hist.window_downloads),
        "hours_since_last_activity": (
            round((evs[0].analysis_time - hist.last_time).total_seconds() / 3600, 6)
            if hist.last_time is not None
            else None
        ),
    }
    assert tuple(values) == FEATURE_NAMES, "keep values in FEATURE_SPECS order"
    return values


def _remember(hist: _History, evs: list[NormalizedEvent], cfg: FeatureConfig) -> None:
    actions = [e for e in evs if e.action in USER_ACTIONS]
    hist.ips |= {e.client_ip for e in evs if e.client_ip}
    hist.countries |= {
        e.geo.country
        for e in evs
        if e.geo is not None and e.geo.status is GeoStatus.RESOLVED and e.geo.country
    }
    hist.resources |= {e.resource for e in evs if e.action in FILE_ACTIONS and e.resource}
    hist.hour_counts.update(_local_hour(e.analysis_time, cfg) for e in actions)
    hist.window_actions.append(len(actions))
    hist.window_downloads.append(sum(1 for e in actions if e.action is Action.DOWNLOAD))
    hist.last_time = max(e.analysis_time for e in evs)
