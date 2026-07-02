"""
Multinode Environmental Sensing Monitor (display only)  -- native/systemd track, pure Python
- source : SQLite (sensor_data.db) written by hub.py -- read only
- split  : collect (hub.py) <-> display (this file). Same DB file.
- labels : nodes.json (optional; falls back to node ID)
- theme  : dark background + seaborn pastel (.streamlit/config.toml)

[Use of this file -- native (terminal / systemd)]
  - pure streamlit -> no Arduino Q dependency. Portable to Pi / PC / VM.
  - pairs with hub.py (collector). Register both as systemd services for 24/7 run.
  - run: uv run streamlit run dashboard.py --server.address 0.0.0.0 --server.headless true

[App Lab uses main.py instead] (combined collect+display, Brick import).

[Screen sections]
  1) node card grid (auto layout) -- 4 sensors as 2x2 half gauges
  2) overall stats (5-min cache) -- per-variable boxplots | correlation heatmap
  3) time series -- pick a node -> 4 variables in a row
  4) recent 5 rows
  5) data export -- full CSV / date-range CSV
"""
import json, os, re, sqlite3
from contextlib import closing
from datetime import datetime, date, time, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---- Streamlit import: plain streamlit (no Arduino Q dependency) ----
#   native/systemd only -> use the normal streamlit package
#   (no App Lab Brick import -> portable to any Linux/PC)
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---- Config ----
DB         = "sensor_data.db"
NODES_PATH = "nodes.json"
ROW_LIMIT  = 5000          # recent rows to show
REFRESH_MS = 10_000        # auto-refresh every 10s
MAX_COLS   = 4             # max grid columns (2 rows x 4 = 8 nodes)

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
NODE_PALETTE = ["#FF5CA8", "#8B7CFF", "#00E5B0", "#FFB300", "#4DD2FF", "#C4FF4D"]
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
@st.cache_data(ttl=5)
def load_df(limit: int = ROW_LIMIT) -> pd.DataFrame:
    """Recent rows from SQLite -> KST time. SEN55 stores values directly (no scaling)."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, node, "
           "pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, "
           "co2, scd_temp, scd_hum "
           "FROM readings ORDER BY id DESC LIMIT ?")
    with closing(sqlite3.connect(DB)) as con:
        df = pd.read_sql_query(sql, con, params=(limit,))
    return df.iloc[::-1].reset_index(drop=True) if not df.empty else df


@st.cache_data(ttl=300)               # stats cached for 5 min
def load_all_for_stats() -> pd.DataFrame:
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT node, pm1p0, pm2p5, pm4p0, pm10p0, sen_temp, sen_hum, voc, nox, "
           "co2, scd_temp, scd_hum "
           "FROM readings")
    with closing(sqlite3.connect(DB)) as con:
        return pd.read_sql_query(sql, con)


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
    with closing(sqlite3.connect(DB)) as con:
        return pd.read_sql_query(sql, con, params=(start_utc, end_utc))


def get_time_bounds():
    """Min/max time in DB (KST) -- defaults for the range picker."""
    if not os.path.isfile(DB):
        return None, None
    sql = ("SELECT MIN(datetime(ts,'+9 hours')), MAX(datetime(ts,'+9 hours')) "
           "FROM readings")
    with closing(sqlite3.connect(DB)) as con:
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


def node_card(node_id: str, vals: dict, labels: dict):
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;font-weight:700;color:{INK};"
            f"font-size:14px;margin-bottom:2px;'>{label_of(node_id, labels)}</div>",
            unsafe_allow_html=True)
        # one radar per node (6 vars normalized by gauge range)
        st.plotly_chart(make_node_radar(vals, node_id),
                        use_container_width=True, key=f"radar_{node_id}")


def make_boxplots(dfa: pd.DataFrame) -> go.Figure:
    """Per-variable boxplots (PM1.0/PM4.0 excluded). VOC last, with emphasis."""
    keys = STATS_KEYS
    fig = make_subplots(rows=1, cols=len(keys),
                        subplot_titles=[METRICS[k][0] for k in keys])
    for i, key in enumerate(keys, start=1):
        _, unit, color, _, _ = METRICS[key]
        is_target = key in TARGET_KEYS
        fig.add_trace(go.Box(y=dfa[key], name=METRICS[key][0],
                             marker_color=color, boxpoints="outliers",
                             line={"color": color},
                             fillcolor=(emph_line(key) if is_target else "rgba(255,255,255,0.05)"),
                             showlegend=False), row=1, col=i)
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


def make_regime_scatter(dfa: pd.DataFrame, labels: dict, latest: dict = None) -> go.Figure:
    """CO2-VOC RELATIVE regime scatter (RobustScaling). Each point = one reading.
    RobustScaling: (v - median) / IQR  -> robust to outliers & skew, stable origin.
    Purpose = RELATIVE regime (where a point sits within the distribution), good for
    flexible regime-switching detection. NOTE: normalization removes ABSOLUTE level
    (e.g. 500 vs 900ppm both map near 0); absolute level is shown by the CO2 barplot.
    Density gradation: denser quadrant = deeper tint. Foundation for future GMM.
    Quadrant split at median(=0): low-low=Clean / lowCO2-highVOC=Matter>Human /
    highCO2-lowVOC=Human>Matter / high-high=Human~=Matter."""
    d = dfa[["co2", "voc", "node"]].dropna()
    if len(d) < 3:
        fig = go.Figure()
        fig.add_annotation(text="Not enough data yet for regime scatter",
                           x=0.5, y=0.5, showarrow=False, font={"color": INK_DIM})
        fig.update_layout(height=420, paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font={"color": INK})
        return fig

    # RobustScaling: (v - median) / IQR per axis (robust to outliers/skew)
    def robust(s):
        med = s.median()
        iqr = s.quantile(0.75) - s.quantile(0.25)
        return (s - med) / iqr if iqr and iqr > 0 else (s - med) * 0.0
    zco2 = robust(d["co2"]); zvoc = robust(d["voc"])

    # 2D density (histogram) as background -> denser quadrant = deeper tint
    fig = go.Figure()
    # (density trace added after range is known, so clipping is consistent)
    # normalization params (reuse for mapping current values to same robust-space)
    co2_med = d["co2"].median(); co2_iqr = d["co2"].quantile(0.75) - d["co2"].quantile(0.25)
    voc_med = d["voc"].median(); voc_iqr = d["voc"].quantile(0.75) - d["voc"].quantile(0.25)
    def rc(v, med, iqr): return (v - med) / iqr if iqr and iqr > 0 else 0.0

    # axis range from PERCENTILES (not max) so a single outlier can't blow up scale
    def prange(s):
        lo, hi = s.quantile(0.02), s.quantile(0.98)
        return max(abs(lo), abs(hi))
    amax = float(max(prange(zco2), prange(zvoc)))
    amax = (amax * 1.15) if amax > 0 else 1.0
    amax = min(max(amax, 1.5), 3.0)       # 1.5~3.0 (max 3 grid at dtick=1)

    def clip(v):                          # clamp into [-amax, amax] for display
        return max(-amax, min(amax, v))

    # density background (clipped to range so out-of-range points don't distort)
    fig.add_trace(go.Histogram2d(
        x=zco2.clip(-amax, amax), y=zvoc.clip(-amax, amax),
        nbinsx=24, nbinsy=24,
        colorscale=[[0.0, "rgba(0,0,0,0)"], [0.15, "rgba(120,170,255,0.10)"],
                    [0.5, "rgba(120,170,255,0.28)"], [1.0, "rgba(90,140,255,0.55)"]],
        showscale=False, zsmooth="best", hoverinfo="skip",
    ))

    # node colors: shared vivid identity palette (see NODE_PALETTE)
    node_list = sorted(d["node"].unique())
    # past points: small & faint (distribution backdrop). Clip to range edges.
    for i, nd in enumerate(node_list):
        m = d["node"] == nd
        fig.add_trace(go.Scatter(
            x=zco2[m].clip(-amax, amax), y=zvoc[m].clip(-amax, amax), mode="markers",
            name=label_of(nd, labels), legendgroup=nd,
            marker=dict(size=5, color=node_color(nd),
                        line=dict(width=0.3, color="rgba(0,0,0,0.3)"), opacity=0.35),
        ))
    # current position: vector from origin + emphasized marker (per node)
    if latest:
        for i, nd in enumerate(node_list):
            cur = latest.get(nd)
            if not cur:
                continue
            cv, vv = cur.get("co2"), cur.get("voc")
            if cv is None or vv is None or pd.isna(cv) or pd.isna(vv):
                continue
            rx, ry = rc(cv, co2_med, co2_iqr), rc(vv, voc_med, voc_iqr)
            cx, cy = clip(rx), clip(ry)          # clip into view; flag if outside
            outside = (cx != rx) or (cy != ry)
            col = node_color(nd)
            # vector: origin -> current (arrow)
            fig.add_annotation(x=cx, y=cy, ax=0, ay=0,
                               xref="x", yref="y", axref="x", ayref="y",
                               showarrow=True, arrowhead=2, arrowsize=1.2,
                               arrowwidth=2, arrowcolor=col, opacity=0.9)
            # emphasized current marker (modest size). Diamond if clipped (out of range).
            fig.add_trace(go.Scatter(
                x=[cx], y=[cy], mode="markers",
                name=f"{label_of(nd, labels)} (now)", legendgroup=nd,
                showlegend=False,
                marker=dict(size=11, color=col,
                            symbol=("diamond-open" if outside else "star"),
                            line=dict(width=1.2, color=INK)),
                hovertemplate=(f"{label_of(nd, labels)} now<br>CO2 r=%{{x:.2f}}"
                               f"<br>VOC r=%{{y:.2f}}"
                               f"{' (범위밖)' if outside else ''}<extra></extra>"),
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
        title=dict(text="CO\u2082-VOC \uc0c1\ub300 \ub808\uc9d0 (RobustScaling)  \u2014  \u2605 \ud604\uc7ac(\uc6d0\uc810\u2192\ubca1\ud130), \u25c7=\ubc94\uc704\ubc16, \ud750\ub9b0 \uc810=\uacfc\uac70",
                   x=0.5, xanchor="center", font=dict(size=12, color=INK)),
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
        legend=dict(font={"size": 10, "color": INK_DIM}, orientation="h",
                    yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def make_node_regime_scatter(dfa: pd.DataFrame, node_id: str, labels: dict,
                             latest: dict = None) -> go.Figure:
    """Per-node regime scatter using THAT NODE's own median/IQR (within-node
    RobustScaling). Answers 'is this room different from its OWN baseline?'.
    Complements the pooled scatter (which compares nodes). IQR-small nodes can
    look jumpy -- that's expected (each node scaled to itself)."""
    d = dfa[dfa["node"] == node_id][["co2", "voc"]].dropna()
    nm = label_of(node_id, labels)
    if len(d) < 3:
        fig = go.Figure()
        fig.add_annotation(text=f"{nm}: not enough data yet",
                           x=0.5, y=0.5, showarrow=False, font={"color": INK_DIM})
        fig.update_layout(height=360, paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font={"color": INK})
        return fig

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
    def clip(v): return max(-amax, min(amax, v))

    # density backdrop (this node only)
    fig.add_trace(go.Histogram2d(
        x=zco2.clip(-amax, amax), y=zvoc.clip(-amax, amax), nbinsx=20, nbinsy=20,
        colorscale=[[0.0, "rgba(0,0,0,0)"], [0.2, "rgba(120,170,255,0.12)"],
                    [0.6, "rgba(120,170,255,0.30)"], [1.0, "rgba(90,140,255,0.55)"]],
        showscale=False, zsmooth="best", hoverinfo="skip",
    ))
    # past points
    fig.add_trace(go.Scatter(
        x=zco2.clip(-amax, amax), y=zvoc.clip(-amax, amax), mode="markers",
        marker=dict(size=5, color=node_color(node_id),
                    line=dict(width=0.3, color="rgba(0,0,0,0.3)"), opacity=0.4),
        showlegend=False, hoverinfo="skip",
    ))
    # current position vector + star (this node's own scale)
    def rc(v, med, iqr): return (v - med) / iqr if iqr and iqr > 0 else 0.0
    if latest and latest.get(node_id):
        cur = latest[node_id]
        cv, vv = cur.get("co2"), cur.get("voc")
        if cv is not None and vv is not None and not pd.isna(cv) and not pd.isna(vv):
            rx, ry = rc(cv, co2_med, co2_iqr), rc(vv, voc_med, voc_iqr)
            cx, cy = clip(rx), clip(ry)
            outside = (cx != rx) or (cy != ry)
            fig.add_annotation(x=cx, y=cy, ax=0, ay=0, xref="x", yref="y",
                               axref="x", ayref="y", showarrow=True, arrowhead=2,
                               arrowsize=1.2, arrowwidth=2,
                               arrowcolor=PASTEL["orange"], opacity=0.9)
            fig.add_trace(go.Scatter(
                x=[cx], y=[cy], mode="markers", showlegend=False,
                marker=dict(size=12, color=PASTEL["orange"],
                            symbol=("diamond-open" if outside else "star"),
                            line=dict(width=1.2, color=INK)),
                hovertemplate=f"{nm} now<br>CO2 r=%{{x:.2f}}<br>VOC r=%{{y:.2f}}"
                              f"{' (out)' if outside else ''}<extra></extra>",
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
    return fig


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
#  Screen
# ========================================================
st.set_page_config(page_title="Sensing Monitor", page_icon="*", layout="wide")
st_autorefresh(interval=REFRESH_MS, key="auto")

# extra dark-theme CSS (works with config.toml; also alone)
st.markdown(f"""
<style>
  .stApp {{ background:{BG}; color:{INK}; }}
  section[data-testid="stSidebar"] {{ background:{PANEL_BG}; }}
  [data-testid="stMetricValue"], .stMarkdown, p, span, label {{ color:{INK}; }}
  div[data-testid="stVerticalBlockBorderWrapper"] {{
     background:{PANEL_BG}; border-radius:12px; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"<h1 style='color:{INK};margin-bottom:2px;'>"
            "Multinode Environmental Sensing Monitor</h1>", unsafe_allow_html=True)

df = load_df()
if df.empty:
    st.info("No data yet. Check that the hub (hub_cloud.py for HiveMQ, "
            "or hub.py for local mosquitto) is running, and that nodes "
            "are publishing. First data appears at the next publish "
            "interval (e.g. every 5 min).")
    st.stop()

labels = load_node_labels()


def _node_sort_key(node_id: str):
    """Sort by integer found in the label (e.g. CLASS_1 -> 1, CLASS_10 -> 10).
    Nodes whose label has a number come first in numeric order; the rest fall
    back to case-insensitive label text. Keeps mixed labels sensible."""
    lbl = label_of(node_id, labels)
    m = re.search(r"\d+", lbl)
    if m:
        return (0, int(m.group()), lbl.lower())
    return (1, 0, lbl.lower())


nodes = sorted(df["node"].dropna().unique(), key=_node_sort_key)
NODE_COLOR.update({n: NODE_PALETTE[i % len(NODE_PALETTE)] for i, n in enumerate(nodes)})
latest = {n: df[df["node"] == n].iloc[-1].to_dict() for n in nodes}

st.caption(f"{len(nodes)} nodes: {', '.join(label_of(n, labels) for n in nodes)}"
           f"   |   {len(df):,} rows  -  last seen {df['recv_time'].max()} (KST)")


def header(text, color):
    st.markdown(f"<h3 style='color:{color};margin:14px 0 6px;'>{text}</h3>",
                unsafe_allow_html=True)


# ---- Section 1: node card grid ----
header("1) Live status by node", H_OVERVIEW)
ncols = min(len(nodes), MAX_COLS)
for i in range(0, len(nodes), ncols):
    row_nodes = nodes[i:i + ncols]
    cols = st.columns(ncols)
    for col, node in zip(cols, row_nodes):
        with col:
            node_card(node, latest[node], labels)

# ---- Section 2: overall stats (5-min) ----
header("2) Overall stats (5-min)", H_STATS)
dfa = load_all_for_stats()
if not dfa.empty:
    # row 1: boxplot | correlation  (1:1)
    r1c1, r1c2 = st.columns(2)
    r1c1.plotly_chart(make_boxplots(dfa), use_container_width=True, key="box")
    r1c2.plotly_chart(make_corr(dfa), use_container_width=True, key="corr")
    # row 2: CO2+VOC by node (stacked, left) | CO2-VOC regime scatter (right)  (1:2)
    r2c1, r2c2 = st.columns([1, 2])
    with r2c1:
        st.plotly_chart(make_target_by_node(dfa, labels, "co2"),
                        use_container_width=True, key="co2_bar")
        st.plotly_chart(make_target_by_node(dfa, labels, "voc"),
                        use_container_width=True, key="voc_bar")
    r2c2.plotly_chart(make_regime_scatter(dfa, labels, latest),
                      use_container_width=True, key="regime")

# ---- Section 3: time series + per-node regime ----
header("3) Time series by node", H_TS)
sel = st.selectbox("Select node", nodes,
                   format_func=lambda n: label_of(n, labels), key="ts_node")
dfn = df[df["node"] == sel].tail(60)
st.plotly_chart(make_timeseries(dfn), use_container_width=True, key="ts")
# per-node regime scatter (within-node RobustScaling = this room's own baseline)
st.plotly_chart(make_node_regime_scatter(dfa, sel, labels, latest),
                use_container_width=True, key="node_regime")
st.caption("위 산점도는 선택한 노드의 '자기 기준'(노드별 RobustScaling)입니다. "
           "전체 비교는 Section 2의 pooled 산점도를 보세요. "
           "(자기 기준 = 그 교실 평소 대비 지금 상태)")

# ---- Section 4: recent rows ----
header("4) Recent records", H_TS)
recent = df[df["node"] == sel][["recv_time"] + SENSOR_KEYS].tail(5).iloc[::-1]
fmt = {k: ("{:.0f}" if k in ("voc", "nox", "co2") else "{:.1f}")
       for k in SENSOR_KEYS}
st.dataframe(recent.style.format(fmt), use_container_width=True, hide_index=True)

# ---- Section 5: data export ----
header("5) Data export (CSV)", H_EXPORT)

# (5-1) full download -- quick backup
csv_all = load_df(limit=10_000_000)        # effectively all
st.download_button(
    "Download all data (CSV)",
    data=csv_all.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"sensor_all_{df['recv_time'].max()[:10]}.csv",
    mime="text/csv",
)

# (5-2) date-range download -- date picker + hour dropdown
st.markdown(f"<div style='color:{INK_DIM};margin:10px 0 4px;'>"
            "Export by date range (KST)</div>", unsafe_allow_html=True)

lo, hi = get_time_bounds()
if lo and hi:
    d1, d2, d3, d4 = st.columns(4)
    start_d = d1.date_input("Start date", value=lo.date(),
                            min_value=lo.date(), max_value=hi.date(), key="sd")
    start_h = d2.selectbox("Start hour", list(range(24)), index=0,
                           format_func=lambda h: f"{h:02d}:00", key="sh")
    end_d   = d3.date_input("End date", value=hi.date(),
                            min_value=lo.date(), max_value=hi.date(), key="ed")
    end_h   = d4.selectbox("End hour", list(range(24)), index=23,
                           format_func=lambda h: f"{h:02d}:00", key="eh")

    start_dt = datetime.combine(start_d, time(start_h, 0, 0))
    end_dt   = datetime.combine(end_d,   time(end_h, 59, 59))

    if start_dt > end_dt:
        st.warning("Start is later than end. Check the range.")
    else:
        rng = query_range(start_dt, end_dt)
        n_rows = len(rng)
        st.caption(f"Range: {start_dt:%Y-%m-%d %H:00} ~ {end_dt:%Y-%m-%d %H:00}"
                   f"   -   {n_rows:,} rows")
        st.download_button(
            f"Download range CSV ({n_rows:,} rows)",
            data=rng.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"sensor_{start_dt:%Y%m%d_%H}-{end_dt:%Y%m%d_%H}.csv",
            mime="text/csv",
            disabled=(n_rows == 0),
            key="dl_range",
        )
        if n_rows == 0:
            st.info("No data in the selected range.")
else:
    st.caption("Range export becomes available once data accumulates.")


# ---- Section 6: data reset (clear table, with auto-backup) ----
header("6) Data reset", H_EXPORT)
with st.expander("Clear all collected data (DANGER)", expanded=False):
    st.warning(
        "This empties the 'readings' table. hub.py keeps running and will "
        "store new data into the now-empty table. A CSV backup is saved "
        "automatically before deletion."
    )
    try:
        with closing(sqlite3.connect(DB)) as con:
            total_rows = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    except Exception:
        total_rows = 0
    st.caption(f"Current rows: {total_rows:,}")

    confirm = st.checkbox("I understand this cannot be undone", key="reset_confirm")

    if st.button("Backup + Clear table", type="primary",
                 disabled=(not confirm or total_rows == 0), key="reset_btn"):
        try:
            # 1) auto-backup: save full CSV next to the DB
            backup_df = load_df(limit=10_000_000)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(os.path.dirname(os.path.abspath(DB)) or ".",
                                       f"sensor_backup_{stamp}.csv")
            backup_df.to_csv(backup_path, index=False, encoding="utf-8-sig")

            # 2) clear table (hub.py untouched; it keeps writing new rows)
            with closing(sqlite3.connect(DB)) as con:
                con.execute("DELETE FROM readings")
                con.commit()
            # VACUUM is optional (reclaims file size). Skip silently if the
            # DB is briefly locked by hub.py writing.
            try:
                with closing(sqlite3.connect(DB, timeout=2)) as con:
                    con.execute("VACUUM")
            except Exception:
                pass
            load_df.clear()                    # drop cached data so UI refreshes

            st.success(f"Cleared {total_rows:,} rows. Backup saved: {backup_path}")
            # also offer the backup as a browser download
            st.download_button(
                "Download the backup CSV",
                data=backup_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"sensor_backup_{stamp}.csv",
                mime="text/csv",
                key="dl_backup",
            )
            st.info("Refresh (or wait for auto-refresh) to see the empty dashboard.")
        except Exception as e:
            st.error(f"Reset failed: {e}")
