"""`ueba` command. Each phase adds a subcommand here (normalize, simulate, features, ...)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ueba import __version__
from ueba.adapters.jsonl_store import JsonlEventSink, SampleFolderSource, read_events
from ueba.adapters.mmdb_geo import MmdbGeoLookup
from ueba.adapters.wazuh_indexer import IndexerClient, IndexerConfig, IndexerEventSource
from ueba.application.enrich_geo import enrich_geo
from ueba.application.normalize import NormalizeStats, correlate
from ueba.application.quality import quality_report
from ueba.application.trace import Expectation, trace
from ueba.domain.events import Action, Outcome
from ueba.entrypoints import features_cmd


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _indexer_config() -> IndexerConfig:
    password = os.environ.get("UEBA_INDEXER_PASSWORD")
    if not password:
        sys.exit("UEBA_INDEXER_PASSWORD is not set (on the VPS use infra/scripts/ueba.sh)")
    return IndexerConfig(
        url=os.environ.get("UEBA_INDEXER_URL", "https://127.0.0.1:9200"),
        user=os.environ.get("UEBA_INDEXER_USER", "admin"),
        password=password,
        ca_file=os.environ.get("UEBA_INDEXER_CA") or None,
        insecure=os.environ.get("UEBA_INDEXER_INSECURE") == "1",
    )


def cmd_normalize(args: argparse.Namespace) -> int:
    if args.samples:
        source = SampleFolderSource(Path(args.samples))
    else:
        until = _utc(args.until) if args.until else datetime.now(UTC)
        since = _utc(args.since) if args.since else until - timedelta(hours=24)
        source = IndexerEventSource(IndexerClient(_indexer_config()), since, until)

    stats = NormalizeStats()
    events = list(correlate(source.events(), stats))
    if args.geoip:
        events = list(enrich_geo(events, MmdbGeoLookup(Path(args.geoip))))
    out = Path(args.out)
    JsonlEventSink(out).write(events)
    report = quality_report(events, stats, source.skipped, source.duplicates)
    report["geo_status"] = dict(Counter(e.geo.status.value for e in events if e.geo))
    report_path = out.with_suffix(".quality.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{len(events)} events -> {out}")
    print(f"quality report -> {report_path}")
    print(json.dumps(report, indent=2))
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    expectations = []
    for line in Path(args.manifest).read_text(encoding="utf-8").splitlines():
        if line.strip():
            m = json.loads(line)
            expectations.append(
                Expectation(
                    m["step"],
                    m["request_id"],
                    Action(m["expected_action"]),
                    Outcome(m["expected_outcome"]),
                    m.get("user"),
                )
            )
    results = trace(expectations, read_events(Path(args.events)))
    for r in results:
        e = r.matched or (r.found[0] if r.found else None)
        seen = f"{e.action.value}/{e.outcome.value} {e.user_id} {e.resource or ''}" if e else "-"
        exp = r.expectation
        lag = e.collection_lag_seconds if e else None
        lag_s = f"{lag:6.2f}s" if lag is not None else "      -"
        print(
            f"{r.status:9} {exp.step:18} expect {exp.action.value}/{exp.outcome.value:8}"
            f" lag {lag_s}  got {seen}"
        )
    ok = sum(r.status == "ok" for r in results)
    print(f"\n{ok}/{len(results)} actions traced")
    return 0 if ok == len(results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ueba", description=__doc__)
    parser.add_argument("--version", action="version", version=f"ueba {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser(
        "normalize", help="parse + correlate events, write JSONL and a quality report"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--samples", metavar="DIR", help="sampler output folder")
    src.add_argument("--indexer", action="store_true", help="read from the Wazuh indexer")
    p.add_argument("--since", help="indexer: start (ISO time, UTC; default 24 h before --until)")
    p.add_argument("--until", help="indexer: end (ISO time, UTC; default now)")
    p.add_argument("--out", required=True, metavar="FILE", help="output .jsonl")
    p.add_argument(
        "--geoip", metavar="MMDB", help="add location context from a .mmdb city database"
    )
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("trace", help="check sampled actions against normalized events (LOG-01)")
    p.add_argument("--manifest", required=True, help="sampler manifest.jsonl")
    p.add_argument("--events", required=True, help="normalized events .jsonl")
    p.set_defaults(func=cmd_trace)

    features_cmd.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
