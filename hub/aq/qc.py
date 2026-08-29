"""Data quality gate (Phase 3).

- ``range_mask``: out-of-range values -> NaN (CO2 350-5000, temp -10..50,
  humidity 0..100, VOC index 1..500, PM >= 0 and < 1000). No interpolation.
- ``daily_gate``: node x day CO2 validity < 95 % -> that node/day is excluded
  from analysis (rows are never deleted). Validity is counted over the rows
  the node actually delivered that day; a day with no rows at all fails too.
  "Day" is the KST calendar date of the bucket (cfg time.tz_offset_hours).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# readings column -> [qc.range] key
COLUMN_RANGES = {"co2": "co2", "temp": "temp", "hum": "hum", "voc": "voc", "pm2p5": "pm"}


def range_mask(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Return a copy of ``df`` with out-of-range values replaced by NaN."""
    rng = cfg["qc"]["range"]
    out = df.copy()
    for col, key in COLUMN_RANGES.items():
        if col not in out.columns:
            continue
        lo, hi = rng[key]
        v = pd.to_numeric(out[col], errors="coerce")
        exclusive_hi = key == "pm" and rng.get("pm_max_exclusive", False)
        bad = (v < lo) | ((v >= hi) if exclusive_hi else (v > hi))
        out[col] = v.mask(bad, np.nan)
    return out


def local_date(bucket: pd.Series, cfg: dict) -> pd.Series:
    """KST calendar date of each UTC bucket string."""
    off = pd.Timedelta(hours=cfg["time"]["tz_offset_hours"])
    return (pd.to_datetime(bucket) + off).dt.date


def daily_gate(df: pd.DataFrame, cfg: dict, nodes=None, days=None) -> pd.DataFrame:
    """Per (node, date): rows, valid_co2_pct, valid_voc_pct, passed, reason.
    ``df`` must already be range-masked. Pass ``nodes``/``days`` to also list
    combinations that delivered no rows (they fail with reason 'no rows')."""
    thr = float(cfg["qc"]["daily_valid_pct_min"])
    cols = ["node", "date", "rows", "valid_co2_pct", "valid_voc_pct", "passed", "reason"]
    recs: list[dict] = []
    if not df.empty:
        d = df.assign(date=local_date(df["bucket"], cfg))
        for (node, day), g in d.groupby(["node", "date"], sort=True):
            n = int(len(g))
            co2_pct = float(g["co2"].notna().mean() * 100.0)
            voc_pct = float(g["voc"].notna().mean() * 100.0)
            ok = co2_pct >= thr
            recs.append({"node": node, "date": day, "rows": n,
                         "valid_co2_pct": round(co2_pct, 2), "valid_voc_pct": round(voc_pct, 2),
                         "passed": bool(ok),
                         "reason": "" if ok else f"co2 valid {co2_pct:.1f}% < {thr:g}%"})
    seen = {(r["node"], r["date"]) for r in recs}
    for node in (nodes or []):
        for day in (days or []):
            if (node, day) not in seen:
                recs.append({"node": node, "date": day, "rows": 0, "valid_co2_pct": 0.0,
                             "valid_voc_pct": 0.0, "passed": False, "reason": "no rows"})
    gate = pd.DataFrame(recs, columns=cols)
    return gate.sort_values(["node", "date"]).reset_index(drop=True)


def apply_gate(df: pd.DataFrame, gate: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Rows of ``df`` whose (node, KST date) passed the gate."""
    if df.empty:
        return df
    ok = {(r.node, r.date) for r in gate.itertuples() if r.passed}
    d = df.assign(date=local_date(df["bucket"], cfg))
    keep = [(n, dt) in ok for n, dt in zip(d["node"], d["date"], strict=True)]
    return df[keep].reset_index(drop=True)


def gate_payload(gate: pd.DataFrame, node: str, day: date) -> dict:
    """qc payload for one (node, day); 'no rows' when absent."""
    row = gate[(gate["node"] == node) & (gate["date"] == day)]
    if row.empty:
        return {"valid_co2_pct": 0.0, "valid_voc_pct": 0.0, "rows": 0, "passed": False,
                "reason": "no rows"}
    r = row.iloc[0]
    return {"valid_co2_pct": float(r["valid_co2_pct"]), "valid_voc_pct": float(r["valid_voc_pct"]),
            "rows": int(r["rows"]), "passed": bool(r["passed"]), "reason": str(r["reason"])}
