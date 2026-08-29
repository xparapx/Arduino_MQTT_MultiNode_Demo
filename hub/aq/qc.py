"""Data quality gate (Phase 3).

- ``range_mask``: out-of-range values -> NaN (CO2 350-5000, temp -10..50,
  humidity 0..100, VOC index 1..500, PM >= 0 and < 1000). No interpolation.
- ``daily_gate``: node x day CO2 validity < 95 % -> that node/day is excluded
  from analysis (rows are never deleted).
"""

from __future__ import annotations


def range_mask(df, cfg: dict):
    """Return a copy of ``df`` with out-of-range values replaced by NaN."""
    raise NotImplementedError("Phase 3")


def daily_gate(df, cfg: dict):
    """Return DataFrame[node, date, valid_pct, passed]."""
    raise NotImplementedError("Phase 3")
