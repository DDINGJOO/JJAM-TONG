"""Fail-closed importer for a single GitHub Actions method-index artifact."""

from .collector import Collector, ImportError, Receipt, SourceConfig

__all__ = ("Collector", "ImportError", "Receipt", "SourceConfig")
