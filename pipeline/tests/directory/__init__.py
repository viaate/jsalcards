"""Tests for the school directory build (``snowlight directory``).

This file makes the directory a package, so mypy names its modules
``directory.conftest`` and so on. Without it, this ``conftest.py`` and the
other test directories' ``conftest.py`` files would all be the module
``conftest``, and ``mypy --strict snowlight tests`` would stop at the clash.
"""
