"""aq -- analysis package shared by analyst.py and the Streamlit dashboard.

Rules (see docs/plan/CLAUDE_CODE_PLAN.md section 2):
- readings / occupancy are read-only here; only analyst.py writes, and only to
  the analysis / actuator_state tables.
- every constant lives in config/analyst.toml (no magic numbers in code).
- all time handling starts with the 5-minute bucket floor in aq.db.
"""

__all__ = [
    "config",
    "db",
    "schemas",
    "qc",
    "regime",
    "rules",
    "governance",
    "forecast",
    "occ_co2",
    "summary",
    "plots",
    "ui_common",
]
__version__ = "0.1.0"
