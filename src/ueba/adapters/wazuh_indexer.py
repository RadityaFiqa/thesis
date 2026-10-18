"""EventSource over the Wazuh indexer (wazuh-alerts-*), standard library only.

Events are selected by the log file they came from (`location`), not by rule:
a built-in Wazuh rule can claim a Nextcloud line (rule 2501 takes "Login failed"),
and selecting by rule group would then lose it silently.

The alert's `full_log` is the raw JSON line, so the same parser serves log files
and the index. `timestamp` (when the manager processed the line) is the ingest time.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import ssl
import urllib.request
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ueba.adapters.nextcloud_logs import SOURCE_BY_LOCATION, parse_record
from ueba.domain.events import NormalizedEvent

INDEX_PATTERN = "wazuh-alerts-4.x-*"


@dataclass(frozen=True)
class IndexerConfig:
    url: str = "https://127.0.0.1:9200"
    user: str = "admin"
    password: str = ""
    ca_file: str | None = None  # verify the chain; hostname isn't checked (local endpoint)
    insecure: bool = False  # no verification at all; only for a trusted local tunnel

    def ssl_context(self) -> ssl.SSLContext:
        if self.insecure:
            return ssl._create_unverified_context()  # noqa: S323 - explicit opt-in
        ctx = ssl.create_default_context(cafile=self.ca_file)
        if self.ca_file:
            ctx.check_hostname = False  # cert is issued to "wazuh.indexer", reached as 127.0.0.1
        return ctx


class IndexerClient:
    def __init__(self, config: IndexerConfig) -> None:
        self.config = config
        self._ctx = config.ssl_context()
        token = base64.b64encode(f"{config.user}:{config.password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.config.url.rstrip("/") + path, data=data, method=method, headers=self._headers
        )
        with urllib.request.urlopen(req, context=self._ctx, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")


class IndexerEventSource:
    def __init__(
        self, client: IndexerClient, since: datetime, until: datetime, page_size: int = 1000
    ) -> None:
        self.client = client
        self.since, self.until = since, until
        self.page_size = page_size
        self.skipped: Counter = Counter()
        self.duplicates = 0

    def _query(self) -> dict[str, Any]:
        return {
            "size": self.page_size,
            "sort": [{"timestamp": "asc"}],
            "_source": ["timestamp", "location", "full_log"],
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"location": sorted(SOURCE_BY_LOCATION)}},
                        {
                            "range": {
                                "timestamp": {
                                    "gte": self.since.isoformat(),
                                    "lt": self.until.isoformat(),
                                }
                            }
                        },
                    ]
                }
            },
        }

    def _hits(self) -> Iterator[dict[str, Any]]:
        page = self.client.request("POST", f"/{INDEX_PATTERN}/_search?scroll=2m", self._query())
        scroll_id = page.get("_scroll_id")
        try:
            while hits := page.get("hits", {}).get("hits", []):
                yield from hits
                page = self.client.request(
                    "POST", "/_search/scroll", {"scroll": "2m", "scroll_id": scroll_id}
                )
                scroll_id = page.get("_scroll_id", scroll_id)
        finally:
            if scroll_id:
                with contextlib.suppress(OSError):
                    self.client.request("DELETE", "/_search/scroll", {"scroll_id": [scroll_id]})

    def events(self) -> Iterator[NormalizedEvent]:
        seen: set[str] = set()
        for hit in self._hits():
            src = hit.get("_source", {})
            location, full_log = src.get("location", ""), src.get("full_log", "")
            # The same raw line indexed twice (e.g. resent after a manager outage)
            digest = hashlib.sha256(f"{location}\n{full_log}".encode()).hexdigest()
            if digest in seen:
                self.duplicates += 1
                continue
            seen.add(digest)
            try:
                rec = json.loads(full_log)
                ingest = datetime.fromisoformat(src["timestamp"])
            except (ValueError, KeyError, TypeError):
                self.skipped["invalid_record"] += 1
                continue
            result = parse_record(
                location, rec, raw_ref=f"{hit['_index']}/{hit['_id']}", ingest_time=ingest
            )
            if result.event is None:
                self.skipped[result.skip_reason] += 1
            else:
                yield result.event
