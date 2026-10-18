"""Adapters: implementations of the ports in ueba.application.ports.

One module per external system, added when its phase starts, e.g.:
  wazuh_indexer.py    EventSource, reading wazuh-alerts-* / archives (Phase 2)
  maxmind_geo.py      GeoLookup over a GeoLite2 database file (Phase 2)
  nextcloud_dav.py    WebDAV client for the simulator (Phase 3)
  parquet_store.py    feature and dataset storage (Phase 4)
  wazuh_detections.py DetectionSink (Phase 6)

Adapters translate wire formats into domain objects; they hold no research logic.
"""
