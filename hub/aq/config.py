"""Configuration loader for config/analyst.toml (Phase 2).

All thresholds, scales, rule limits and governance criteria from plan section 2
live in that file; this module only loads and validates it.
"""

from __future__ import annotations

from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = HUB_DIR / "config" / "analyst.toml"
DEFAULT_CALENDAR = HUB_DIR / "calendar.json"


def load(path: str | Path = DEFAULT_CONFIG) -> dict:
    """Load and validate analyst.toml. Implemented in Phase 2."""
    raise NotImplementedError("Phase 2: config/analyst.toml")
