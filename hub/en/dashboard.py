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
import json, os, sqlite3
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

# ========================================================
#  [METRICS] sensor definitions -- edit here to add/replace/remove
#  format: key:(label, unit, color, gauge_min, gauge_max)
# ========================================================
METRICS = {
    "temp":  ("Temp",  "degC",  PASTEL["red"],    0,   50),
    "hum":   ("Hum",   "%",   PASTEL["blue"],   0,  100),
    "press": ("Press", "hPa", PASTEL["green"], 950, 1050),
    "gas":   ("Gas",   "kohm",  PASTEL["orange"], 0,  500),
}
SENSOR_KEYS = list(METRICS.keys())

# ---- Data loading ----
@st.cache_data(ttl=5)
def load_df(limit: int = ROW_LIMIT) -> pd.DataFrame:
    """Recent rows from SQLite -> KST time, gas Ohm->kOhm."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, node, "
           "temp, hum, press, gas/1000.0 AS gas "
           "FROM readings ORDER BY id DESC LIMIT ?")
    with closing(sqlite3.connect(DB)) as con:
        df = pd.read_sql_query(sql, con, params=(limit,))
    return df.iloc[::-1].reset_index(drop=True) if not df.empty else df


@st.cache_data(ttl=300)               # stats cached for 5 min
def load_all_for_stats() -> pd.DataFrame:
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = "SELECT node, temp, hum, press, gas/1000.0 AS gas FROM readings"
    with closing(sqlite3.connect(DB)) as con:
        return pd.read_sql_query(sql, con)


def query_range(start_kst: datetime, end_kst: datetime) -> pd.DataFrame:
    """For date-range export. DB stores UTC; subtract 9h from KST range."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    start_utc = (start_kst - timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    end_utc   = (end_kst   - timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time_kst, node, "
           "temp, hum, press, gas/1000.0 AS gas_kohm "
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


def half_gauge(key: str, value) -> go.Figure:
    """One sensor -> half gauge. Single color (range coloring later)."""
    label, unit, color, gmin, gmax = METRICS[key]
    val = gmin if (value is None or pd.isna(value)) else float(value)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        number={"suffix": f" {unit}", "font": {"size": 17, "color": INK}},
        gauge={
            "shape": "angular",
            "axis": {"range": [gmin, gmax], "tickwidth": 1,
                     "tickcolor": GRID, "tickfont": {"size": 8, "color": INK_DIM}},
            "bar": {"color": color, "thickness": 0.34},
            "bgcolor": "rgba(255,255,255,0.04)",
            "borderwidth": 0,
        },
    ))
    fig.update_layout(
        height=140, margin=dict(l=14, r=14, t=10, b=4),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": INK},
    )
    fig.add_annotation(text=label, x=0.5, y=-0.05, showarrow=False,
                       font={"size": 12, "color": INK_DIM})
    return fig


def node_card(node_id: str, vals: dict, labels: dict):
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;font-weight:700;color:{INK};"
            f"font-size:14px;margin-bottom:2px;'>{label_of(node_id, labels)}</div>",
            unsafe_allow_html=True)
        r1 = st.columns(2)
        r1[0].plotly_chart(half_gauge("temp", vals.get("temp")),
                           use_container_width=True, key=f"g_{node_id}_temp")
        r1[1].plotly_chart(half_gauge("hum", vals.get("hum")),
                           use_container_width=True, key=f"g_{node_id}_hum")
        r2 = st.columns(2)
        r2[0].plotly_chart(half_gauge("press", vals.get("press")),
                           use_container_width=True, key=f"g_{node_id}_press")
        r2[1].plotly_chart(half_gauge("gas", vals.get("gas")),
                           use_container_width=True, key=f"g_{node_id}_gas")


def make_boxplots(dfa: pd.DataFrame) -> go.Figure:
    """All nodes -- 4 boxplots (own y-axis). For spotting outliers."""
    fig = make_subplots(rows=1, cols=len(SENSOR_KEYS),
                        subplot_titles=[METRICS[k][0] for k in SENSOR_KEYS])
    for i, key in enumerate(SENSOR_KEYS, start=1):
        _, unit, color, _, _ = METRICS[key]
        fig.add_trace(go.Box(y=dfa[key], name=METRICS[key][0],
                             marker_color=color, boxpoints="outliers",
                             line={"color": color}, fillcolor="rgba(255,255,255,0.05)",
                             showlegend=False), row=1, col=i)
        fig.update_yaxes(title_text=unit, row=1, col=i,
                         title_font={"size": 10, "color": INK_DIM},
                         gridcolor=GRID, tickfont={"color": INK_DIM})
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font={"color": INK})
    fig.update_annotations(font_size=12, font_color=INK_DIM)
    return fig


def make_corr(dfa: pd.DataFrame) -> go.Figure:
    corr = dfa[SENSOR_KEYS].corr()
    labels_x = [METRICS[k][0] for k in SENSOR_KEYS]
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
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": INK})
    return fig


def make_timeseries(dfn: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=len(SENSOR_KEYS),
                        subplot_titles=[f"{METRICS[k][0]} ({METRICS[k][1]})"
                                        for k in SENSOR_KEYS])
    for i, key in enumerate(SENSOR_KEYS, start=1):
        color = METRICS[key][2]
        fig.add_trace(go.Scatter(
            x=dfn["recv_time"], y=dfn[key], mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=4),
            showlegend=False), row=1, col=i)
        fig.update_yaxes(gridcolor=GRID, tickfont={"color": INK_DIM}, row=1, col=i)
        fig.update_xaxes(gridcolor=GRID, row=1, col=i)
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=40),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font={"color": INK})
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=8, color=INK_DIM))
    fig.update_annotations(font_size=11, font_color=INK_DIM)
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
    st.info("No data yet. Check that hub.py and mosquitto are running, "
            "and that nodes are publishing.")
    st.stop()

nodes = sorted(df["node"].dropna().unique())
latest = {n: df[df["node"] == n].iloc[-1].to_dict() for n in nodes}
labels = load_node_labels()

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
    c1, c2 = st.columns([3, 2])
    c1.plotly_chart(make_boxplots(dfa), use_container_width=True, key="box")
    c2.plotly_chart(make_corr(dfa), use_container_width=True, key="corr")

# ---- Section 3: time series ----
header("3) Time series by node", H_TS)
sel = st.selectbox("Select node", nodes,
                   format_func=lambda n: label_of(n, labels), key="ts_node")
dfn = df[df["node"] == sel].tail(60)
st.plotly_chart(make_timeseries(dfn), use_container_width=True, key="ts")

# ---- Section 4: recent rows ----
header("4) Recent records", H_TS)
recent = df[df["node"] == sel][["recv_time"] + SENSOR_KEYS].tail(5).iloc[::-1]
fmt = {k: ("{:.1f}" if k in ("temp", "hum", "gas") else "{:.0f}")
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
