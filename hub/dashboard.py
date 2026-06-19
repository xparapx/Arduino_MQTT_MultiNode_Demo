"""
멀티노드 환경 센싱 모니터 (Streamlit)
============================================================
- 데이터원 : hub.py 가 쌓는 SQLite (sensor_data.db) — 읽기 전용
- 분리    : 수집(hub.py) ↔ 표시(이 파일). 같은 DB 파일 공유
- 노드명  : nodes.json (없으면 ID 그대로. 보드 이동 시 이 파일만 수정)

[실행 — 두 가지 방법]
  (A) App Lab  : Streamlit Brick 으로 실행 (run 버튼)
       └ import 한 줄만 아래 'App Lab' 주석대로 교체
  (B) 터미널   : uv run streamlit run dashboard.py \\
                   --server.address 0.0.0.0 --server.headless true

[화면 4구역]
  1) 노드 카드 그리드 (자동 정렬, 최대 2행×4열) — 4센서 2×2 반원 게이지
  2) 전체 통계 (5분 갱신) — 변수별 boxplot 4개 | 변수 상관 히트맵
  3) 시계열 — 노드 선택 → 4개 변수 1행 나란히
  4) 최근 5행 테이블 + 전체 CSV 다운로드
============================================================
"""
import json, os, sqlite3
from contextlib import closing

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Streamlit import (실행 방법에 따라 한 줄만) ──────────────
# (A) App Lab 에서 실행할 때 ↓ 주석 해제
# from arduino.app_bricks.streamlit_ui import st
# (B) 터미널(uv) 에서 실행할 때 ↓ (기본)
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ── 설정 ────────────────────────────────────────────────
DB         = "sensor_data.db"
NODES_PATH = "nodes.json"
ROW_LIMIT  = 5000          # 표시용 최근 행 수
REFRESH_MS = 10_000        # 10초 자동 새로고침
MAX_COLS   = 4             # 카드 그리드 최대 열 수 (2행×4열=8노드)

# ════════════════════════════════════════════════════════
#  [METRICS] 센서 정의 — 추가/교체/제거 시 여기만 수정
#  형식: key:(label, unit, color, gauge_min, gauge_max)
#    key       : hub.py SQLite 컬럼명 = 노드 JSON 키
#    gauge_min/max : 반원 게이지 눈금 범위 (정상범위 색분할은 ML 후 추가 예정)
# ════════════════════════════════════════════════════════
METRICS = {
    "temp":  ("Temp",  "°C",  "#d98a8a",    0,   50),
    "hum":   ("Hum",   "%",   "#9bb8d3",    0,  100),
    "press": ("Press", "hPa", "#a8c4a0",  950, 1050),
    "gas":   ("Gas",   "kΩ",  "#e0b87a",    0,  500),
}
SENSOR_KEYS = list(METRICS.keys())

