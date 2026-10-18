"""Use case: correlate audit and proxy events into one stream of user actions (LOG-01..05).

Audit and proxy records of the same HTTP request share a request id. For each request:
- audit events are the authoritative user actions; proxy data adds what only
  the proxy knows (HTTP status, bytes transferred, user agent);
- if the audit log recorded no user action (failed download, folder listing),
  the proxy event is kept instead, so failures are not lost (SIM-05);
- repeated identical actions within one request are merged (an upload logs
  "created" and "written to").
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace

from ueba.domain.events import Action, NormalizedEvent, Outcome, SourceSystem

_TRANSFER_ACTIONS = {Action.UPLOAD, Action.DOWNLOAD}


@dataclass
class NormalizeStats:
    """Counts for the data-quality report (LOG-04, LOG-05)."""

    input_events: int = 0
    output_events: int = 0
    merged_duplicates: int = 0
    proxy_superseded: int = 0  # proxy events replaced by the audit view of the same request
    proxy_only: int = 0
    audit_without_proxy: int = 0
    by_action: Counter = field(default_factory=Counter)


def correlate(
    events: Iterable[NormalizedEvent], stats: NormalizeStats | None = None
) -> Iterator[NormalizedEvent]:
    stats = stats if stats is not None else NormalizeStats()
    by_request: dict[str, list[NormalizedEvent]] = defaultdict(list)
    loose: list[NormalizedEvent] = []
    for event in events:
        stats.input_events += 1
        (by_request[event.request_id] if event.request_id else loose).append(event)

    out: list[NormalizedEvent] = []
    for group in by_request.values():
        out.extend(_merge_request(group, stats))
    out.extend(loose)
    out.sort(key=lambda e: (e.event_time, e.provenance.raw_ref))
    for event in out:
        stats.output_events += 1
        stats.by_action[event.action.value] += 1
        yield event


def _merge_request(group: list[NormalizedEvent], stats: NormalizeStats) -> list[NormalizedEvent]:
    audit = [e for e in group if e.provenance.source is SourceSystem.NEXTCLOUD_AUDIT]
    proxy = [e for e in group if e.provenance.source is SourceSystem.PROXY_ACCESS]
    http = proxy[0] if proxy else None

    merged: dict[tuple, NormalizedEvent] = {}
    for event in audit:
        key = (event.action, event.outcome, event.resource, event.user_id)
        if key in merged:
            stats.merged_duplicates += 1
            continue
        merged[key] = (
            _enrich(event, http)
            if http
            else replace(event, parse_issues=(*event.parse_issues, "no_proxy_record"))
        )
        if http is None:
            stats.audit_without_proxy += 1

    # Keep the proxy view when the audit log has no user action for this request
    user_actions = [e for e in merged.values() if e.action not in {Action.AUTH, Action.OTHER}]
    auth_failed = any(
        e.action is Action.AUTH and e.outcome is Outcome.FAILURE for e in merged.values()
    )
    keep_proxy = http is not None and not user_actions and not auth_failed
    if keep_proxy:  # (a rejected credential is already the event)
        merged[("proxy",)] = replace(http, parse_issues=(*http.parse_issues, "proxy_only"))
        stats.proxy_only += 1
    stats.proxy_superseded += len(proxy) - (1 if keep_proxy else 0)
    return list(merged.values())


def _enrich(event: NormalizedEvent, http: NormalizedEvent) -> NormalizedEvent:
    return replace(
        event,
        response_code=http.response_code,
        bytes_transferred=http.bytes_transferred if event.action in _TRANSFER_ACTIONS else None,
        user_agent=event.user_agent or http.user_agent,
        client_ip=event.client_ip or http.client_ip,
        # The audit log has no virtual time; it belongs to the request (decision 0008)
        effective_time=event.effective_time or http.effective_time,
        parse_issues=(
            *event.parse_issues,
            *(i for i in http.parse_issues if i == "invalid_sim_time"),
        ),
    )
