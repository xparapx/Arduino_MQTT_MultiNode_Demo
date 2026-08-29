"""Shared dashboard pieces (Phase 5): theme constants, METRICS, node palette,
read-only DB helpers, cached figure layer, radar / time-series / vision panels and
the section header. Moved verbatim out of dashboard.py so that dashboard.py (page 1)
and pages/2_diagnosis.py (page 2) draw from one place.

Everything here reads readings / occupancy through read-only connections; page 2
must only use the analysis helpers at the bottom (CI greps pages/ for raw tables).
"""
import copy, json, os, re, sqlite3, sys
from contextlib import closing
from datetime import datetime, timedelta
from time import perf_counter

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from aq.db import bucket_5min


def reset_perf() -> None:
    """Call at the top of a page script so [perf] 'full run' counts from there."""
    global _t0
    _t0 = perf_counter()


# ---- Config ----
DB         = "sensor_data.db"


NODES_PATH = "nodes.json"


ROW_LIMIT  = 5000          # recent rows to show


REFRESH_LIVE  = "60s"      # sections 1, 3, 4 (st.fragment run_every) -- data lands every 5 min


REFRESH_STATS = "5m"       # section 2 (28-day statistics)


MAX_COLS   = 4             # max grid columns (2 rows x 4 = 8 nodes)


STATS_DAYS = 28            # section 2 window (days); same as the model training window


BOX_MAX_OUTLIERS   = 300   # outlier dots sent per boxplot (evenly sampled by rank)


SCATTER_MAX_POINTS = 1500  # past points sent per node regime scatter (evenly by time)


DENSITY_BINS       = 24    # 2D density grid for the pooled regime scatter


DB_TIMEOUT_S       = 5     # wait this long on a write lock instead of failing


def _ro() -> sqlite3.Connection:
    """Read-only connection (?mode=ro). The dashboard can never write readings
    or occupancy by accident, and the busy timeout rides out hub.py inserts.
    Section 6 (reset) keeps its own read-write connection."""
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=DB_TIMEOUT_S)


# ---- [perf] server-side timing of one script run (Phase 1b). stderr -> journalctl.
#      `journalctl -u multinode_aq_dashboard -f | grep perf` shows one line per section.
_t0 = perf_counter()


def _perf(tag: str, t0: float = None) -> None:
    """One line per fragment run (t0 = fragment start) or per full script run."""
    print(f"[perf] {tag} {perf_counter() - (_t0 if t0 is None else t0):.2f}s",
          file=sys.stderr, flush=True)


# ---- Theme colors (seaborn pastel + dark) ----
BG        = "#1a1d24"      # charcoal background


PANEL_BG  = "#242832"      # panel/card background


INK       = "#e6e8ec"      # main text


INK_DIM   = "#aab2bd"      # dim text


GRID      = "#3a414e"      # grid/axis


# seaborn pastel palette
PASTEL = {
    "blue":   "#a1c9f4", "orange": "#ffb482", "green": "#8de5a1",
    "red":    "#ff9f9b", "purple": "#d0bbff", "brown": "#debb9b",
    "pink":   "#fab0e4", "gray":   "#cfcfcf", "yellow": "#fffea3",
    "cyan":   "#b9f2f0",
}


# section header colors
H_OVERVIEW = PASTEL["cyan"]


H_STATS    = PASTEL["orange"]


H_TS       = PASTEL["blue"]


H_EXPORT   = PASTEL["purple"]


# ---- Node identity colors (vivid; deliberately contrasted with the pastel
#      per-variable METRICS colors: high-saturation hues not used by the
#      6 displayed variables). Shared by radar + regime scatters. ----
NODE_PALETTE = ["#FF5CA8", "#8B7CFF", "#00E5B0", "#FFB300",
                "#4DD2FF", "#C4FF4D", "#FF8A5C", "#EAEAEA"]  # 8 nodes


NODE_COLOR: dict = {}          # filled once nodes are known (label-number order)


def node_color(node_id: str) -> str:
    return NODE_COLOR.get(node_id, NODE_PALETTE[0])


def node_fill(node_id: str, alpha: float = 0.32) -> str:
    h = node_color(node_id).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ========================================================
#  [METRICS] SEN55 + SCD30 sensor definitions (11 raw vars)
#  format: key:(label, unit, color, gauge_min, gauge_max)
#  Temp/Hum representative = SCD30 (scd_temp/scd_hum). SEN55 T/H kept in DB only.
# ========================================================
METRICS = {
    # SEN55
    "pm1p0":    ("PM1.0",  "\u00b5g/m\u00b3", PASTEL["pink"],   0,  100),
    "pm2p5":    ("PM2.5",  "\u00b5g/m\u00b3", PASTEL["orange"], 0,  100),
    "pm4p0":    ("PM4.0",  "\u00b5g/m\u00b3", PASTEL["brown"],  0,  100),
    "pm10p0":   ("PM10",   "\u00b5g/m\u00b3", PASTEL["red"],    0,  150),
    "sen_temp": ("Temp(SEN)", "\u00b0C",      PASTEL["gray"],   0,   50),
    "sen_hum":  ("Hum(SEN)",  "%",            PASTEL["gray"],   0,  100),
    "voc":      ("VOC",    "idx",             PASTEL["green"],  0,  500),
    "nox":      ("NOx",    "idx",             PASTEL["purple"], 0,  500),
    # SCD30
    "co2":      ("CO\u2082", "ppm",           PASTEL["cyan"],   400, 2000),
    "scd_temp": ("Temp",   "\u00b0C",         PASTEL["yellow"], 0,   50),
    "scd_hum":  ("Hum",    "%",               PASTEL["blue"],   0,  100),
}


# all 11 vars stored in DB; ALL_KEYS used for export (full raw)
ALL_KEYS = list(METRICS.keys())


# Displayed vars (6): CO2 + SCD30 temp/hum + PM2.5/PM10 + VOC.
# Hidden from display (DB/export only): pm1p0, pm4p0, nox, sen_temp, sen_hum.
# CO2 and VOC are ML targets -> placed LAST with emphasis.
# Order: PM2.5 -> PM10 -> Temp -> Hum -> CO2(target) -> VOC(target)
GAUGE_KEYS = ["pm2p5", "pm10p0", "scd_temp", "scd_hum", "co2", "voc"]


STATS_KEYS = ["pm2p5", "pm10p0", "scd_temp", "scd_hum", "co2", "voc"]


TS_KEYS    = ["pm2p5", "pm10p0", "scd_temp", "scd_hum", "co2", "voc"]


SENSOR_KEYS = ALL_KEYS    # backward-compat alias (export uses all 11)


# ML-target emphasis (CO2 & VOC). Both highlighted at the end of charts.
TARGET_KEYS   = ["co2", "voc"]


VOC_EMPH_BG   = "rgba(141,229,161,0.12)"   # soft green tint (VOC)


