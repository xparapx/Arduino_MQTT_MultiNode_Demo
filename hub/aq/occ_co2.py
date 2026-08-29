"""Occupancy x CO2 relation (Phase 3).

Environment and vision nodes of the same room share a label in nodes.json; both
publish on the 5-minute bucket grid, so the join is exact on (room, bucket).
Spearman is used because CO2 saturates with people (monotone, not linear);
the ppm-per-person slope is a plain least-squares line for the summary text.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_POINTS = 3          # fewer joined points than this -> no coefficient


def join_rooms(readings: pd.DataFrame, occupancy: pd.DataFrame, labels: dict,
               cfg: dict) -> pd.DataFrame:
    """Inner join on (room, bucket). Occupancy buckets with n < min_occ_n are
    dropped first (low-quality buckets). Columns: room, bucket, co2, occ."""
    min_n = cfg["occ_co2"]["min_occ_n"]
    if readings.empty or occupancy.empty:
        return pd.DataFrame(columns=["room", "bucket", "co2", "occ"])
    env = readings[["node", "bucket", "co2"]].dropna(subset=["co2"]).copy()
    occ = occupancy[occupancy["n"] >= min_n][["node", "bucket", "occ"]].dropna().copy()
    env["room"] = env["node"].map(labels)
    occ["room"] = occ["node"].map(labels)
    env = env.dropna(subset=["room"]).drop(columns="node")
    occ = occ.dropna(subset=["room"]).drop(columns="node")
    return env.merge(occ, on=["room", "bucket"], how="inner")


def _stats(d: pd.DataFrame) -> dict:
    n = int(len(d))
    if n < MIN_POINTS or d["occ"].nunique() < 2 or d["co2"].nunique() < 2:
        return {"rho": None, "n": n, "slope": None}
    rho = float(d["co2"].corr(d["occ"], method="spearman"))
    slope = float(np.polyfit(d["occ"].to_numpy(float), d["co2"].to_numpy(float), 1)[0])
    return {"rho": None if np.isnan(rho) else round(rho, 4), "n": n, "slope": round(slope, 2)}


def spearman_by_room(readings: pd.DataFrame, occupancy: pd.DataFrame, labels: dict,
                     cfg: dict) -> dict:
    """occ_co2 payload: pooled Spearman rho, n, slope (ppm per person), by_room."""
    joined = join_rooms(readings, occupancy, labels, cfg)
    pooled = _stats(joined)
    by_room = {room: _stats(g) for room, g in joined.groupby("room")}
    return {"spearman_rho": pooled["rho"] if pooled["rho"] is not None else float("nan"),
            "n": pooled["n"],
            "slope_ppm_per_person": pooled["slope"] if pooled["slope"] is not None
            else float("nan"),
            "by_room": by_room}
