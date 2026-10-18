"""Nextcloud UEBA research platform (thesis).

Layers, innermost first (see docs/architecture.md):
  domain       pure data and rules, no I/O
  application  use cases and the ports (interfaces) they need
  adapters     ports implemented against Wazuh, Nextcloud, files, GeoIP
  entrypoints  CLI wiring: picks adapters and runs a use case
"""

__version__ = "0.1.0"