VOC_EMPH_LINE = PASTEL["green"]


CO2_EMPH_BG   = "rgba(185,242,240,0.12)"   # soft cyan tint (CO2)


CO2_EMPH_LINE = PASTEL["cyan"]


def emph_line(key):  return CO2_EMPH_LINE if key == "co2" else VOC_EMPH_LINE


def emph_bg(key):    return CO2_EMPH_BG if key == "co2" else VOC_EMPH_BG


# ---- Rule-based air-quality color grade (NOT ML; based on public guidelines) ----
#  Returns (grade_text, color). Conservative thresholds for indoor reference.
#  PM2.5/PM10 ~ KR MoE bands ; VOC/NOx index 100 = 24h baseline.
def grade_color(key: str, v):
    if v is None or pd.isna(v):
        return ("-", INK_DIM)
    good, mod, bad = PASTEL["green"], PASTEL["yellow"], PASTEL["red"]
    if key == "pm2p5":
        return ("good", good) if v <= 15 else ("moderate", mod) if v <= 35 else ("bad", bad)
    if key == "pm10p0":
        return ("good", good) if v <= 30 else ("moderate", mod) if v <= 80 else ("bad", bad)
    if key in ("voc", "nox"):     # index: 100 = 24h average baseline
        return ("good", good) if v <= 100 else ("moderate", mod) if v <= 200 else ("bad", bad)
    if key == "temp":
        return ("good", good) if 18 <= v <= 26 else ("moderate", mod) if 15 <= v <= 30 else ("bad", bad)
    if key == "hum":
        return ("good", good) if 40 <= v <= 60 else ("moderate", mod) if 30 <= v <= 70 else ("bad", bad)
    return ("-", INK_DIM)


# ---- Data loading ----
def _query_recent(limit: int) -> pd.DataFrame:
    """Most recent `limit` readings rows -> KST time, oldest first. SEN55 stores
    values directly (no scaling)."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, node, "
           "pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, "
           "co2, scd_temp, scd_hum "
           "FROM readings ORDER BY id DESC LIMIT ?")
    with closing(_ro()) as con:
        df = pd.read_sql_query(sql, con, params=(limit,))
    return df.iloc[::-1].reset_index(drop=True) if not df.empty else df


def data_version() -> "tuple[int, str]":
    """Cache key for everything on screen: (MAX(id), 5-min bucket of the newest
    row). Two PK lookups, ~1 ms. max_id keys the live figures (they rebuild only
    when a row arrived); the bucket keys the 28-day statistics (one rebuild per
    5-min bucket, however many rows land inside it)."""
    if not os.path.isfile(DB):
        return 0, ""
    with closing(_ro()) as con:
        row = con.execute("SELECT id, ts FROM readings "
                          "WHERE id = (SELECT MAX(id) FROM readings)").fetchone()
    if not row:
        return 0, ""
    try:
        return int(row[0]), bucket_5min(row[1])
    except ValueError:                      # unexpected ts format: fall back to raw
        return int(row[0]), str(row[1])


@st.cache_data(ttl=300, show_spinner=False)
def load_df(max_id: int, limit: int = ROW_LIMIT) -> pd.DataFrame:
    """Recent rows for the live sections. Re-queried only when max_id moved."""
    return _query_recent(limit)


def query_all() -> pd.DataFrame:
    """Every readings row. Uncached: only for on-demand export / reset backup."""
    return _query_recent(10_000_000)


@st.cache_data(ttl=300, show_spinner=False)
def load_all_for_stats(bucket: str) -> pd.DataFrame:
    """Rows for section 2 / node regime. Keyed on the newest 5-min bucket."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT node, pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, "
           "co2, scd_temp, scd_hum "
           "FROM readings WHERE ts >= datetime('now', ?)")
    with closing(_ro()) as con:
        return pd.read_sql_query(sql, con, params=(f"-{STATS_DAYS} days",))


def query_range(start_kst: datetime, end_kst: datetime) -> pd.DataFrame:
    """For date-range export. DB stores UTC; subtract 9h from KST range."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    start_utc = (start_kst - timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    end_utc   = (end_kst   - timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time_kst, node, "
           "pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, "
           "co2, scd_temp, scd_hum "
           "FROM readings WHERE ts BETWEEN ? AND ? ORDER BY id")
    with closing(_ro()) as con:
        return pd.read_sql_query(sql, con, params=(start_utc, end_utc))


@st.cache_data(ttl=300, show_spinner=False)
def get_time_bounds():
    """Min/max time in DB (KST) -- defaults for the range picker. Full scan, so cached."""
    if not os.path.isfile(DB):
        return None, None
    sql = ("SELECT MIN(datetime(ts,'+9 hours')), MAX(datetime(ts,'+9 hours')) "
           "FROM readings")
    with closing(_ro()) as con:
        lo, hi = con.execute(sql).fetchone()
    if not lo:
        return None, None
    return (datetime.fromisoformat(lo), datetime.fromisoformat(hi))


def load_node_labels() -> dict:
    if not os.path.isfile(NODES_PATH):
        return {}
    try:
        with open(NODES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"nodes.json read error: {e}")
        return {}


def label_of(node_id: str, labels: dict) -> str:
    return labels.get(node_id, node_id)


# ========================================================
#  [VISION] FOMO occupancy node (Nicla) -- `occupancy` table
#  - source : hub.py stores topic multinode_aq/+/occ
#  - pairing: env node <-> vision node share the SAME label in nodes.json
#             (16 flat pairs: two node IDs -> one CLASS_xx label)
#  - policy : occ* columns = analysis (SQL/join) ; cents JSON = UI only
# ========================================================
VIS_ACC  = "#FFB300"            # crosshair / occupancy accent (vivid amber)


VIS_GRID = "#2b3242"            # map grid line


@st.cache_data(ttl=300, show_spinner=False)
def _occ_table_exists() -> bool:
    if not os.path.isfile(DB):
        return False
    with closing(_ro()) as con:
        r = con.execute("SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='occupancy'").fetchone()
    return bool(r)


@st.cache_data(ttl=60, show_spinner=False)
def load_occ_latest() -> pd.DataFrame:
    """Last bucket per vision node (+9h KST time)."""
    if not _occ_table_exists():
        return pd.DataFrame()
    sql = ("SELECT o.node, datetime(o.ts,'+9 hours') AS recv_time, "
           "o.occ, o.occ_med, o.occ_max, o.occ_last, o.cents, o.w, o.n "
           "FROM occupancy o JOIN (SELECT node, MAX(id) AS mid FROM occupancy "
           "GROUP BY node) m ON o.id = m.mid")
    with closing(_ro()) as con:
        return pd.read_sql_query(sql, con)


@st.cache_data(ttl=60, show_spinner=False)
def load_occ_hist(node_id: str, limit: int = 24) -> pd.DataFrame:
    """Recent buckets for the mini bar strip (oldest -> newest)."""
    if not _occ_table_exists():
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, occ, occ_max, n "
           "FROM occupancy WHERE node=? ORDER BY id DESC LIMIT ?")
    with closing(_ro()) as con:
        df = pd.read_sql_query(sql, con, params=(node_id, limit))
    return df.iloc[::-1].reset_index(drop=True)


def vision_node_for(env_node: str, labels: dict, occ_nodes) -> "str | None":
    """Find the vision node sharing this env node's label (nodes.json pairing)."""
    lbl = label_of(env_node, labels)
    for vn in occ_nodes:
        if label_of(vn, labels) == lbl:
            return vn
    return None


