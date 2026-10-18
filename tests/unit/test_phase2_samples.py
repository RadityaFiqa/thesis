"""End to end on real samples: each sampled action traces to the right event (LOG-01)."""

import json
from pathlib import Path

import pytest

from ueba.adapters.jsonl_store import SampleFolderSource, event_from_dict, event_to_dict
from ueba.application.normalize import NormalizeStats, correlate
from ueba.application.trace import Expectation, trace
from ueba.domain.events import Action, Outcome

SAMPLES = Path(__file__).parent.parent / "fixtures" / "phase2-samples"


@pytest.fixture(scope="module")
def normalized():
    source = SampleFolderSource(SAMPLES)
    stats = NormalizeStats()
    events = list(correlate(source.events(), stats))
    return events, stats, source


def expectations():
    for line in (SAMPLES / "manifest.jsonl").read_text().splitlines():
        m = json.loads(line)
        yield Expectation(
            m["step"],
            m["request_id"],
            Action(m["expected_action"]),
            Outcome(m["expected_outcome"]),
            m["user"],
        )


def test_every_sampled_action_traces(normalized):
    events, _, _ = normalized
    results = trace(expectations(), events)
    assert len(results) == 13
    assert {r.expectation.step: r.status for r in results} == {
        r.expectation.step: "ok" for r in results
    }
    assert all(r.matched.user_id == "p2-sampler" for r in results)


def test_failures_visible_only_in_the_proxy_are_kept(normalized):
    events, stats, _ = normalized
    missing = [e for e in events if e.resource and e.resource.endswith("does-not-exist.txt")]
    assert len(missing) == 1 and missing[0].outcome is Outcome.FAILURE
    assert stats.proxy_only == 2  # failed download + folder listing


def test_nothing_is_dropped_silently(normalized):
    _, stats, source = normalized
    # every parsed event is accounted for exactly once
    assert (
        stats.input_events == stats.output_events + stats.merged_duplicates + stats.proxy_superseded
    )
    # every unparsed record has a known reason
    assert set(source.skipped) <= {
        "login_attempt_precursor",
        "internal_cache",
        "session_churn",
        "share_interaction_duplicate",
        "not_a_user_action",
    }


def test_repeated_raw_lines_are_counted_and_dropped(tmp_path):
    # e.g. a line resent after a manager outage (LOG-05)
    for name in ("audit.jsonl", "access.jsonl"):
        lines = (SAMPLES / name).read_text().splitlines()
        (tmp_path / name).write_text("\n".join(lines + lines[:3]) + "\n")
    source = SampleFolderSource(tmp_path)
    events = list(correlate(source.events()))
    clean = list(correlate(SampleFolderSource(SAMPLES).events()))
    assert source.duplicates == 6
    assert events == clean


def test_jsonl_round_trip(normalized):
    events, _, _ = normalized
    assert [event_from_dict(event_to_dict(e)) for e in events] == events
