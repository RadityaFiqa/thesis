"""Application layer: use cases, one module per job, plus the ports they depend on.

Use cases talk to the outside world only through the Protocols in ports.py,
so they can be tested with in-memory fakes and the adapters can change freely.
"""