@st.cache_data(ttl=60)
def load_merged_analysis(min_n_env: int = 0, min_n_occ: int = 25) -> pd.DataFrame:
    """Analysis-ready dataframe: env(readings) x vision(occupancy) merged on
    (bucket ts, room label). Exact join -- both sides publish on the same
    NTP-aligned bucket grid, so no resample/asof needed. Rows whose occ bucket
    has too few samples (n < min_n_occ) are dropped as low-quality.
    Columns: t_kst, room, co2, voc, scd_temp, scd_hum, pm2p5, pm10p0,
             occ_mean, occ_med, occ_max, occ_n
    """
    if not _occ_table_exists():
        return pd.DataFrame()
    labels_ = load_node_labels()
    with closing(_ro()) as con:
        env = pd.read_sql_query(
            "SELECT ts, node, co2, voc, scd_temp, scd_hum, pm2p5, pm10p0, n "
            "FROM readings", con)
        occ = pd.read_sql_query(
            "SELECT ts, node, occ AS occ_mean, occ_med, occ_max, n AS occ_n "
            "FROM occupancy WHERE n >= ?", con, params=(min_n_occ,))
    if env.empty or occ.empty:
        return pd.DataFrame()
    env["room"] = env["node"].map(labels_)
    occ["room"] = occ["node"].map(labels_)
    env = env.dropna(subset=["room"])
    occ = occ.dropna(subset=["room"])
    m = pd.merge(env.drop(columns=["node"]),
                 occ[["ts", "room", "occ_mean", "occ_med", "occ_max", "occ_n"]],
                 on=["ts", "room"], how="inner")
    if m.empty:
        return m
    m["t_kst"] = (pd.to_datetime(m["ts"]) + pd.Timedelta(hours=9)
                  ).dt.strftime("%Y-%m-%d %H:%M:%S")
    cols = ["t_kst", "room", "co2", "voc", "scd_temp", "scd_hum",
            "pm2p5", "pm10p0", "occ_mean", "occ_med", "occ_max", "occ_n"]
    return m[cols].sort_values(["room", "t_kst"]).reset_index(drop=True)


# crosshair map CSS (plain string; kept out of f-string to avoid brace escapes)
_VIS_CSS = """
<style>
  .vp{font-family:'Pretendard','Malgun Gothic',system-ui,sans-serif;
      background:__PANEL__;border-radius:12px;padding:12px 14px;color:__INK__;}
  .vp .hd{display:flex;justify-content:space-between;align-items:center;}
  .vp .hd b{font-size:13px;}
  .vp .fresh{font-size:10px;padding:2px 9px;border-radius:20px;
             border:1px solid #3a414e;color:#8de5a1;}
  .vp .fresh.stale{color:#ff9f9b;}
  .vp .chips{display:flex;gap:8px;margin:8px 0 10px;width:clamp(288px,50%,373px);}
  .vp .chip{background:#1a1f29;border:1px solid #333b49;border-radius:8px;
            padding:4px 12px;text-align:center;flex:1;min-width:0;}
  .vp .chip .v{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums;}
  .vp .chip.acc .v{color:__ACC__;}
  .vp .chip .l{font-size:9.5px;color:#aab2bd;letter-spacing:.08em;}
  .vp .maprow{display:flex;gap:12px;align-items:stretch;}
  .vp .map{position:relative;flex:0 0 clamp(288px,50%,373px);aspect-ratio:4/3;height:auto;background:#161a22;
           border:1px dashed #3a414e;border-radius:8px;overflow:hidden;
           background-image:
             repeating-linear-gradient(0deg,transparent,transparent 23px,__GRID__ 24px),
             repeating-linear-gradient(90deg,transparent,transparent 23px,__GRID__ 24px);}
  .vp .map .tag{position:absolute;left:7px;bottom:5px;font-size:9px;color:#4a5568;}
  .vp .map .none{position:absolute;inset:0;display:flex;align-items:center;
                 justify-content:center;font-size:11px;color:#5f6f7e;}
  .vp .ch{position:absolute;width:38px;height:38px;
          transform:translate(-50%,-50%);
          animation:vblink 1.15s ease-in-out infinite;}
  .vp .ch::before{content:'';position:absolute;left:50%;top:-4px;bottom:-4px;
                  width:2px;background:__ACC__;transform:translateX(-50%);}
  .vp .ch::after{content:'';position:absolute;top:50%;left:-4px;right:-4px;
                 height:2px;background:__ACC__;transform:translateY(-50%);}
  .vp .ch b{position:absolute;inset:9px;border:2px solid __ACC__;
            border-radius:50%;}
  .vp .ch i{position:absolute;left:50%;top:50%;width:4px;height:4px;
            background:__ACC__;border-radius:50%;
            transform:translate(-50%,-50%);}
  @keyframes vblink{0%,100%{opacity:1;}50%{opacity:.18;}}
  .vp .side{flex:1;display:flex;flex-direction:column;justify-content:flex-end;}
  .vp .side .cap{font-size:10px;color:#aab2bd;margin-bottom:6px;}
  .vp .bars{display:flex;align-items:flex-end;gap:2px;height:74px;}
  .vp .bars i{flex:1;background:#3d4c60;border-radius:2px 2px 0 0;min-height:2px;}
  .vp .bars i.now{background:__ACC__;}
  .vp .ft{font-size:9.5px;color:#5f6f7e;margin-top:8px;}
</style>
"""


