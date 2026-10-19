"""The live closings ingest (spec S8): row ledger, interval dating, resolve, merge and guards.

Nothing in this package keeps raw station text: the ledger holds hashed keys, times
and source ids (:mod:`snowlight.live.ledger`), the derived results hold codes, and
the provenance lines hold codes, ids and times (:mod:`snowlight.live.provenance`).
"""
