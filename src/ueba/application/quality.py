"""Use case: data-quality report for a normalized event stream (LOG-04, LOG-05)."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from typing import Any

from ueba.application.normalize import NormalizeStats
from ueba.domain.events import NormalizedEvent


def _percentile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    return statistics.quantiles(sorted_values, n=100, method="inclusive")[int(q) - 1]


def quality_report(
    events: Iterable[NormalizedEvent],
    stats: NormalizeStats,
    skipped: Counter,
    duplicates: int,
) -> dict[str, Any]:
    events = list(events)
    lags = sorted(lag for e in events if (lag := e.collection_lag_seconds) is not None)
    issues = Counter(issue for e in events for issue in e.parse_issues)
    missing = Counter(
        name
        for e in events
        for name in ("user_id", "client_ip", "response_code")
        if getattr(e, name) is None
    )
    lag: dict[str, Any] = {"measured": len(lags)}
    if lags:
        lag |= {
            "min_s": round(lags[0], 3),
            "p50_s": round(_percentile(lags, 50), 3),
            "p95_s": round(_percentile(lags, 95), 3),
            "max_s": round(lags[-1], 3),
        }
    return {
        "events": len(events),
        "by_action": dict(stats.by_action),
        "outcomes": dict(Counter(e.outcome.value for e in events)),
        "collection_lag": lag,
        "duplicates_dropped": duplicates,
        "merged_within_request": stats.merged_duplicates,
        "proxy_superseded": stats.proxy_superseded,
        "proxy_only_events": stats.proxy_only,
        "audit_without_proxy": stats.audit_without_proxy,
        "skipped_records": dict(skipped),
        "parse_issues": dict(issues),
        "missing_fields": dict(missing),
    }