def render_vision_panel(env_node: str, labels: dict):
    """Section-3 right column: blinking-crosshair occupancy map for the vision
    node paired (same label) with the selected env node."""
    lbl = label_of(env_node, labels)
    occ_latest = load_occ_latest()
    if occ_latest.empty:
        st.info("비전(재실) 데이터가 아직 없습니다 — occ 노드 발행과 "
                "hub.py의 occ 구독(occupancy 테이블)을 확인하세요.")
        return
    vn = vision_node_for(env_node, labels, occ_latest["node"].tolist())
    if vn is None:
        st.info(f"'{lbl}' 교실에 매핑된 비전 노드가 없습니다. "
                "nodes.json에서 비전 노드 ID를 같은 라벨로 등록하세요.")
        return

    row = occ_latest[occ_latest["node"] == vn].iloc[0]
    try:
        cents = json.loads(row["cents"] or "[]")
    except Exception:
        cents = []
    w = int(row["w"]) if row["w"] else 96
    hist = load_occ_hist(vn)

    # freshness: bucket older than ~12 min -> stale badge
    stale = True
    try:
        age = datetime.now() - datetime.fromisoformat(str(row["recv_time"]))
        stale = age > timedelta(minutes=12)
    except Exception:
        pass
    fresh_cls = "fresh stale" if stale else "fresh"
    fresh_txt = "지연" if stale else "LIVE"

    # crosshairs (staggered blink for visual rhythm)
    ch = ""
    for i, c in enumerate(cents):
        try:
            x = float(c[0]) / w * 100.0
            y = float(c[1]) / w * 100.0
        except Exception:
            continue
        ch += (f"<div class='ch' style='left:{x:.1f}%;top:{y:.1f}%;"
               f"animation-delay:{i*0.15:.2f}s'><b></b><i></i></div>")
    if not ch:
        ch = "<div class='none'>버킷 내 탐지 없음</div>"

    # history mini bars (scaled by occ_max of the window)
    bars = ""
    if not hist.empty:
        top = max(float(hist["occ_max"].max() or 0), 1.0)
        vals = hist["occ"].fillna(0).tolist()
        for j, v in enumerate(vals):
            hpc = max(3, int(float(v) / top * 100))
            cls = " class='now'" if j == len(vals) - 1 else ""
            bars += f"<i{cls} style='height:{hpc}%'></i>"

    css = (_VIS_CSS.replace("__PANEL__", PANEL_BG).replace("__INK__", INK)
                   .replace("__ACC__", VIS_ACC).replace("__GRID__", VIS_GRID))
    occ_v  = f"{float(row['occ']):.1f}" if row["occ"] is not None else "-"
    body = f"""
    <div class="vp">
      <div class="hd"><b>재실 탐지 — {lbl} <span style="color:#7c8b9c">
        ({vn})</span></b><span class="{fresh_cls}">{fresh_txt}</span></div>
      <div class="chips">
        <div class="chip acc"><div class="v">{occ_v}</div><div class="l">5분 평균</div></div>
        <div class="chip"><div class="v">{row['occ_med'] if row['occ_med'] is not None else '-'}</div><div class="l">중앙값</div></div>
        <div class="chip"><div class="v">{row['occ_max'] if row['occ_max'] is not None else '-'}</div><div class="l">최대</div></div>
        <div class="chip"><div class="v">{row['n'] if row['n'] is not None else '-'}</div><div class="l">샘플 n</div></div>
      </div>
      <div class="maprow">
        <div class="map">{ch}<span class="tag">CAMERA VIEW 4:3 &middot; coords /{w}</span></div>
        <div class="side">
          <div class="cap">최근 버킷 추이 (평균 인원)</div>
          <div class="bars">{bars}</div>
          <div class="ft">조준선 = 최대 인원({row['occ_max']}) 시점 위치 (4:3 프레임 상대좌표) &middot;
            버킷 {row['recv_time']} KST<br>영상 비전송 &middot; 좌표만 수집 (온디바이스 추론)</div>
        </div>
      </div>
    </div>"""
    components.html(css + body, height=436)


# ---- Normalize / charts ----
def normalize(key: str, value):
    _, _, _, gmin, gmax = METRICS[key]
    if gmax == gmin or pd.isna(value):
        return 0.0
    return float(np.clip((value - gmin) / (gmax - gmin), 0.0, 1.0))


def make_node_radar(vals: dict, node_id: str = "") -> go.Figure:
    """Node live status: one radar over GAUGE_KEYS, each var normalized 0-1
    by its METRICS (gmin, gmax) range. Axis label shows name + current value."""
    cats, r = [], []
    for k in GAUGE_KEYS:
        label, unit, _, gmin, gmax = METRICS[k]
        v = vals.get(k)
        if v is None or pd.isna(v):
            rv, vtxt = 0.0, "-"
        else:
            rv = float(np.clip((float(v) - gmin) / (gmax - gmin), 0.0, 1.0))
            vtxt = f"{float(v):.1f}"
        cats.append(f"{label}<br><b>{vtxt}</b> {unit}")
        r.append(rv)
    cats.append(cats[0]); r.append(r[0])          # close polygon
    fig = go.Figure(go.Scatterpolar(
        r=r, theta=cats, fill="toself", mode="lines+markers",
        line=dict(color=node_color(node_id), width=2),
        marker=dict(size=4, color=node_color(node_id)),
        fillcolor=node_fill(node_id),
        hoverinfo="skip", showlegend=False,
    ))
    fig.update_layout(
        height=300, margin=dict(l=56, r=56, t=30, b=26),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": INK},
        polar=dict(
            bgcolor="rgba(255,255,255,0.03)",
            radialaxis=dict(range=[0, 1], showticklabels=False,
                            gridcolor=GRID, linecolor=GRID),
            angularaxis=dict(tickfont={"size": 10, "color": INK},
                             gridcolor=GRID, linecolor=GRID),
        ),
    )
    return fig


def radar_values(vals: dict) -> tuple[list, list]:
    """(theta labels, r) for one node: GAUGE_KEYS normalised by their gauge range,
    axis label = name + current value (same text as the old per-node radar)."""
    cats, r = [], []
    for k in GAUGE_KEYS:
        label, unit, _, gmin, gmax = METRICS[k]
        v = vals.get(k)
        if v is None or pd.isna(v):
            rv, vtxt = 0.0, "-"
        else:
            rv = float(np.clip((float(v) - gmin) / (gmax - gmin), 0.0, 1.0))
            vtxt = f"{float(v):.1f}"
        cats.append(f"{label}<br><b>{vtxt}</b> {unit}")
        r.append(rv)
    cats.append(cats[0]); r.append(r[0])          # close polygon
    return cats, r


