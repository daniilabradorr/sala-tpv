"""Dynamic read-model and analytics module.

Reports aggregates tenant-scoped data from authoritative domain models at query
time. Persistent report snapshots are intentionally deferred until performance,
historical export, or precomputation requirements justify them.
"""
