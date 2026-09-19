"""Autoanosis Continuity Core v1.

Canonical, timestamp/provenance-aware continuity utilities for existing
Autoanosis health data. The v1 foundation is intentionally read-only:
it derives a continuity summary from already-available context without
writing or mutating production medical data.
"""

from .service import build_continuity_summary

__all__ = ["build_continuity_summary"]