def make_radar_grid(nodes: list, latest: dict, labels: dict, ncols: int = MAX_COLS) -> go.Figure:
    """Phase 5 (decision a): all node radars in ONE figure as a rows x ncols grid of
    polar subplots -- one plotly element per refresh instead of eight. Same
    polygon, colours and axis labels as make_node_radar; the card title becomes
    the subplot title."""
    n = len(nodes)
    ncols = max(1, min(n, ncols))
    nrows = max(1, (n + ncols - 1) // ncols)
    fig = make_subplots(rows=nrows, cols=ncols,
                        specs=[[{"type": "polar"}] * ncols for _ in range(nrows)],
                        subplot_titles=[label_of(nd, labels) for nd in nodes],
                        horizontal_spacing=0.06, vertical_spacing=0.16)
    for i, nd in enumerate(nodes):
        cats, r = radar_values(latest.get(nd, {}))
        fig.add_trace(go.Scatterpolar(
            r=r, theta=cats, fill="toself", mode="lines+markers",
            line=dict(color=node_color(nd), width=2),
            marker=dict(size=4, color=node_color(nd)),
            fillcolor=node_fill(nd), hoverinfo="skip", showlegend=False,
        ), row=i // ncols + 1, col=i % ncols + 1)
    polar_style = dict(
        bgcolor="rgba(255,255,255,0.03)",
        radialaxis=dict(range=[0, 1], showticklabels=False, gridcolor=GRID, linecolor=GRID),
        angularaxis=dict(tickfont={"size": 9, "color": INK}, gridcolor=GRID, linecolor=GRID),
    )
    fig.update_polars(**polar_style)
    fig.update_annotations(font=dict(size=14, color=INK))
    fig.update_layout(height=300 * nrows + 40, margin=dict(l=40, r=40, t=50, b=20),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": INK})
    return fig


@st.cache_resource(ttl=300, max_entries=8, show_spinner=False)
def radar_grid_figure(stamps: tuple, _nodes: list, _latest: dict, _labels: dict) -> go.Figure:
    """Section 1: the whole grid, keyed on (node, newest recv_time) per node."""
    return make_radar_grid(list(_nodes), _latest, _labels)


def node_card(node_id: str, vals: dict, labels: dict):
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;font-weight:700;color:{INK};"
            f"font-size:14px;margin-bottom:2px;'>{label_of(node_id, labels)}</div>",
            unsafe_allow_html=True)
        # one radar per node (6 vars normalized by gauge range); rebuilt only
        # when this node has a newer row (cache key = its recv_time)
        st.plotly_chart(radar_figure(node_id, str(vals.get("recv_time")), vals),
                        width="stretch", key=f"radar_{node_id}")


def box_stats(s: pd.Series) -> "dict | None":
    """Tukey box statistics of one series, computed here so the browser receives
    five numbers + a bounded outlier sample instead of the whole column."""
    s = s.dropna()
    if s.empty:
        return None
    q1, med, q3 = (float(v) for v in s.quantile([0.25, 0.5, 0.75]))
    lo_f, hi_f = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    inside = s[(s >= lo_f) & (s <= hi_f)]
    out = s[(s < lo_f) | (s > hi_f)].sort_values()
    if len(out) > BOX_MAX_OUTLIERS:           # keep extremes, thin the middle
        out = out.iloc[np.linspace(0, len(out) - 1, BOX_MAX_OUTLIERS).astype(int)]
    return dict(q1=q1, median=med, q3=q3,
                lowerfence=float(inside.min()) if len(inside) else q1,
                upperfence=float(inside.max()) if len(inside) else q3,
                mean=float(s.mean()), n=int(len(s)), outliers=out.to_numpy())


def make_boxplots(dfa: pd.DataFrame) -> go.Figure:
    """Per-variable boxplots (PM1.0/PM4.0 excluded). VOC last, with emphasis.
    Boxes are drawn from box_stats() (precomputed), outliers as a thin scatter."""
    keys = STATS_KEYS
    fig = make_subplots(rows=1, cols=len(keys),
                        subplot_titles=[METRICS[k][0] for k in keys])
    for i, key in enumerate(keys, start=1):
        _, unit, color, _, _ = METRICS[key]
        is_target = key in TARGET_KEYS
        name = METRICS[key][0]
        bs = box_stats(dfa[key])
        if bs is None:
            continue
        fig.add_trace(go.Box(x=[name], name=name,
                             q1=[bs["q1"]], median=[bs["median"]], q3=[bs["q3"]],
                             lowerfence=[bs["lowerfence"]], upperfence=[bs["upperfence"]],
                             mean=[bs["mean"]],
                             marker_color=color, line={"color": color},
                             fillcolor=(emph_line(key) if is_target else "rgba(255,255,255,0.05)"),
                             showlegend=False), row=1, col=i)
        if len(bs["outliers"]):
            fig.add_trace(go.Scatter(x=[name] * len(bs["outliers"]), y=bs["outliers"],
                                     mode="markers", showlegend=False, hoverinfo="skip",
                                     marker=dict(color=color, size=3, opacity=0.6)),
                          row=1, col=i)
        fig.update_yaxes(title_text=unit, row=1, col=i,
                         title_font={"size": 10, "color": INK_DIM},
                         gridcolor=GRID, tickfont={"color": INK_DIM})
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font={"color": INK})
    # highlight CO2 & VOC subplot titles (last two = ML targets)
    fig.update_annotations(font_size=12, font_color=INK_DIM)
    anns = fig.layout.annotations
    for i, key in enumerate(keys):
        if key in TARGET_KEYS and i < len(anns):
            anns[i].font.color = emph_line(key)
            anns[i].text = f"{METRICS[key][0]} \u2605"   # star marks target
    return fig


def make_corr(dfa: pd.DataFrame) -> go.Figure:
    corr = dfa[STATS_KEYS].corr()
    labels_x = [METRICS[k][0] for k in STATS_KEYS]
    # pastel diverging color scale (red <-> grey <-> blue)
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=labels_x, y=labels_x,
        text=np.round(corr.values, 2), texttemplate="%{text}",
        textfont={"color": "#2a2d34"},
        colorscale=[[0.0, PASTEL["red"]], [0.5, "#eceff4"], [1.0, PASTEL["blue"]]],
        zmid=0, zmin=-1, zmax=1,
        colorbar=dict(title="r", tickfont={"color": INK_DIM}), xgap=2, ygap=2,
    ))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                      title=dict(text="Correlation", x=0.5, xanchor="center",
                                 font=dict(size=12, color=INK_DIM)),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": INK},
                      xaxis=dict(tickfont={"size": 9, "color": INK_DIM}, automargin=True),
                      yaxis=dict(tickfont={"size": 9, "color": INK_DIM}, automargin=True))
    fig.update_traces(textfont_size=9)   # cell numbers smaller for narrow column
    return fig