# ── 데이터 로딩 ──────────────────────────────────────────
@st.cache_data(ttl=5)
def load_df(limit: int = ROW_LIMIT) -> pd.DataFrame:
    """SQLite 최근 limit 행 → KST 변환, gas Ω→kΩ."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT datetime(ts,'+9 hours') AS recv_time, node, "
           "temp, hum, press, gas/1000.0 AS gas "
           "FROM readings ORDER BY id DESC LIMIT ?")
    with closing(sqlite3.connect(DB)) as con:
        df = pd.read_sql_query(sql, con, params=(limit,))
    return df.iloc[::-1].reset_index(drop=True) if not df.empty else df


@st.cache_data(ttl=300)               # 통계는 5분 캐시
def load_all_for_stats() -> pd.DataFrame:
    """통계용 — 전체 데이터(시간 무관)."""
    if not os.path.isfile(DB):
        return pd.DataFrame()
    sql = ("SELECT node, temp, hum, press, gas/1000.0 AS gas FROM readings")
    with closing(sqlite3.connect(DB)) as con:
        return pd.read_sql_query(sql, con)


def load_node_labels() -> dict:
    if not os.path.isfile(NODES_PATH):
        return {}
    try:
        with open(NODES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.warning(f"nodes.json 읽기 오류: {e}")
        return {}


def label_of(node_id: str, labels: dict) -> str:
    return labels.get(node_id, node_id)


# ── 구역 1: 반원 게이지 ──────────────────────────────────
def half_gauge(key: str, value) -> go.Figure:
    """한 센서 → 반원 게이지(크로노그래프). 색분할 없음(단색)."""
    label, unit, color, gmin, gmax = METRICS[key]
    val = gmin if (value is None or pd.isna(value)) else float(value)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        number={"suffix": f" {unit}", "font": {"size": 18, "color": "#e6e8ec"}},
        title={"text": label, "font": {"size": 13, "color": "#cfd3da"}},
        gauge={
            "shape": "angular",
            "axis": {"range": [gmin, gmax], "tickwidth": 1,
                     "tickcolor": "#5f6f7e", "tickfont": {"size": 8}},
            "bar": {"color": color, "thickness": 0.32},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
        },
    ))
    fig.update_layout(
        height=150, margin=dict(l=14, r=14, t=30, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def node_card(node_id: str, vals: dict, labels: dict):
    """노드 1개 카드 = 2×2 반원 게이지."""
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;font-weight:700;color:#e6e8ec;"
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


# ── 구역 2: boxplot(4 서브플롯) + 상관 히트맵 ────────────
def make_boxplots(dfa: pd.DataFrame) -> go.Figure:
    """전체노드 합산 — 변수별 boxplot 4개(각자 y축). 이상치 판단용."""
    fig = make_subplots(rows=1, cols=len(SENSOR_KEYS),
                        subplot_titles=[METRICS[k][0] for k in SENSOR_KEYS])
    for i, key in enumerate(SENSOR_KEYS, start=1):
        _, unit, color, _, _ = METRICS[key]
        fig.add_trace(go.Box(y=dfa[key], name=METRICS[key][0],
                             marker_color=color, boxpoints="outliers",
                             showlegend=False), row=1, col=i)
        fig.update_yaxes(title_text=unit, row=1, col=i,
                         title_font={"size": 10})
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)")
    fig.update_annotations(font_size=12, font_color="#cfd3da")
    return fig


def make_corr(dfa: pd.DataFrame) -> go.Figure:
    """변수 간 상관관계 히트맵."""
    corr = dfa[SENSOR_KEYS].corr()
    labels_x = [METRICS[k][0] for k in SENSOR_KEYS]
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=labels_x, y=labels_x,
        text=np.round(corr.values, 2), texttemplate="%{text}",
        colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
        colorbar=dict(title="r"), xgap=2, ygap=2,
    ))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                      title=dict(text="변수 상관관계", x=0.5, xanchor="center",
                                 font=dict(size=12, color="#cfd3da")),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


# ── 구역 3: 노드별 시계열(4 변수 1행) ────────────────────
def make_timeseries(dfn: pd.DataFrame) -> go.Figure:
    """선택 노드 → 4개 변수를 1행 4열 라인차트로."""
    fig = make_subplots(rows=1, cols=len(SENSOR_KEYS),
                        subplot_titles=[f"{METRICS[k][0]} ({METRICS[k][1]})"
                                        for k in SENSOR_KEYS])
    for i, key in enumerate(SENSOR_KEYS, start=1):
        color = METRICS[key][2]
        fig.add_trace(go.Scatter(
            x=dfn["recv_time"], y=dfn[key], mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=4),
            showlegend=False), row=1, col=i)
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=40),
                      paper_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=8))
    fig.update_annotations(font_size=11, font_color="#cfd3da")
    return fig


# ════════════════════════════════════════════════════════
#  화면
# ════════════════════════════════════════════════════════
st.set_page_config(page_title="환경 센싱 모니터", page_icon="🌫️", layout="wide")
st_autorefresh(interval=REFRESH_MS, key="auto")

st.markdown("<h1 style='color:#e6e8ec;margin-bottom:2px;'>"
            "🌫️ 멀티노드 환경 센싱 모니터</h1>", unsafe_allow_html=True)

df = load_df()
if df.empty:
    st.info("아직 데이터가 없습니다. hub.py 와 mosquitto 가 돌고 있는지, "
            "노드가 발행 중인지 확인하세요.")
    st.stop()

nodes = sorted(df["node"].dropna().unique())
latest = {n: df[df["node"] == n].iloc[-1].to_dict() for n in nodes}
labels = load_node_labels()

st.caption(f"노드 {len(nodes)}개: {', '.join(label_of(n, labels) for n in nodes)}"
           f"   |   최근 {len(df):,}행  ·  마지막 수신 {df['recv_time'].max()} (KST)")


def header(text, color):
    st.markdown(f"<h3 style='color:{color};margin:14px 0 6px;'>{text}</h3>",
                unsafe_allow_html=True)


# ── 구역 1: 노드 카드 그리드 ──
header("① 노드별 실시간 현황", "#4fd1c5")
ncols = min(len(nodes), MAX_COLS)
for i in range(0, len(nodes), ncols):
    row_nodes = nodes[i:i + ncols]
    cols = st.columns(ncols)
    for col, node in zip(cols, row_nodes):
        with col:
            node_card(node, latest[node], labels)

# ── 구역 2: 전체 통계 (5분 갱신) ──
header("② 전체 통계 (5분 갱신)", "#e0b87a")
dfa = load_all_for_stats()
if not dfa.empty:
    c1, c2 = st.columns([3, 2])
    c1.plotly_chart(make_boxplots(dfa), use_container_width=True, key="box")
    c2.plotly_chart(make_corr(dfa), use_container_width=True, key="corr")

# ── 구역 3: 노드별 시계열 ──
header("③ 노드별 시계열", "#9bb8d3")
sel = st.selectbox("노드 선택", nodes,
                   format_func=lambda n: label_of(n, labels), key="ts_node")
dfn = df[df["node"] == sel].tail(60)
st.plotly_chart(make_timeseries(dfn), use_container_width=True, key="ts")

# ── 구역 4: 최근 5행 + CSV ──
header("④ 최근 기록 & 데이터 내보내기", "#c2afd1")
recent = df[df["node"] == sel][["recv_time"] + SENSOR_KEYS].tail(5).iloc[::-1]
fmt = {k: ("{:.1f}" if k in ("temp", "hum", "gas") else "{:.0f}")
       for k in SENSOR_KEYS}
st.dataframe(recent.style.format(fmt), use_container_width=True, hide_index=True)

# 전체 데이터 CSV 다운로드 — DB 전체를 읽어 즉석 변환
csv_all = load_df(limit=10_000_000)        # 사실상 전체
csv_bytes = csv_all.to_csv(index=False).encode("utf-8-sig")  # 엑셀 한글 호환
st.download_button(
    "📥 전체 데이터 CSV 다운로드",
    data=csv_bytes,
    file_name=f"sensor_data_{df['recv_time'].max()[:10]}.csv",
    mime="text/csv",
)