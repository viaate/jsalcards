"""Tests for the weather piece (NWS alerts, the IEM archive and the weather check).

This file makes the folder the package ``weather`` for mypy, so its helpers are
``weather.conftest``. Without it, this ``conftest.py`` and the other test
folders' ``conftest.py`` files would all be the module ``conftest``, and
``mypy --strict snowlight tests`` would stop at the clash.
"""
