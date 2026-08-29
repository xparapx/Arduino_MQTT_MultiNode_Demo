"""Occupancy x CO2 relation (Phase 3).

Environment and vision nodes of the same room share a label in nodes.json; both
publish on the 5-minute bucket grid, so the join is exact on (room, bucket).
Spearman is used because CO2 saturates with people (monotone, not linear);
the ppm-per-person slope is a plain least-squares line for the summary text.

by_room also carries ``last_bucket`` -- the last occupancy bucket the room's
vision node ever sent (all time, from ``last_seen``) -- so page 2 can show a
room whose vision node stopped before the analysis window as "stopped"
instead of silently dropping it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_POINTS = 3          # fewer joined points than this -> no coefficient
EMPTY = {"rho": None, "n": 0, "slope": None}


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


def last_bucket_by_room(occupancy: pd.DataFrame, labels: dict,
                        last_seen: dict[str, str] | None) -> dict[str, str]:
    """{room: last occupancy bucket}. ``last_seen`` (node -> bucket, all time)
    wins; the window's occupancy frame is the fallback. Unlabelled nodes are
    skipped, several vision nodes per room take the latest."""
    out: dict[str, str] = {}
    pairs = list((last_seen or {}).items())
    if not pairs and not occupancy.empty:
        pairs = list(occupancy.groupby("node")["bucket"].max().items())
    for node, b in pairs:
        room = labels.get(node)
        if room is not None and b and (room not in out or b > out[room]):
            out[room] = b
    return out


def spearman_by_room(readings: pd.DataFrame, occupancy: pd.DataFrame, labels: dict,
                     cfg: dict, last_seen: dict[str, str] | None = None) -> dict:
    """occ_co2 payload: pooled Spearman rho, n, slope (ppm per person), by_room.
    by_room lists every room with a vision node ever seen (n = 0 when nothing
    joined in the window) and its last_bucket."""
    joined = join_rooms(readings, occupancy, labels, cfg)
    pooled = _stats(joined)
    last = last_bucket_by_room(occupancy, labels, last_seen)
    by_room = {room: _stats(g) for room, g in joined.groupby("room")}
    for room in last:
        by_room.setdefault(room, dict(EMPTY))
    for room, s in by_room.items():
        s["last_bucket"] = last.get(room)
    return {"spearman_rho": pooled["rho"] if pooled["rho"] is not None else float("nan"),
            "n": pooled["n"],
            "slope_ppm_per_person": pooled["slope"] if pooled["slope"] is not None
            else float("nan"),
            "by_room": dict(sorted(by_room.items()))}
