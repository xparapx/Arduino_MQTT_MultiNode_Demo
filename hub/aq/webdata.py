"""Read-only data layer for the JSON API (Phase 8, webapp.py).

Everything the two web pages need, as plain JSON-able dicts. Mirrors the
page-1 computations of aq.ui_common (radar normalisation, Tukey box stats,
per-node means, 60-bucket series, vision panel) and the page-2 reads of
aq.analysis_view, but imports neither: no streamlit, no plotly, so the API
process stays small. Results are memoised on the DB version -- (MAX(id) of
readings, its 5-min bucket) for readings-based views, MAX(id) of analysis
for page 2 -- so a poll without new rows costs a couple of PK lookups.

Invariants: only SELECTs on readings / occupancy / analysis (connections are
opened ?mode=ro); analysis and actuator_state stay analyst.py's to write.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from aq import config, db, governance
from aq.derive import ACTION_WORDS, REGIME_KO, action_summary, pool_transitions
from aq.regime import REGIMES

TS_FMT = "%Y-%m-%d %H:%M:%S"
KST = timedelta(hours=9)
DB_TIMEOUT_S = 5
ROW_LIMIT = 5000              # recent rows behind the live sections (as page 1)
STATS_DAYS = 28
BOX_DAYS = 7                  # distribution boxes: recent week (trend/exceed stay on the full window)
EXCEED_THR = {"co2": 1000.0, "voc": 200.0}   # = rules layer ON thresholds (fan.on_co2 / purifier.on_voc)
BOX_MAX_OUTLIERS = 300
SERIES_BUCKETS = 60
RECORDS_N = 5
OCC_HIST = 24
ACTIVE_WINDOW_MIN = 15        # node with a row in the last 15 min counts as active
VISION_RECENT_DAYS = 1
BAND24_HOURS = 24            # action cards: value trace behind the hysteresis band
BAND24_BUCKET_MIN = 5
STALE_MIN = 12                # vision bucket older than this -> "지연"

# Same tables as aq.ui_common.METRICS / GAUGE_KEYS / NODE_PALETTE (kept in sync by
# tests/test_webdata.py) -- duplicated so this module never imports streamlit.
METRICS = {
    "pm1p0": ("PM1.0", "µg/m³", 0, 100), "pm2p5": ("PM2.5", "µg/m³", 0, 100),
    "pm4p0": ("PM4.0", "µg/m³", 0, 100), "pm10p0": ("PM10", "µg/m³", 0, 150),
    "sen_temp": ("Temp(SEN)", "°C", 0, 50), "sen_hum": ("Hum(SEN)", "%", 0, 100),
    "voc": ("VOC", "idx", 0, 500), "nox": ("NOx", "idx", 0, 500),
    "co2": ("CO₂", "ppm", 400, 2000), "scd_temp": ("Temp", "°C", 0, 50),
    "scd_hum": ("Hum", "%", 0, 100),
}
ALL_KEYS = list(METRICS)
GAUGE_KEYS = ["pm2p5", "pm10p0", "scd_temp", "scd_hum", "co2", "voc"]
TARGET_KEYS = ["co2", "voc"]
NODE_PALETTE = ["#FF5CA8", "#8B7CFF", "#00E5B0", "#FFB300",
                "#4DD2FF", "#C4FF4D", "#FF8A5C", "#EAEAEA"]
ANALYSIS_COLS = ("id", "run_at", "scope", "win_start", "win_end", "model_ver", "payload")


class WebData:
    """One instance per server process. ``db_path`` / ``nodes_path`` /
    ``models_dir`` are taken as given (tests point them at a fixture copy)."""

    def __init__(self, db_path: str = "sensor_data.db", nodes_path: str = "nodes.json",
                 models_dir: str | Path = "models", cfg: dict | None = None):
        self.db_path = str(db_path)
        self.nodes_path = str(nodes_path)
        self.models_dir = Path(models_dir)
        self.cfg = cfg or config.load()
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    # ---- infrastructure ---------------------------------------------------------------
    def _ro(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=DB_TIMEOUT_S)

    def _has_db(self) -> bool:
        return os.path.isfile(self.db_path)

    def _memo(self, key: str, version, build):
        """Return the cached value for ``key`` when its version matches, else rebuild."""
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == version:
                return hit[1]
        value = build()
        with self._lock:
            self._cache[key] = (version, value)
        return value

    def labels(self) -> dict:
        try:
            with open(self.nodes_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def label_of(self, node: str) -> str:
        return self.labels().get(node, node)

    @staticmethod
    def _sort_key(label: str):
        m = re.search(r"\d+", label)
        return (0, int(m.group()), label.lower()) if m else (1, 0, label.lower())

    def _tables(self, con) -> set[str]:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    # ---- versions ---------------------------------------------------------------------
    def data_version(self) -> tuple[int, str]:
        """(MAX(id), 5-min bucket of the newest readings row)."""
        if not self._has_db():
            return 0, ""
        with closing(self._ro()) as con:
            if "readings" not in self._tables(con):
                return 0, ""
            row = con.execute("SELECT id, ts FROM readings "
                              "WHERE id = (SELECT MAX(id) FROM readings)").fetchone()
        if not row:
            return 0, ""
        try:
            return int(row[0]), db.bucket_5min(row[1])
        except (ValueError, TypeError):
            return int(row[0]), str(row[1])

    def analysis_version(self) -> tuple[int, str]:
        if not self._has_db():
            return 0, ""
        with closing(self._ro()) as con:
            if "analysis" not in self._tables(con):
                return 0, ""
            mid, ts = con.execute("SELECT MAX(id), MAX(run_at) FROM analysis").fetchone()
        return (int(mid) if mid else 0), (ts or "")

    # ---- node identity -----------------------------------------------------------------
    def env_nodes(self, version=None) -> list[str]:
        """Environment nodes = nodes that ever wrote readings, in label-number order."""
        version = version if version is not None else self.data_version()[0]

        def build():
            if not self._has_db():
                return []
            with closing(self._ro()) as con:
                if "readings" not in self._tables(con):
                    return []
                nodes = [r[0] for r in con.execute("SELECT node FROM readings GROUP BY node")]
            return sorted(nodes, key=lambda n: self._sort_key(self.label_of(n)))
        return self._memo("env_nodes", version, build)

    def colors(self, nodes: list[str]) -> dict[str, str]:
        return {n: NODE_PALETTE[i % len(NODE_PALETTE)] for i, n in enumerate(nodes)}

    def node_info(self, node: str, colors: dict) -> dict:
        return {"node": node, "label": self.label_of(node), "color": colors.get(node, NODE_PALETTE[0])}

    # ---- readings ---------------------------------------------------------------------
    def recent(self, max_id: int, limit: int = ROW_LIMIT) -> pd.DataFrame:
        def build():
            if not self._has_db():
                return pd.DataFrame()
            sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, ts, node, "
                   + ", ".join(ALL_KEYS) + " FROM readings ORDER BY id DESC LIMIT ?")
            with closing(self._ro()) as con:
                if "readings" not in self._tables(con):
                    return pd.DataFrame()
                d = pd.read_sql_query(sql, con, params=(limit,))
            return d.iloc[::-1].reset_index(drop=True) if not d.empty else d
        return self._memo("recent", max_id, build)

    def live(self) -> dict:
        """Section 1: the newest row of every node, radar-normalised."""
        max_id, bucket = self.data_version()

        def build():
            d = self.recent(max_id)
            if d.empty:
                return {"version": max_id, "rows": 0, "last_seen_kst": None, "nodes": []}
            nodes = self.env_nodes(max_id)
            colors = self.colors(nodes)
            now = datetime.now(UTC).replace(tzinfo=None)
            out = []
            for n in nodes:
                g = d[d["node"] == n]
                if g.empty:
                    out.append({**self.node_info(n, colors), "recv_time": None, "age_min": None,
                                "down": True, "values": {}, "radar": []})
                    continue
                row = g.iloc[-1]
                age = (now - datetime.strptime(row["ts"], TS_FMT)).total_seconds() / 60
                vals = {k: _num(row[k]) for k in ALL_KEYS}
                radar = []
                for k in GAUGE_KEYS:
                    label, unit, gmin, gmax = METRICS[k]
                    v = vals[k]
                    r = 0.0 if v is None else float(np.clip((v - gmin) / (gmax - gmin), 0, 1))
                    radar.append({"key": k, "label": label, "unit": unit, "value": v, "r": r,
                                  "target": k in TARGET_KEYS})
                out.append({**self.node_info(n, colors), "recv_time": row["recv_time"],
                            "age_min": round(age, 1), "down": age > ACTIVE_WINDOW_MIN,
                            "values": vals, "radar": radar})
            return {"version": max_id, "rows": int(len(d)),
                    "last_seen_kst": str(d["recv_time"].max()), "nodes": out}
        return self._memo("live", max_id, build)

    def stats(self, days: int = STATS_DAYS) -> dict:
        """Section 2: Tukey box statistics per variable and CO2 / VOC means per node
        over the last ``days`` days, keyed on the newest 5-min bucket."""
        _, bucket = self.data_version()

        def build():
            if not self._has_db():
                return {"version": bucket, "days": days, "box": {}, "by_node": {}}
            sql = ("SELECT node, date(ts, '+9 hours') AS d, " + ", ".join(GAUGE_KEYS)
                   + " FROM readings WHERE ts >= datetime('now', ?)")
            with closing(self._ro()) as con:
                if "readings" not in self._tables(con):
                    return {"version": bucket, "days": days, "box": {}, "by_node": {}}
                dfa = pd.read_sql_query(sql, con, params=(f"-{days} days",))
            if dfa.empty:
                return {"version": bucket, "days": days, "box": {}, "by_node": {}}
            day_list = sorted(dfa["d"].unique())
            rec = dfa[dfa["d"] >= day_list[max(0, len(day_list) - BOX_DAYS)]]
            box = {}
            for k in GAUGE_KEYS:
                bs = box_stats(rec[k])
                if bs:
                    label, unit, _, _ = METRICS[k]
                    box[k] = {"label": label, "unit": unit, "target": k in TARGET_KEYS, **bs}
            colors = self.colors(self.env_nodes())
            by_node = {}
            for k in TARGET_KEYS:
                g = dfa.groupby("node")[k].mean().dropna().sort_values(ascending=False)
                by_node[k] = [{**self.node_info(n, colors), "mean": round(float(v), 1)}
                              for n, v in g.items()]
            # daily q1/med/q3 per target (KST day) and ON-threshold exceedance per node --
            # server aggregates only, a few hundred numbers for the whole window
            daily, exceed = {}, {}
            for k in TARGET_KEYS:
                v = dfa.dropna(subset=[k])
                if v.empty:
                    daily[k] = {"days": [], "q1": [], "med": [], "q3": []}
                    exceed[k] = []
                    continue
                q = v.groupby("d")[k].quantile([0.25, 0.5, 0.75]).unstack().sort_index()
                daily[k] = {"days": list(q.index),
                            "q1": [round(float(x), 1) for x in q[0.25]],
                            "med": [round(float(x), 1) for x in q[0.5]],
                            "q3": [round(float(x), 1) for x in q[0.75]]}
                grp = v.groupby("node")[k]
                pct = grp.apply(lambda x: float((x > EXCEED_THR[k]).mean() * 100.0))
                med = grp.median()
                exceed[k] = [{**self.node_info(n, colors), "pct": round(float(p), 1),
                              "med": round(float(med[n]), 1)}
                             for n, p in pct.sort_values(ascending=False).items()]
            return {"version": bucket, "days": days, "rows": int(len(dfa)), "box": box,
                    "box_days": BOX_DAYS, "by_node": by_node, "thr": EXCEED_THR,
                    "daily": daily, "exceed": exceed}
        return self._memo("stats", bucket, build)

    def series(self, node: str) -> dict:
        """Section 3 + 4: last 60 rows of one node, its recent records and the
        paired vision node's latest bucket."""
        max_id, _ = self.data_version()
        d = self.recent(max_id)
        colors = self.colors(self.env_nodes(max_id))
        info = self.node_info(node, colors)
        if d.empty or node not in set(d["node"]):
            return {**info, "version": max_id, "times": [], "series": {}, "records": [],
                    "occupancy": self.occupancy(node)}
        g = d[d["node"] == node].tail(SERIES_BUCKETS)
        series = {k: [_num(v) for v in g[k]] for k in GAUGE_KEYS}
        recs = d[d["node"] == node].tail(RECORDS_N).iloc[::-1]
        records = [{"recv_time": r["recv_time"], **{k: _num(r[k]) for k in ALL_KEYS}}
                   for _, r in recs.iterrows()]
        return {**info, "version": max_id, "times": list(g["recv_time"]), "series": series,
                "metrics": {k: {"label": METRICS[k][0], "unit": METRICS[k][1],
                                "target": k in TARGET_KEYS} for k in GAUGE_KEYS},
                "records": records, "record_keys": ALL_KEYS, "occupancy": self.occupancy(node)}

    # ---- occupancy ----------------------------------------------------------------------
    def _occ_exists(self, con) -> bool:
        return "occupancy" in self._tables(con)

    def occupancy(self, env_node: str) -> dict:
        """Vision panel of the room that ``env_node`` belongs to (same label in
        nodes.json): latest bucket, crosshair centroids, 24-bucket history."""
        lbl = self.label_of(env_node)
        if not self._has_db():
            return {"available": False, "reason": "no db"}
        with closing(self._ro()) as con:
            if not self._occ_exists(con):
                return {"available": False, "reason": "no occupancy table"}
            latest = pd.read_sql_query(
                "SELECT o.node, datetime(o.ts,'+9 hours') AS recv_time, o.ts, o.occ, o.occ_med, "
                "o.occ_max, o.occ_last, o.cents, o.w, o.n FROM occupancy o JOIN "
                "(SELECT node, MAX(id) AS mid FROM occupancy GROUP BY node) m ON o.id = m.mid", con)
            if latest.empty:
                return {"available": False, "reason": "no rows"}
            labels = self.labels()
            now = datetime.now(UTC).replace(tzinfo=None)
            vnodes = []                       # every vision node's latest bucket -> ON / OFF chips
            for _, v in latest.iterrows():
                a = (now - datetime.strptime(v["ts"], TS_FMT)).total_seconds() / 60
                vnodes.append({"node": v["node"], "room": labels.get(v["node"], v["node"]),
                               "age_min": round(a, 1), "on": a <= STALE_MIN,
                               "last_kst": v["recv_time"]})
            vnodes.sort(key=lambda x: self._sort_key(x["room"]))
            vn = next((v for v in latest["node"] if labels.get(v, v) == lbl), None)
            if vn is None:
                return {"available": False, "reason": "no vision node", "label": lbl}
            row = latest[latest["node"] == vn].iloc[0]
            hist = pd.read_sql_query(
                "SELECT datetime(ts,'+9 hours') AS recv_time, occ, occ_max, n FROM occupancy "
                "WHERE node=? ORDER BY id DESC LIMIT ?", con, params=(vn, OCC_HIST)).iloc[::-1]
        try:
            cents = [[float(c[0]), float(c[1])] for c in json.loads(row["cents"] or "[]")]
        except (ValueError, TypeError, IndexError):
            cents = []
        w = int(row["w"]) if row["w"] else 96
        age = next(x["age_min"] for x in vnodes if x["node"] == vn)
        return {"available": True, "label": lbl, "vision_node": vn, "recv_time": row["recv_time"],
                "nodes": vnodes,
                "age_min": round(age, 1), "stale": age > STALE_MIN,
                "occ": _num(row["occ"]), "occ_med": _num(row["occ_med"]),
                "occ_max": _num(row["occ_max"]), "n": _num(row["n"]), "w": w, "cents": cents,
                "hist": [{"recv_time": r["recv_time"], "occ": _num(r["occ"]),
                          "occ_max": _num(r["occ_max"])} for _, r in hist.iterrows()]}

    # ---- status (sidebar) ---------------------------------------------------------------
    def status(self) -> dict:
        max_id, bucket = self.data_version()
        aid, _ = self.analysis_version()
        out = {"version": {"max_id": max_id, "bucket": bucket, "analysis_id": aid},
               "hub_last_kst": None, "hub_age_min": None, "fresh": False, "readings_rows": 0,
               "journal": None, "env_active": 0, "env_total": 0, "vis_recent": 0, "vis_total": 0,
               "hourly_kst": None, "daily_kst": None, "weekly_kst": None, "model": None}
        if not self._has_db():
            return out
        with closing(self._ro()) as con:
            tables = self._tables(con)
            out["journal"] = con.execute("PRAGMA journal_mode").fetchone()[0]
            if "readings" in tables:
                out["readings_rows"] = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
                last = con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
                out["env_total"] = len(self.env_nodes(max_id))
                out["env_active"] = con.execute(
                    "SELECT COUNT(*) FROM (SELECT node FROM readings "
                    "WHERE id > (SELECT MAX(id) FROM readings) - 2000 GROUP BY node "
                    "HAVING MAX(ts) >= datetime('now', ?))",
                    (f"-{ACTIVE_WINDOW_MIN} minutes",)).fetchone()[0]
                if last:
                    out["hub_last_kst"] = kst(last)
                    age = (datetime.now(UTC).replace(tzinfo=None)
                           - datetime.strptime(last, TS_FMT)).total_seconds() / 60
                    out["hub_age_min"] = round(age, 1)
                    out["fresh"] = age <= ACTIVE_WINDOW_MIN
            if "occupancy" in tables:
                out["vis_total"] = con.execute(
                    "SELECT COUNT(*) FROM (SELECT node FROM occupancy GROUP BY node)").fetchone()[0]
                out["vis_recent"] = con.execute(
                    "SELECT COUNT(*) FROM (SELECT node FROM occupancy "
                    "WHERE id > (SELECT MAX(id) FROM occupancy) - 2000 GROUP BY node "
                    "HAVING MAX(ts) >= datetime('now', ?))",
                    (f"-{VISION_RECENT_DAYS} days",)).fetchone()[0]
            if "analysis" in tables:
                for key, kind in (("hourly_kst", "summary"), ("daily_kst", "band"),
                                  ("weekly_kst", "model_event")):
                    r = con.execute("SELECT MAX(run_at) FROM analysis WHERE kind=?",
                                    (kind,)).fetchone()[0]
                    out[key] = kst(r) if r else None
        try:
            out["model"] = governance.resolve_current(self.models_dir,
                                                      self.cfg["governance"]["current_link"])
        except OSError:
            out["model"] = None
        return out

    # ---- analysis (page 2) ---------------------------------------------------------------
    def _latest_rows(self, con, kind: str) -> list[dict]:
        sql = ("SELECT id, run_at, scope, win_start, win_end, model_ver, payload FROM analysis "
               "WHERE kind=? AND run_at=(SELECT MAX(run_at) FROM analysis WHERE kind=?) ORDER BY id")
        return [_parse(r) for r in con.execute(sql, (kind, kind)).fetchall()]

    def _recent_rows(self, con, kind: str, limit: int) -> list[dict]:
        sql = ("SELECT id, run_at, scope, win_start, win_end, model_ver, payload FROM analysis "
               "WHERE kind=? ORDER BY id DESC LIMIT ?")
        return [_parse(r) for r in con.execute(sql, (kind, limit)).fetchall()]

    def _band24_readings(self, con, start: str, end: str) -> dict[str, dict[str, list]]:
        """{node: {"co2": [...], "voc": [...]}} -- 5-min bucket means over (start, end],
        one slot per bucket (None where nothing was received)."""
        n_slots = BAND24_HOURS * 60 // BAND24_BUCKET_MIN
        if "readings" not in self._tables(con):
            return {}
        d = pd.read_sql_query("SELECT node, ts, co2, voc FROM readings WHERE ts > ? AND ts <= ?",
                              con, params=(start, end))
        if d.empty:
            return {}
        t0 = datetime.strptime(start, TS_FMT)
        secs = (pd.to_datetime(d["ts"], format=TS_FMT) - t0).dt.total_seconds()
        d["slot"] = (secs // (BAND24_BUCKET_MIN * 60)).astype(int).clip(0, n_slots - 1)
        out: dict[str, dict[str, list]] = {}
        for node, g in d.groupby("node"):
            m = g.groupby("slot")[["co2", "voc"]].mean()
            out[node] = {k: [None] * n_slots for k in ("co2", "voc")}
            for slot, r in m.iterrows():
                for k in ("co2", "voc"):
                    v = _num(r[k])
                    out[node][k][int(slot)] = None if v is None else round(v, 1)
        return out

    def _band24_history(self, con, start: str, end: str) -> dict[str, dict]:
        """{node: {"on": {device: [[h0, h1], ...]}, "unjudged": [[h0, h1], ...]}} from the
        hourly action rows in (start, end]. Hours count from ``start``; a run's state
        holds until the next run (or ``end``). rule == "hold" = QC-excluded run: the
        rule layer was not evaluated and the state is the carried-over one."""
        if "analysis" not in self._tables(con):
            return {}
        rows = con.execute("SELECT run_at, scope, payload FROM analysis WHERE kind='action' "
                           "AND run_at > ? AND run_at <= ? ORDER BY run_at, id", (start, end)).fetchall()
        t0 = datetime.strptime(start, TS_FMT)
        h_end = (datetime.strptime(end, TS_FMT) - t0).total_seconds() / 3600
        hours = lambda ts: (datetime.strptime(ts, TS_FMT) - t0).total_seconds() / 3600  # noqa: E731
        per: dict[str, dict[str, list[tuple[float, dict]]]] = {}
        for run_at, scope, payload in rows:
            p = json.loads(payload)
            per.setdefault(scope, {}).setdefault(p["device"], []).append((hours(run_at), p))
        out: dict[str, dict] = {}
        for node, devs in per.items():
            on: dict[str, list] = {}
            unjudged: list = []
            for dev, runs in devs.items():
                segs: list = []
                for i, (h0, p) in enumerate(runs):
                    h1 = runs[i + 1][0] if i + 1 < len(runs) else h_end
                    if p.get("state") == 1:
                        if segs and abs(segs[-1][1] - h0) < 1e-9:
                            segs[-1][1] = h1
                        else:
                            segs.append([h0, h1])
                    if p.get("rule") == "hold" and dev == "fan":      # same for both devices
                        if unjudged and abs(unjudged[-1][1] - h0) < 1e-9:
                            unjudged[-1][1] = h1
                        else:
                            unjudged.append([h0, h1])
                on[dev] = [[round(a, 3), round(b, 3)] for a, b in segs]
            out[node] = {"on": on, "unjudged": [[round(a, 3), round(b, 3)] for a, b in unjudged]}
        return out

    def model_meta(self, ver: str | None) -> dict | None:
        if not ver or ver == "adhoc":
            return None
        p = self.models_dir / f"{ver}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def analysis(self) -> dict:
        """Everything page 2 shows, from the analysis table only (+ models/)."""
        aid, run_at = self.analysis_version()
        return self._memo("analysis", (aid, self.data_version()[0]), lambda: self._analysis(aid))

    def _analysis(self, aid: int) -> dict:
        cfg = self.cfg
        reg = cfg["regime"]
        out = {"version": aid, "empty": aid == 0,
               "cfg": {"regime": {"co2_scale": reg["co2_scale"], "voc_scale": reg["voc_scale"],
                                  "anchor_co2_ppm": reg["anchor_co2_ppm"],
                                  "anchor_voc_index": reg["anchor_voc_index"],
                                  "smooth_window": cfg["time"]["smooth_window"],
                                  "bucket_minutes": cfg["time"]["bucket_minutes"]},
                       "rules": cfg["rules"], "run": cfg["run"], "occ_co2": cfg["occ_co2"],
                       "qc": {"daily_valid_pct_min": cfg["qc"]["daily_valid_pct_min"]},
                       "time": {"transition_dt_minutes": cfg["time"]["transition_dt_minutes"],
                                "transition_dt_tolerance": cfg["time"]["transition_dt_tolerance"]},
                       "governance": {k: cfg["governance"][k] for k in
                                      ("train_window_days", "eval_window_days", "loglik_gain_min",
                                       "centroid_shift_min")}},
               "regime_ko": REGIME_KO, "regimes": list(REGIMES)}
        gov = cfg["governance"]
        versions = governance.list_versions(self.models_dir)
        current = governance.resolve_current(self.models_dir, gov["current_link"])
        out["model"] = {"versions": versions, "current": current, "ver": None, "meta": None}
        if aid == 0:
            return out
        nodes = self.env_nodes()
        colors = self.colors(nodes)
        with closing(self._ro()) as con:
            L = {k: self._latest_rows(con, k) for k in
                 ("regime_now", "action", "forecast", "qc", "band", "transition", "occ_co2",
                  "explore", "summary")}
            events = self._recent_rows(con, "model_event", 20)
            # E: the 24 h behind the action cards end at the newest readings bucket
            # ("now"), not at the hourly run -- the run can be up to an hour old.
            b24: dict = {"start": None, "end": None, "readings": {}, "history": {}}
            if L["action"]:
                b24_end = max(self.data_version()[1] or "", L["action"][0]["run_at"])
                b24_start = (datetime.strptime(b24_end, TS_FMT) - timedelta(hours=BAND24_HOURS)).strftime(TS_FMT)
                b24.update(start=b24_start, end=b24_end,
                           readings=self._band24_readings(con, b24_start, b24_end),
                           history=self._band24_history(con, b24_start, b24_end))
        reg_rows = L["regime_now"]
        ver = reg_rows[0]["model_ver"] if reg_rows else None
        out["model"].update({"ver": ver, "meta": self.model_meta(ver)})
        if L["summary"]:
            out["summary"] = {"lines": L["summary"][0]["payload"]["lines"],
                              "run_at_kst": kst(L["summary"][0]["run_at"])}
        else:
            out["summary"] = None
        out["run_at"] = {"hourly_kst": kst(reg_rows[0]["run_at"]) if reg_rows else None,
                         "daily_kst": kst(L["band"][0]["run_at"]) if L["band"] else None}
        out["daily_window"] = ({"start": L["band"][0]["win_start"], "end": L["band"][0]["win_end"]}
                               if L["band"] else None)
        # A: QC -- one row per node. The node-scoped row (hourly) is "today"; the
        # node@day rows (daily) become a 7-day pass / fail strip.
        qc_today: dict[str, dict] = {}
        qc_days: dict[str, list] = {}
        for r in L["qc"]:
            node, _, day = r["scope"].partition("@")
            p = r["payload"]
            if day:
                qc_days.setdefault(node, []).append({"date": day, "passed": p["passed"],
                                                     "valid_co2_pct": p["valid_co2_pct"]})
            else:
                qc_today[node] = p
        qc = []
        for n in nodes:
            days = sorted(qc_days.get(n, []), key=lambda d: d["date"])
            p = qc_today.get(n) or (dict(days[-1]) if days else None)
            if p is None and n not in qc_days:
                continue
            qc.append({**self.node_info(n, colors),
                       "valid_co2_pct": (p or {}).get("valid_co2_pct"),
                       "valid_voc_pct": (p or {}).get("valid_voc_pct"),
                       "passed": (p or {}).get("passed", False), "reason": (p or {}).get("reason", ""),
                       "days": days, "failed_days": sum(1 for d in days if not d["passed"])})
        out["qc"] = qc
        # B: regime now + one action row per room, all env nodes listed
        regime_now = {r["scope"]: r["payload"] for r in reg_rows}
        actions: dict[str, dict] = {}
        for r in L["action"]:
            actions.setdefault(r["scope"], {})[r["payload"]["device"]] = r["payload"]
        action_run_at = L["action"][0]["run_at"] if L["action"] else None
        rooms = []
        for n in nodes:
            p = regime_now.get(n)
            a = action_summary(actions.get(n, {}))
            if n not in actions:            # no hourly rows for this node at all
                a.update(word=ACTION_WORDS["hold"], kind="hold", reason="hourly 창에 수신 행 없음")
            binding = bool(a["hold_until"] and (action_run_at is None or a["hold_until"] > action_run_at))
            rooms.append({**self.node_info(n, colors), "judged": p is not None,
                          "regime": (p or {}).get("regime"),
                          "co2": _num((p or {}).get("co2")), "voc": _num((p or {}).get("voc")),
                          "dwell_min": (p or {}).get("dwell_min"),
                          "dwell_censored": (p or {}).get("dwell_censored"),
                          "trail": (p or {}).get("trail", []),
                          "action": {**a, "since_kst": kst(a["since"]) if a["since"] else None,
                                     "hold_until_kst": kst(a["hold_until"], "%H:%M") if a["hold_until"] else None,
                                     "binding": binding},
                          "devices": actions.get(n, {}),
                          "band24": {"start_kst": kst(b24["start"]), "end_kst": kst(b24["end"]),
                                     "hours": BAND24_HOURS, "bucket_min": BAND24_BUCKET_MIN,
                                     **b24["readings"].get(n, {"co2": [], "voc": []}),
                                     **b24["history"].get(n, {"on": {}, "unjudged": []})}})
        out["rooms"] = rooms
        out["action_run_at_kst"] = kst(action_run_at) if action_run_at else None
        # C: band
        if L["band"]:
            share: dict = {}
            bnodes = []
            for r in sorted(L["band"], key=lambda r: self._sort_key(self.label_of(r["scope"]))):
                slots = [{"bucket_kst": kst(s["bucket"], "%Y-%m-%d %H:%M"), "regime": s["regime"]}
                         for s in r["payload"]["slots"]]
                for s in slots:
                    share[s["regime"] or "missing"] = share.get(s["regime"] or "missing", 0) + 1
                bnodes.append({**self.node_info(r["scope"], colors), "slots": slots})
            tot = sum(share.values()) or 1
            out["band"] = {"nodes": bnodes, "share": {k: round(100 * v / tot, 1) for k, v in share.items()}}
        else:
            out["band"] = None
        # D: transitions
        out["transition"] = (pool_transitions({r["scope"]: r["payload"] for r in L["transition"]})
                             if L["transition"] else None)
        # F: forecast
        out["forecast"] = [{**self.node_info(r["scope"], colors),
                            "co2_now": _num(regime_now.get(r["scope"], {}).get("co2")),
                            "voc_now": _num(regime_now.get(r["scope"], {}).get("voc")),
                            "horizon_min": r["payload"]["horizon_min"],
                            "co2_pred": round(r["payload"]["co2_pred"]),
                            "voc_pred": round(r["payload"]["voc_pred"]),
                            "alert": r["payload"]["alert"], "train_rows": r["payload"].get("train_rows")}
                           for r in L["forecast"]]
        # G: occupancy x CO2
        if L["occ_co2"]:
            r = L["occ_co2"][0]
            p = r["payload"]
            by_room = []
            for room, s in sorted(p.get("by_room", {}).items()):
                last = s.get("last_bucket")
                by_room.append({"room": room, "n": s["n"], "rho": s["rho"], "slope": s["slope"],
                                "last_bucket_kst": kst(last) if last else None,
                                "stopped": bool(last and last < r["win_start"])})
            out["occ_co2"] = {"rho": _num(p["spearman_rho"]), "n": p["n"],
                              "slope": _num(p["slope_ppm_per_person"]), "win_start": r["win_start"],
                              "by_room": by_room}
        else:
            out["occ_co2"] = None
        # H: explore payload as stored (page draws it) + per-node label/colour
        out["explore"] = L["explore"][0]["payload"] if L["explore"] else None
        # I: model history
        out["model_events"] = []
        for e in events:
            p = e["payload"]
            meta = p.get("meta", {}) or {}
            out["model_events"].append({
                "run_at_kst": kst(e["run_at"]), "candidate_ver": p.get("candidate_ver"),
                "decision": p.get("decision"),
                "window": (f"{meta.get('win_start', '')[:10]} → {meta.get('win_end', '')[:10]}"
                           if meta else None),
                "rows": meta.get("rows"), "centroid_shift": p.get("centroid_shift"),
                "loglik_delta": p.get("loglik_delta"), "current_after": p.get("current_after"),
                "reason": (p.get("reason") or "")[:160]})
        return out

    # ---- export ----------------------------------------------------------------------------
    def time_bounds(self) -> dict:
        max_id, _ = self.data_version()

        def build():
            if not self._has_db():
                return {"lo": None, "hi": None}
            with closing(self._ro()) as con:
                if "readings" not in self._tables(con):
                    return {"lo": None, "hi": None}
                lo, hi = con.execute("SELECT MIN(datetime(ts,'+9 hours')), "
                                     "MAX(datetime(ts,'+9 hours')) FROM readings").fetchone()
            return {"lo": lo, "hi": hi}
        return self._memo("bounds", max_id, build)

    def export(self, kind: str, start_kst: str | None = None, end_kst: str | None = None) -> tuple[str, pd.DataFrame]:
        """(file name, dataframe) for the on-demand CSV exports. Uncached -- only
        runs when a button is pressed (page-1 Phase 1b rule)."""
        labels = self.labels()
        cols = "pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, co2, scd_temp, scd_hum"
        with closing(self._ro()) as con:
            tables = self._tables(con)
            if kind == "all":
                d = pd.read_sql_query(f"SELECT datetime(ts,'+9 hours') AS recv_time, node, {cols} "
                                      "FROM readings ORDER BY id", con)
                last = str(d.iloc[-1, 0])[:10] if len(d) else "empty"
                return f"sensor_all_{last}.csv", d
            if kind == "range":
                s = (datetime.fromisoformat(start_kst) - KST).strftime(TS_FMT)
                e = (datetime.fromisoformat(end_kst) - KST).strftime(TS_FMT)
                d = pd.read_sql_query(f"SELECT datetime(ts,'+9 hours') AS recv_time_kst, node, {cols} "
                                      "FROM readings WHERE ts BETWEEN ? AND ? ORDER BY id",
                                      con, params=(s, e))
                a, b = start_kst.replace("-", "")[:8], end_kst.replace("-", "")[:8]
                return f"sensor_{a}_{start_kst[11:13]}-{b}_{end_kst[11:13]}.csv", d
            if "occupancy" not in tables:
                return "occupancy_empty.csv", pd.DataFrame()
            if kind == "occupancy":
                d = pd.read_sql_query("SELECT datetime(ts,'+9 hours') AS recv_time_kst, ts AS ts_utc, "
                                      "node, occ AS occ_mean, occ_med, occ_max, occ_last, cents, w, n "
                                      "FROM occupancy ORDER BY id", con)
                if not d.empty:
                    d.insert(3, "room", d["node"].map(labels).fillna(""))
                last = str(d.iloc[-1, 0])[:10] if len(d) else "empty"
                return f"occupancy_all_{last}.csv", d
            if kind == "merged":
                env = pd.read_sql_query("SELECT ts, node, co2, voc, scd_temp, scd_hum, pm2p5, pm10p0, n "
                                        "FROM readings", con)
                occ = pd.read_sql_query("SELECT ts, node, occ AS occ_mean, occ_med, occ_max, n AS occ_n "
                                        "FROM occupancy WHERE n >= ?", con,
                                        params=(self.cfg["occ_co2"]["min_occ_n"],))
        if env.empty or occ.empty:
            return "env_occ_merged_empty.csv", pd.DataFrame()
        env["room"] = env["node"].map(labels)
        occ["room"] = occ["node"].map(labels)
        m = pd.merge(env.dropna(subset=["room"]).drop(columns=["node"]),
                     occ.dropna(subset=["room"])[["ts", "room", "occ_mean", "occ_med", "occ_max", "occ_n"]],
                     on=["ts", "room"], how="inner")
        if m.empty:
            return "env_occ_merged_empty.csv", m
        m["t_kst"] = (pd.to_datetime(m["ts"]) + pd.Timedelta(hours=9)).dt.strftime(TS_FMT)
        cols_ = ["t_kst", "room", "co2", "voc", "scd_temp", "scd_hum", "pm2p5", "pm10p0",
                 "occ_mean", "occ_med", "occ_max", "occ_n"]
        m = m[cols_].sort_values(["room", "t_kst"]).reset_index(drop=True)
        return f"env_occ_merged_{str(m.iloc[-1, 0])[:10]}.csv", m


# ---- helpers -------------------------------------------------------------------------------

def kst(ts_utc: str | None, fmt: str = "%m-%d %H:%M") -> str | None:
    if not ts_utc:
        return None
    return (datetime.strptime(ts_utc, TS_FMT) + KST).strftime(fmt)


def _num(v):
    """float or None (NaN / None / pandas NA -> None) so json never sees NaN."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) else f


def _parse(r) -> dict:
    d = dict(zip(ANALYSIS_COLS, r, strict=True))
    d["payload"] = json.loads(d["payload"])
    return d


def box_stats(s: pd.Series) -> dict | None:
    """Tukey box statistics (as aq.ui_common.box_stats): five numbers + a bounded
    outlier sample instead of the whole column."""
    s = s.dropna()
    if s.empty:
        return None
    q1, med, q3 = (float(v) for v in s.quantile([0.25, 0.5, 0.75]))
    lo_f, hi_f = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    inside = s[(s >= lo_f) & (s <= hi_f)]
    out = s[(s < lo_f) | (s > hi_f)].sort_values()
    if len(out) > BOX_MAX_OUTLIERS:
        out = out.iloc[np.linspace(0, len(out) - 1, BOX_MAX_OUTLIERS).astype(int)]
    return {"q1": q1, "median": med, "q3": q3,
            "lowerfence": float(inside.min()) if len(inside) else q1,
            "upperfence": float(inside.max()) if len(inside) else q3,
            "mean": float(s.mean()), "n": int(len(s)),
            "p99": float(s.quantile(0.99)), "out_n": int((~s.between(lo_f, hi_f)).sum()),
            "out_max": float(s.max()),
            "outliers": [round(float(v), 2) for v in out]}
