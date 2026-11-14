"""Portable declared build inventory contracts.

This package deliberately does not evaluate Maven or Gradle builds.
"""

from .inventory import (
    SafeReader,
    Snapshot,
    canonical_json,
    canonical_path,
    capture,
    link_analysis,
    load_manifest,
    load_snapshot,
    save_snapshot,
)

__all__ = [
    "SafeReader", "Snapshot", "canonical_json", "canonical_path", "capture",
    "link_analysis", "load_manifest", "load_snapshot", "save_snapshot",
]
