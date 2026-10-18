"""Feature definitions for user-window rows (Phase 4, FE-01..FE-03).

Every feature has a definition, the event fields it comes from, and a
missing-value policy (FE-02). A value is None when it can't be computed; None
is never replaced by zero here (PRD section 6). Phase 5 decides imputation.

Only observable event data is used: nothing from the simulator's ground truth
(labels, scenario or episode ids) may ever become a feature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ueba.domain.events import Action

FEATURE_VERSION = "features/1"

# Actions a person performs. AUTH (per-request WebDAV authentication) measures
# request volume rather than behavior, and OTHER is mostly side effects; both are
# left out of the counts, except failed AUTH, which counts as a failed login.
USER_ACTIONS = frozenset(
    {
        Action.LOGIN,
        Action.LOGOUT,
        Action.UPLOAD,
        Action.DOWNLOAD,
        Action.ACCESS,
        Action.MKDIR,
        Action.RENAME,
        Action.DELETE,
        Action.SHARE,
    }
)
FILE_ACTIONS = frozenset(
    {Action.UPLOAD, Action.DOWNLOAD, Action.ACCESS, Action.MKDIR, Action.RENAME, Action.DELETE,
     Action.SHARE}
)  # fmt: skip


class Group(StrEnum):
    VOLUME = "volume"
    BREADTH = "breadth"
    OUTCOME = "outcome"
    TRANSFER = "transfer"
    TIME = "time"
    HISTORY = "history"


class Missing(StrEnum):
    """When a feature is None."""

    NEVER = "never"  # always computable for an active window
    NO_DENOMINATOR = "no_denominator"  # a ratio whose denominator is zero
    NOT_MEASURED = "not_measured"  # the logs did not record the quantity
    NO_HISTORY = "no_history"  # not enough past data for this user yet


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    group: Group
    definition: str
    sources: tuple[str, ...]
    missing: Missing
    contextual: bool = False  # needs user history or location (EVAL-01 compares with/without)


def _count(action: Action) -> FeatureSpec:
    return FeatureSpec(
        f"n_{action.value}",
        Group.VOLUME,
        f"number of {action.value} actions in the window (any outcome)",
        ("action",),
        Missing.NEVER,
    )


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "n_actions",
        Group.VOLUME,
        "number of user actions in the window (login, logout and file actions; any outcome)",
        ("action",),
        Missing.NEVER,
    ),
    *(
        _count(a)
        for a in (
            Action.UPLOAD,
            Action.DOWNLOAD,
            Action.ACCESS,
            Action.DELETE,
            Action.RENAME,
            Action.MKDIR,
            Action.SHARE,
            Action.LOGIN,
        )
    ),  # fmt: skip
    FeatureSpec(
        "n_distinct_resources",
        Group.BREADTH,
        "distinct files or folders touched by file actions",
        ("resource",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "n_distinct_folders",
        Group.BREADTH,
        "distinct parent folders of the resources touched",
        ("resource",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "n_distinct_ips",
        Group.BREADTH,
        "distinct client IPs (events without an IP are not counted)",
        ("client_ip",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "n_failed_logins",
        Group.OUTCOME,
        "failed web logins plus rejected per-request credentials",
        ("action", "outcome"),
        Missing.NEVER,
    ),
    FeatureSpec(
        "n_failed_file_ops",
        Group.OUTCOME,
        "file actions with outcome failure",
        ("action", "outcome"),
        Missing.NEVER,
    ),
    FeatureSpec(
        "failure_ratio",
        Group.OUTCOME,
        "failed actions / actions with a known outcome (including rejected credentials)",
        ("action", "outcome"),
        Missing.NO_DENOMINATOR,
    ),
    FeatureSpec(
        "bytes_uploaded",
        Group.TRANSFER,
        "sum of measured upload bytes; 0 if there were no uploads; None if uploads happened "
        "but none had a measured size",
        ("action", "bytes_transferred"),
        Missing.NOT_MEASURED,
    ),
    FeatureSpec(
        "bytes_downloaded",
        Group.TRANSFER,
        "as bytes_uploaded, for successful downloads",
        ("action", "bytes_transferred"),
        Missing.NOT_MEASURED,
    ),
    FeatureSpec(
        "n_transfers_unmeasured",
        Group.TRANSFER,
        "uploads and successful downloads without a measured size (quality indicator)",
        ("action", "bytes_transferred"),
        Missing.NEVER,
    ),
    FeatureSpec(
        "hour_of_day",
        Group.TIME,
        "local hour (configured UTC offset) of the window start",
        ("analysis_time",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "day_of_week",
        Group.TIME,
        "local day of the window start, 0 = Monday",
        ("analysis_time",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "is_weekend",
        Group.TIME,
        "1 if the local window start is Saturday or Sunday, else 0",
        ("analysis_time",),
        Missing.NEVER,
    ),
    FeatureSpec(
        "off_hours_ratio",
        Group.TIME,
        "share of the window's actions in local hours that are rare for this user "
        "(below the configured share of the user's past actions)",
        ("analysis_time",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "n_new_ips",
        Group.HISTORY,
        "client IPs in the window never seen for this user before the window",
        ("client_ip",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "n_new_countries",
        Group.HISTORY,
        "resolved countries in the window never seen for this user before the window "
        "(unresolved or private locations are ignored, CTX-02)",
        ("geo.country", "geo.status"),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "n_new_resources",
        Group.HISTORY,
        "resources in the window never touched by this user before the window",
        ("resource",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "actions_vs_user_mean",
        Group.HISTORY,
        "n_actions / mean n_actions over the user's past active windows",
        ("action",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "downloads_vs_user_mean",
        Group.HISTORY,
        "n_download / mean n_download over the user's past active windows "
        "(None while that mean is 0)",
        ("action",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
    FeatureSpec(
        "hours_since_last_activity",
        Group.HISTORY,
        "hours between the user's last action before the window and the window's first action",
        ("analysis_time",),
        Missing.NO_HISTORY,
        contextual=True,
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS)
BASIC_FEATURES: tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS if not s.contextual)
CONTEXTUAL_FEATURES: tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS if s.contextual)


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One user-window (the proposed evaluation unit, PRD section 7)."""

    user_id: str
    window_start: datetime
    window_end: datetime
    warmup: bool  # inside the history warm-up: kept for history, excluded from training
    values: dict[str, Any] = field(default_factory=dict)
    event_refs: tuple[str, ...] = ()  # provenance of the events behind the row (DET-01)

    def __post_init__(self) -> None:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if set(self.values) != set(FEATURE_NAMES):
            missing = set(FEATURE_NAMES) - set(self.values)
            extra = set(self.values) - set(FEATURE_NAMES)
            raise ValueError(f"feature set mismatch: missing {missing}, unexpected {extra}")
