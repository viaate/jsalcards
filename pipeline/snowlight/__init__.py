"""Snowlight data pipeline: builds the static files the website reads."""

from importlib.metadata import version

__version__ = version("snowlight")

__all__ = ["__version__"]
