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
  3) time series -- pick a node -> 6 variables in a row
     + per-node regime | vision occupancy crosshair map (2-col)
  4) recent 5 rows
  5) data export -- full CSV / date-range CSV (built on demand)
  6) data reset (backup + clear)
Refresh (Phase 1b): sections are st.fragment blocks -- 1/3/4 every 60 s,
2 every 5 min, 5 only on its buttons. No full-page autorefresh.
"""
import copy, json, os, re, sqlite3, sys
from contextlib import closing
from datetime import datetime, date, time, timedelta
from time import perf_counter

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---- Streamlit import: plain streamlit (no Arduino Q dependency) ----
#   native/systemd only -> use the normal streamlit package
#   (no App Lab Brick import -> portable to any Linux/PC)
import streamlit as st
import streamlit.components.v1 as components

from aq import ui_common
from aq.ui_common import (  # noqa: F401  (page-1 uses most of these; probe reads the rest)
    DB,
    NODES_PATH,
    ROW_LIMIT,
    REFRESH_LIVE,
    REFRESH_STATS,
    MAX_COLS,
    STATS_DAYS,
    BOX_MAX_OUTLIERS,
    SCATTER_MAX_POINTS,
    DENSITY_BINS,
    DB_TIMEOUT_S,
    _ro,
    _perf,
    BG,
    PANEL_BG,
    INK,
    INK_DIM,
    GRID,
    PASTEL,
    H_OVERVIEW,
    H_STATS,
    H_TS,
    H_EXPORT,
    NODE_PALETTE,
    NODE_COLOR,
    node_color,
    node_fill,
    METRICS,
    ALL_KEYS,
    GAUGE_KEYS,
    STATS_KEYS,
    TS_KEYS,
    SENSOR_KEYS,
    TARGET_KEYS,
    VOC_EMPH_BG,
    VOC_EMPH_LINE,
    CO2_EMPH_BG,
    CO2_EMPH_LINE,
    emph_line,
    emph_bg,
    grade_color,
    _query_recent,
    data_version,
    load_df,
    query_all,
    load_all_for_stats,
    query_range,
    get_time_bounds,
    load_node_labels,
    label_of,
    VIS_ACC,
    VIS_GRID,
    _occ_table_exists,
    load_occ_latest,
    load_occ_hist,
    vision_node_for,
    load_merged_analysis,
    render_vision_panel,
    normalize,
    make_node_radar,
    node_card,
    box_stats,
    make_boxplots,
    make_corr,
    make_target_by_node,
    density_heatmap,
    make_regime_base,
    overlay_current,
    make_regime_scatter,
    make_node_regime_base,
    overlay_node_current,
    make_node_regime_scatter,
    make_timeseries,
    stats_figures,
    node_regime_figure,
    radar_figure,
    timeseries_figure,
    header,
)

ui_common.reset_perf()


# ========================================================
#  Screen
# ========================================================
st.set_page_config(page_title="Sensing Monitor", page_icon="*", layout="wide")

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

max_id, bucket = data_version()
df = load_df(max_id)
if df.empty:
    st.info("No data yet. Check that the hub (hub.py) is running "
            "and that nodes "
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


def snapshot():
    """What the live sections need: (max_id, bucket, df, nodes, latest).
    Called at the start of every fragment run; everything behind it is cached
    on data_version(), so a run without new rows costs two PK lookups."""
    max_id, bucket = data_version()
    df = load_df(max_id)
    nodes = sorted(df["node"].dropna().unique(), key=_node_sort_key)
    for i, n in enumerate(nodes):                       # colours stay stable per session
        NODE_COLOR.setdefault(n, NODE_PALETTE[i % len(NODE_PALETTE)])
    latest = {n: df[df["node"] == n].iloc[-1].to_dict() for n in nodes}
    return max_id, bucket, df, nodes, latest


# Phase 1b: each section is a st.fragment with its own timer, so a refresh
# re-runs only that block (no full-page rerun, no flicker on node selection).
# Section 5 has no timer -- its buttons rerun just that fragment. Section 6
# (reset) stays a plain block: its button triggers a full rerun, which is fine.

# ---- Section 1: node card grid ----
@st.fragment(run_every=REFRESH_LIVE)
def section_live_status():
    t = perf_counter()
    _, _, df, nodes, latest = snapshot()
    st.caption(f"{len(nodes)} nodes: {', '.join(label_of(n, labels) for n in nodes)}"
               f"   |   {len(df):,} rows  -  last seen {df['recv_time'].max()} (KST)")
    header("1) Live status by node", H_OVERVIEW)
    ncols = min(len(nodes), MAX_COLS)
    for i in range(0, len(nodes), ncols):
        row_nodes = nodes[i:i + ncols]
        cols = st.columns(ncols)
        for col, node in zip(cols, row_nodes):
            with col:
                node_card(node, latest[node], labels)
    _perf("sec1", t)


# ---- Section 2: overall stats (5-min) ----
@st.fragment(run_every=REFRESH_STATS)
def section_stats():
    t = perf_counter()
    _, bucket, _, _, latest = snapshot()
    header("2) Overall stats (5-min)", H_STATS)
    st.caption(f"Window: last {STATS_DAYS} days. Rebuilt once per 5-min bucket.")
    figs = stats_figures(bucket)
    if figs:
        # row 1: boxplot | correlation  (1:1)
        r1c1, r1c2 = st.columns(2)
        r1c1.plotly_chart(figs["box"], width="stretch", key="box")
        r1c2.plotly_chart(figs["corr"], width="stretch", key="corr")
        # row 2: CO2+VOC by node (stacked, left) | CO2-VOC regime scatter (right)  (1:2)
        r2c1, r2c2 = st.columns([1, 2])
        with r2c1:
            st.plotly_chart(figs["co2_bar"], width="stretch", key="co2_bar")
            st.plotly_chart(figs["voc_bar"], width="stretch", key="voc_bar")
        # live markers (★) go on a deep copy of the cached base every refresh
        r2c2.plotly_chart(overlay_current(figs["regime"], figs["regime_meta"], latest, labels),
                          width="stretch", key="regime")
    _perf("sec2", t)


# ---- Section 3: time series + per-node regime ; Section 4: recent rows ----
@st.fragment(run_every=REFRESH_LIVE)
def section_node_detail():
    t = perf_counter()
    _, bucket, df, nodes, latest = snapshot()
    header("3) Time series by node", H_TS)
    sel = st.selectbox("Select node", nodes,
                       format_func=lambda n: label_of(n, labels), key="ts_node")
    dfn = df[df["node"] == sel].tail(60)
    st.plotly_chart(timeseries_figure(sel, str(latest[sel].get("recv_time")), dfn),
                    width="stretch", key="ts")
    # per-node regime scatter | vision occupancy crosshair map  (2 columns)
    r3a, r3b = st.columns(2)
    base, meta = node_regime_figure(bucket, sel)
    r3a.plotly_chart(overlay_node_current(base, meta, latest.get(sel)),
                     width="stretch", key="node_regime")
    with r3b:
        render_vision_panel(sel, labels)
    st.caption("좌: 선택 노드의 '자기 기준'(노드별 RobustScaling) — 전체 비교는 Section 2의 "
               "pooled 산점도. 우: 같은 교실(라벨) 비전 노드의 재실 탐지 — 깜빡이는 조준선은 "
               "최근 버킷 '최대 인원 시점'의 위치(c), 수치는 5분 버킷 통계(평균/중앙값/최대). "
               "영상은 전송·저장되지 않습니다(좌표만 수집).")

    header("4) Recent records", H_TS)
    recent = df[df["node"] == sel][["recv_time"] + SENSOR_KEYS].tail(5).iloc[::-1]
    fmt = {k: ("{:.0f}" if k in ("voc", "nox", "co2") else "{:.1f}")
           for k in SENSOR_KEYS}
    st.dataframe(recent.style.format(fmt), width="stretch", hide_index=True)
    _perf("sec3+4", t)


# ---- Section 5: data export (on demand) ----
# Phase 1b: nothing is queried or serialised until asked. Each export has a
# "Prepare" button that runs the query + to_csv once and parks the bytes in
# st.session_state; the download button appears after that. Before, all four
# CSVs (two of them the full table) were rebuilt on every 10 s refresh.
EXPORT_ON_DEMAND = True


def _csv_bytes(d: pd.DataFrame) -> bytes:
    return d.to_csv(index=False).encode("utf-8-sig")


def export_slot(key: str, prepare_label: str, build, label_fn, file_fn, help=None,
                empty_msg: str = None):
    """One on-demand export. `build()` -> DataFrame runs only when the Prepare
    button is pressed; the result (bytes + meta) stays in session_state so the
    download button survives reruns without re-querying."""
    slot = f"csv_{key}"
    if st.button(prepare_label, key=f"prep_{key}"):
        with st.spinner("Preparing CSV..."):
            d = build()
        meta = {"rows": len(d)}
        if not d.empty:
            meta.update({"rooms": d["room"].nunique() if "room" in d else None,
                         "nodes": d["node"].nunique() if "node" in d else None,
                         "last": str(d.iloc[-1, 0])[:10] if len(d.columns) else ""})
        st.session_state[slot] = (_csv_bytes(d) if not d.empty else b"", meta)
    if slot in st.session_state:
        data, meta = st.session_state[slot]
        if meta["rows"] == 0:
            st.caption(empty_msg or "No rows.")
        else:
            st.download_button(label_fn(meta), data=data, file_name=file_fn(meta),
                               mime="text/csv", key=f"dl_{key}", help=help)


def load_occ_all() -> pd.DataFrame:
    """(5-2b) vision occupancy raw -- full occupancy schema as stored (the merged
    export drops cents/w and low-n rows; this keeps everything)."""
    if not _occ_table_exists():
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time_kst, ts AS ts_utc, "
           "node, occ AS occ_mean, occ_med, occ_max, occ_last, cents, w, n "
           "FROM occupancy ORDER BY id")
    with closing(_ro()) as con:
        d = pd.read_sql_query(sql, con)
    if not d.empty:
        d.insert(3, "room", d["node"].map(labels).fillna(""))
    return d


@st.fragment
def section_export():
    t = perf_counter()
    header("5) Data export (CSV)", H_EXPORT)

    # (5-1) full download -- quick backup
    export_slot("all", "Prepare all-data CSV", query_all,
                lambda m: "Download all data (CSV)",
                lambda m: f"sensor_all_{m['last']}.csv")

    # (5-2) merged analysis download -- env x occupancy, join on (bucket, room)
    #        analysis-ready: one row = one 5-min bucket of one room, CO2 next to occ.
    if _occ_table_exists():
        export_slot("merged", "Prepare merged env x occupancy CSV", load_merged_analysis,
                    lambda m: f"Download merged env x occupancy CSV ({m['rows']:,} rows / "
                              f"{m['rooms']} rooms)",
                    lambda m: f"env_occ_merged_{m['last']}.csv",
                    help="재실 x CO2 상관 분석용. (버킷시각, 교실) 정확 조인, "
                         "occ 버킷 n>=25 품질 필터 적용. 상관은 Spearman 권장(포화형 계수 대비).",
                    empty_msg="Merged export: no matching (bucket, room) rows yet -- "
                              "needs both env and vision nodes publishing with NTP time.")
        # (5-2b) vision occupancy raw
        export_slot("occ_raw", "Prepare vision occupancy CSV", load_occ_all,
                    lambda m: f"Download vision occupancy CSV ({m['rows']:,} rows / "
                              f"{m['nodes']} nodes)",
                    lambda m: f"occupancy_all_{m['last']}.csv",
                    help="occupancy 테이블 원본 전체. cents=최대 인원 시점 centroid JSON(w 좌표계), "
                         "n=버킷 내 유효 샘플 수(정상 ~30, 낮으면 저품질 버킷). "
                         "병합 CSV와 달리 품질 필터 없이 전 행 포함 — 결측/장애 구간 분석에도 사용.",
                    empty_msg="No occupancy rows yet.")

    # (5-3) date-range download -- date picker + hour dropdown, queried on "Query range"
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
            st.caption(f"Range: {start_dt:%Y-%m-%d %H:00} ~ {end_dt:%Y-%m-%d %H:00}")
            export_slot("range", "Query range", lambda: query_range(start_dt, end_dt),
                        lambda m: f"Download range CSV ({m['rows']:,} rows)",
                        lambda m: f"sensor_{start_dt:%Y%m%d_%H}-{end_dt:%Y%m%d_%H}.csv",
                        empty_msg="No data in the selected range.")
    else:
        st.caption("Range export becomes available once data accumulates.")
    _perf("sec5", t)


section_live_status()
section_stats()
section_node_detail()
section_export()

# ---- Section 6: data reset (clear table, with auto-backup) ----
header("6) Data reset", H_EXPORT)
with st.expander("Clear all collected data (DANGER)", expanded=False):
    st.warning(
        "This empties the 'readings' table. hub.py keeps running and will "
        "store new data into the now-empty table. A CSV backup is saved "
        "automatically before deletion."
    )
    try:
        with closing(_ro()) as con:
            total_rows = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    except Exception:
        total_rows = 0
    st.caption(f"Current rows: {total_rows:,}")

    confirm = st.checkbox("I understand this cannot be undone", key="reset_confirm")

    if st.button("Backup + Clear table", type="primary",
                 disabled=(not confirm or total_rows == 0), key="reset_btn"):
        try:
            # 1) auto-backup: save full CSV next to the DB
            backup_df = query_all()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(os.path.dirname(os.path.abspath(DB)) or ".",
                                       f"sensor_backup_{stamp}.csv")
            backup_df.to_csv(backup_path, index=False, encoding="utf-8-sig")

            # 2) clear table (hub.py untouched; it keeps writing new rows)
            with closing(sqlite3.connect(DB, timeout=DB_TIMEOUT_S)) as con:
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

_perf("full run")