def make_target_by_node(dfa: pd.DataFrame, labels: dict, key: str) -> go.Figure:
    """Mean value of an ML-target var (co2 or voc) per node. Horizontal bars:
    node=y, value=x. Descending (highest on top). Tone gradation:
    higher value -> deeper color (VOC=green tone, CO2=cyan tone)."""
    g = (dfa.groupby("node")[key].mean()
         .sort_values(ascending=False))            # highest first
    names = [label_of(n, labels) for n in g.index]
    vals = g.values
    n = len(vals)
    vmax = float(vals.max()) if n and vals.max() > 0 else 1.0
    vmin = float(vals.min()) if n else 0.0
    # color stops: (light) -> (deep), per target
    if key == "co2":
        lo, hi = (185, 242, 240), (20, 110, 130)   # light cyan -> deep teal
    else:  # voc
        lo, hi = (205, 238, 214), (35, 120, 70)    # light green -> deep green
    def grad(v):
        t = 0.5 if vmax == vmin else (v - vmin) / (vmax - vmin)
        r = int(lo[0] + (hi[0]-lo[0]) * t)
        gg = int(lo[1] + (hi[1]-lo[1]) * t)
        b = int(lo[2] + (hi[2]-lo[2]) * t)
        return f"rgb({r},{gg},{b})"
    colors = [grad(v) for v in vals]
    label, unit, _, _, _ = METRICS[key]
    # vertical bar: highest on the LEFT
    fig = go.Figure(go.Bar(
        x=names, y=vals, orientation="v",
        marker_color=colors,
        text=[f"{v:.0f}" for v in vals], textposition="outside",
        showlegend=False,
    ))
    fig.update_layout(
        height=215, margin=dict(l=10, r=20, t=28, b=28),
        title=dict(text=f"{label} by node \u2605", x=0.5, xanchor="center",
                   font=dict(size=12, color=emph_line(key))),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=emph_bg(key),
        font={"color": INK},
        xaxis=dict(tickfont={"size": 10, "color": INK_DIM}, automargin=True),
        yaxis=dict(title=f"{label} ({unit})", gridcolor=GRID,
                   tickfont={"color": INK_DIM}, title_font={"size": 10, "color": INK_DIM}),
        bargap=0.35,
    )
    return fig


def density_heatmap(zx: pd.Series, zy: pd.Series, amax: float, bins: int,
                    colorscale) -> go.Heatmap:
    """2D density of robust-scaled points, aggregated on the server with
    np.histogram2d (bins x bins cells) instead of shipping every point to the
    browser as go.Histogram2d did. Values are clipped into the range first so
    off-scale points pile up in the edge cells, as before."""
    H, xe, ye = np.histogram2d(zx.clip(-amax, amax), zy.clip(-amax, amax),
                               bins=bins, range=[[-amax, amax], [-amax, amax]])
    return go.Heatmap(z=H.T, x=(xe[:-1] + xe[1:]) / 2, y=(ye[:-1] + ye[1:]) / 2,
                      colorscale=colorscale, showscale=False, zsmooth="best",
                      hoverinfo="skip")


