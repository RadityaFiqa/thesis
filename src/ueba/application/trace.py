"""Use case: trace known actions to normalized events (LOG-01).

Given what was actually done (one expectation per HTTP request, with the request
id the proxy returned) and the normalized event stream, report for each action
whether a matching event exists and whether its action and outcome agree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ueba.domain.events import Action, NormalizedEvent, Outcome


@dataclass(frozen=True, slots=True)
class Expectation:
    step: str
    request_id: str
    action: Action
    outcome: Outcome
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class TraceResult:
    expectation: Expectation
    found: tuple[NormalizedEvent, ...]

    @property
    def matched(self) -> NormalizedEvent | None:
        exp = self.expectation
        for event in self.found:
            if event.action is exp.action and event.outcome is exp.outcome:
                return event
        return None

    @property
    def status(self) -> str:
        if not self.found:
            return "missing"
        return "ok" if self.matched else "mismatch"


def trace(
    expectations: Iterable[Expectation], events: Iterable[NormalizedEvent]
) -> list[TraceResult]:
    by_request: dict[str, list[NormalizedEvent]] = defaultdict(list)
    for event in events:
        if event.request_id:
            by_request[event.request_id].append(event)
    return [TraceResult(exp, tuple(by_request.get(exp.request_id, ()))) for exp in expectations]