def make_regime_base(dfa: pd.DataFrame, labels: dict):
    """CO2-VOC RELATIVE regime scatter (RobustScaling), cacheable part: density
    background + quadrant labels + axes. Returns (fig, meta); meta carries the
    scaling (median/IQR per axis), the range and the node list so that
    overlay_current() can place the live markers on the same axes later
    without touching dfa again.
    RobustScaling: (v - median) / IQR  -> robust to outliers & skew, stable origin.
    Purpose = RELATIVE regime (where a point sits within the distribution), good for
    flexible regime-switching detection. NOTE: normalization removes ABSOLUTE level
    (e.g. 500 vs 900ppm both map near 0); absolute level is shown by the CO2 barplot.
    Density gradation: denser quadrant = deeper tint. Foundation for future GMM.
    v2: past-point scatter removed (readability) -> density bg + current vectors only,
    enlarged current markers + class label annotated at each arrow tip.
    Quadrant split at median(=0): low-low=Clean / lowCO2-highVOC=Matter>Human /
    highCO2-lowVOC=Human>Matter / high-high=Human~=Matter."""
    d = dfa[["co2", "voc", "node"]].dropna()
    if len(d) < 3:
        fig = go.Figure()
        fig.add_annotation(text="Not enough data yet for regime scatter",
                           x=0.5, y=0.5, showarrow=False, font={"color": INK_DIM})
        fig.update_layout(height=420, paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font={"color": INK})
        return fig, None

    # RobustScaling: (v - median) / IQR per axis (robust to outliers/skew)
    def robust(s):
        med = s.median()
        iqr = s.quantile(0.75) - s.quantile(0.25)
        return (s - med) / iqr if iqr and iqr > 0 else (s - med) * 0.0
    zco2 = robust(d["co2"]); zvoc = robust(d["voc"])
    # normalization params (reused by overlay_current for the live values)
    co2_med = d["co2"].median(); co2_iqr = d["co2"].quantile(0.75) - d["co2"].quantile(0.25)
    voc_med = d["voc"].median(); voc_iqr = d["voc"].quantile(0.75) - d["voc"].quantile(0.25)

    # axis range from PERCENTILES (not max) so a single outlier can't blow up scale
    def prange(s):
        lo, hi = s.quantile(0.02), s.quantile(0.98)
        return max(abs(lo), abs(hi))
    amax = float(max(prange(zco2), prange(zvoc)))
    amax = (amax * 1.15) if amax > 0 else 1.0
    amax = min(max(amax, 1.5), 3.0)       # 1.5~3.0 (max 3 grid at dtick=1)

    fig = go.Figure()
    # density background (server-aggregated; clipped so out-of-range points don't distort)
    fig.add_trace(density_heatmap(
        zco2, zvoc, amax, DENSITY_BINS,
        colorscale=[[0.0, "rgba(0,0,0,0)"], [0.15, "rgba(120,170,255,0.10)"],
                    [0.5, "rgba(120,170,255,0.28)"], [1.0, "rgba(90,140,255,0.55)"]],
    ))
    # quadrant labels with inequality notation (Human vs Matter)
    #  x+ = CO2 high (human factor) ; y+ = VOC high (matter factor)
    qlabels = [( amax*0.6,  amax*0.6, "Human \u2248 Matter"),   # high-high (both)
               (-amax*0.6,  amax*0.6, "Matter \u003e Human"),   # lowCO2-highVOC
               ( amax*0.6, -amax*0.6, "Human \u003e Matter"),   # highCO2-lowVOC
               (-amax*0.6, -amax*0.6, "Clean")]                 # low-low
    for qx, qy, qt in qlabels:
        fig.add_annotation(x=qx, y=qy, text=qt, showarrow=False,
                           font={"size": 11, "color": INK})
    fig.update_layout(
        height=440, margin=dict(l=10, r=10, t=36, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": INK},
        xaxis=dict(title="CO\u2082 (robust)  \u2192 Human factor", gridcolor=GRID, dtick=1,
                   tickfont={"color": INK_DIM}, range=[-amax, amax],
                   zeroline=True, zerolinecolor=INK, zerolinewidth=2,
                   showline=True, linecolor=INK_DIM, mirror=True),
        yaxis=dict(title="VOC (robust)  \u2192 Matter factor", gridcolor=GRID, dtick=1,
                   tickfont={"color": INK_DIM}, range=[-amax, amax],
                   zeroline=True, zerolinecolor=INK, zerolinewidth=2,
                   showline=True, linecolor=INK_DIM, mirror=True),
        legend=dict(font={"size": 12, "color": INK_DIM}, orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    # node colors: shared vivid identity palette (see NODE_PALETTE)
    meta = dict(co2_med=co2_med, co2_iqr=co2_iqr, voc_med=voc_med, voc_iqr=voc_iqr,
                amax=amax, nodes=sorted(d["node"].unique(), key=lambda n: labels.get(n, n)))
    return fig, meta


def overlay_current(fig: go.Figure, meta: dict, latest: dict, labels: dict) -> go.Figure:
    """Live layer on top of make_regime_base(): per node a vector from the
    origin + enlarged marker + class label at the arrow tip. The base comes
    from st.cache_resource (shared object), so it is deep-copied first; the
    additions are batched because every add_annotation() re-validates the
    whole annotation list (16 calls cost 6x one batched assignment)."""
    if not meta or not latest:
        return fig
    fig = copy.deepcopy(fig)
    amax = meta["amax"]
    def rc(v, med, iqr): return (v - med) / iqr if iqr and iqr > 0 else 0.0
    def clip(v):                          # clamp into [-amax, amax] for display
        return max(-amax, min(amax, v))
    anns, traces = [], []
    for nd in meta["nodes"]:
        cur = latest.get(nd)
        if not cur:
            continue
        cv, vv = cur.get("co2"), cur.get("voc")
        if cv is None or vv is None or pd.isna(cv) or pd.isna(vv):
            continue
        rx = rc(cv, meta["co2_med"], meta["co2_iqr"])
        ry = rc(vv, meta["voc_med"], meta["voc_iqr"])
        cx, cy = clip(rx), clip(ry)          # clip into view; flag if outside
        outside = (cx != rx) or (cy != ry)
        col = node_color(nd)
        # vector: origin -> current (arrow)
        anns.append(dict(x=cx, y=cy, ax=0, ay=0,
                         xref="x", yref="y", axref="x", ayref="y",
                         showarrow=True, arrowhead=2, arrowsize=1.0,
                         arrowwidth=2, arrowcolor=col, opacity=0.95))
        # enlarged current marker. Diamond if clipped (out of range).
        traces.append(go.Scatter(
            x=[cx], y=[cy], mode="markers",
            name=f"{label_of(nd, labels)} (now)", legendgroup=nd,
            showlegend=False,
            marker=dict(size=16, color=col,
                        symbol=("diamond-open" if outside else "star"),
                        line=dict(width=1.6, color=INK)),
            hovertemplate=(f"{label_of(nd, labels)} now<br>CO2 r=%{{x:.2f}}"
                           f"<br>VOC r=%{{y:.2f}}"
                           f"{' (범위밖)' if outside else ''}<extra></extra>"),
        ))
        # class label at the arrow tip (offset outward along the vector)
        norm = (cx * cx + cy * cy) ** 0.5
        ux, uy = ((cx / norm, cy / norm) if norm > 1e-6 else (1.0, 0.0))
        off = amax * 0.07
        lx = max(-amax * 0.98, min(amax * 0.98, cx + ux * off))
        ly = max(-amax * 0.98, min(amax * 0.98, cy + uy * off))
        anns.append(dict(x=lx, y=ly, text=label_of(nd, labels),
                         showarrow=False,
                         xanchor=("left" if ux >= 0 else "right"),
                         yanchor=("bottom" if uy >= 0 else "top"),
                         font={"size": 9, "color": col},
                         bgcolor="rgba(0,0,0,0.45)",
                         bordercolor=col, borderwidth=1, borderpad=1,
                         opacity=0.95))
    if traces:
        fig.add_traces(traces)
        fig.layout.annotations = tuple(fig.layout.annotations) + tuple(anns)
    return fig


def make_regime_scatter(dfa: pd.DataFrame, labels: dict, latest: dict = None) -> go.Figure:
    """Uncached base + overlay in one call (scripts / tests)."""
    fig, meta = make_regime_base(dfa, labels)
    return overlay_current(fig, meta, latest, labels)


def make_node_regime_base(dfa: pd.DataFrame, node_id: str, labels: dict):
    """Per-node regime scatter using THAT NODE's own median/IQR (within-node
    RobustScaling). Answers 'is this room different from its OWN baseline?'.
    Complements the pooled scatter (which compares nodes). IQR-small nodes can
    look jumpy -- that's expected (each node scaled to itself).
    Cacheable part (density + past points + quadrants + axes); returns (fig, meta)."""
    d = dfa[dfa["node"] == node_id][["co2", "voc"]].dropna()
    nm = label_of(node_id, labels)
    if len(d) < 3:
        fig = go.Figure()
        fig.add_annotation(text=f"{nm}: not enough data yet",
                           x=0.5, y=0.5, showarrow=False, font={"color": INK_DIM})
        fig.update_layout(height=360, paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font={"color": INK})
        return fig, None

    # within-node RobustScaling (this node's own median/IQR)
    def robust(s):
        med = s.median(); iqr = s.quantile(0.75) - s.quantile(0.25)
        return ((s - med) / iqr if iqr and iqr > 0 else (s - med) * 0.0), med, iqr
    zco2, co2_med, co2_iqr = robust(d["co2"])
    zvoc, voc_med, voc_iqr = robust(d["voc"])

    fig = go.Figure()
    # percentile-based symmetric range (outlier-safe)
    def prange(s):
        return max(abs(s.quantile(0.02)), abs(s.quantile(0.98)))
    amax = float(max(prange(zco2), prange(zvoc)))
    amax = min(max((amax * 1.15) if amax > 0 else 1.0, 1.5), 3.0)

    # density backdrop (this node only, server-aggregated)
    fig.add_trace(density_heatmap(
        zco2, zvoc, amax, 20,
        colorscale=[[0.0, "rgba(0,0,0,0)"], [0.2, "rgba(120,170,255,0.12)"],
                    [0.6, "rgba(120,170,255,0.30)"], [1.0, "rgba(90,140,255,0.55)"]],
    ))
    # past points: at most SCATTER_MAX_POINTS, evenly spaced in time (rows are
    # id-ordered) so the cloud keeps its shape while the payload stays bounded
    if len(zco2) > SCATTER_MAX_POINTS:
        idx = np.linspace(0, len(zco2) - 1, SCATTER_MAX_POINTS).astype(int)
        zco2, zvoc = zco2.iloc[idx], zvoc.iloc[idx]
    fig.add_trace(go.Scatter(
        x=zco2.clip(-amax, amax), y=zvoc.clip(-amax, amax), mode="markers",
        marker=dict(size=5, color=node_color(node_id),
                    line=dict(width=0.3, color="rgba(0,0,0,0.3)"), opacity=0.4),
        showlegend=False, hoverinfo="skip",
    ))
    # quadrant labels (inequality)
    for qx, qy, qt in [( amax*0.6,  amax*0.6, "Human \u2248 Matter"),
                       (-amax*0.6,  amax*0.6, "Matter \u003e Human"),
                       ( amax*0.6, -amax*0.6, "Human \u003e Matter"),
                       (-amax*0.6, -amax*0.6, "Clean")]:
        fig.add_annotation(x=qx, y=qy, text=qt, showarrow=False,
                           font={"size": 10, "color": INK_DIM})
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=34, b=36),
        title=dict(text=f"{nm} \u2014 자기 기준 레짐 (within-node Robust)",
                   x=0.5, xanchor="center", font=dict(size=12, color=INK)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": INK},
        xaxis=dict(title="CO\u2082 (robust)", gridcolor=GRID, dtick=1, range=[-amax, amax],
                   tickfont={"color": INK_DIM}, zeroline=True, zerolinecolor=INK,
                   zerolinewidth=2, showline=True, linecolor=INK_DIM, mirror=True),
        yaxis=dict(title="VOC (robust)", gridcolor=GRID, dtick=1, range=[-amax, amax],
                   tickfont={"color": INK_DIM}, zeroline=True, zerolinecolor=INK,
                   zerolinewidth=2, showline=True, linecolor=INK_DIM, mirror=True),
    )
    meta = dict(co2_med=co2_med, co2_iqr=co2_iqr, voc_med=voc_med, voc_iqr=voc_iqr,
                amax=amax, name=nm)
    return fig, meta


def overlay_node_current(fig: go.Figure, meta: dict, cur: dict) -> go.Figure:
    """Live layer for make_node_regime_base(): vector + star on the node's own scale."""
    if not meta or not cur:
        return fig
    amax = meta["amax"]; nm = meta["name"]
    def rc(v, med, iqr): return (v - med) / iqr if iqr and iqr > 0 else 0.0
    def clip(v): return max(-amax, min(amax, v))
    cv, vv = cur.get("co2"), cur.get("voc")
    if cv is None or vv is None or pd.isna(cv) or pd.isna(vv):
        return fig
    rx = rc(cv, meta["co2_med"], meta["co2_iqr"])
    ry = rc(vv, meta["voc_med"], meta["voc_iqr"])
    cx, cy = clip(rx), clip(ry)
    outside = (cx != rx) or (cy != ry)
    fig = copy.deepcopy(fig)              # base is a shared cache_resource object
    fig.layout.annotations = tuple(fig.layout.annotations) + (dict(
        x=cx, y=cy, ax=0, ay=0, xref="x", yref="y",
        axref="x", ayref="y", showarrow=True, arrowhead=2,
        arrowsize=1.2, arrowwidth=2,
        arrowcolor=PASTEL["orange"], opacity=0.9),)
    fig.add_trace(go.Scatter(
        x=[cx], y=[cy], mode="markers", showlegend=False,
        marker=dict(size=12, color=PASTEL["orange"],
                    symbol=("diamond-open" if outside else "star"),
                    line=dict(width=1.2, color=INK)),
        hovertemplate=f"{nm} now<br>CO2 r=%{{x:.2f}}<br>VOC r=%{{y:.2f}}"
                      f"{' (out)' if outside else ''}<extra></extra>",
    ))
    return fig


def make_node_regime_scatter(dfa: pd.DataFrame, node_id: str, labels: dict,
                             latest: dict = None) -> go.Figure:
    """Uncached base + overlay in one call (scripts / tests)."""
    fig, meta = make_node_regime_base(dfa, node_id, labels)
    return overlay_node_current(fig, meta, latest.get(node_id) if latest else None)


def make_timeseries(dfn: pd.DataFrame) -> go.Figure:
    keys = TS_KEYS
    fig = make_subplots(rows=1, cols=len(keys),
                        subplot_titles=[f"{METRICS[k][0]} ({METRICS[k][1]})"
                                        for k in keys])
    for i, key in enumerate(keys, start=1):
        color = METRICS[key][2]
        is_target = key in TARGET_KEYS
        fig.add_trace(go.Scatter(
            x=dfn["recv_time"], y=dfn[key], mode="lines+markers",
            line=dict(color=color, width=3 if is_target else 2),
            marker=dict(size=5 if is_target else 4),
            showlegend=False), row=1, col=i)
        fig.update_yaxes(gridcolor=GRID, tickfont={"color": INK_DIM}, row=1, col=i)
        fig.update_xaxes(gridcolor=GRID, row=1, col=i)
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=40),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font={"color": INK})
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=8, color=INK_DIM))
    fig.update_annotations(font_size=11, font_color=INK_DIM)
    # emphasize CO2 & VOC subplot titles (ML targets)
    anns = fig.layout.annotations
    for i, key in enumerate(keys):
        if key in TARGET_KEYS and i < len(anns):
            anns[i].font.color = emph_line(key)
    return fig


# ========================================================
#  Cached figure layer (Phase 1b)
#  Keys come from data_version(): the 28-day statistics rebuild once per 5-min
#  bucket, live figures only when their node has a newer row.
#  st.cache_resource, not cache_data: a cache_data hit unpickles the figure,
#  which re-runs plotly's validation (25 ms per radar, 280 ms for section 2 on
#  the board -- as slow as building it). cache_resource hands back the same
#  object, so a hit is free; st.plotly_chart only reads it, and the overlays
#  deep-copy before adding their live markers. max_entries bounds memory.
# ========================================================
@st.cache_resource(ttl=300, max_entries=4, show_spinner=False)
def stats_figures(bucket: str) -> dict:
    """Section 2: five figures + the regime base/meta, built from one load."""
    dfa = load_all_for_stats(bucket)
    if dfa.empty:
        return {}
    labels_ = load_node_labels()
    # Phase 5: correlation heatmap and the regime scatters moved to page 2 (H);
    # page 1 keeps "now": boxplots + CO2 / VOC means by node.
    return {"box": make_boxplots(dfa),
            "co2_bar": make_target_by_node(dfa, labels_, "co2"),
            "voc_bar": make_target_by_node(dfa, labels_, "voc")}


@st.cache_resource(ttl=300, max_entries=16, show_spinner=False)
def node_regime_figure(bucket: str, node_id: str):
    """Section 3 left: (base figure, meta) for one node."""
    return make_node_regime_base(load_all_for_stats(bucket), node_id, load_node_labels())


@st.cache_resource(ttl=300, max_entries=32, show_spinner=False)
def radar_figure(node_id: str, stamp: str, _vals: dict) -> go.Figure:
    """Section 1: one radar, keyed on the node's newest recv_time."""
    return make_node_radar(_vals, node_id)


@st.cache_resource(ttl=300, max_entries=32, show_spinner=False)
def timeseries_figure(node_id: str, stamp: str, _dfn: pd.DataFrame) -> go.Figure:
    """Section 3: last 60 rows of one node, keyed on its newest recv_time."""
    return make_timeseries(_dfn)


def header(text, color):
    st.markdown(f"<h3 style='color:{color};margin:14px 0 6px;'>{text}</h3>",
                unsafe_allow_html=True)
