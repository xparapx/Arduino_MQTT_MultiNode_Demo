"""Read side of the analysis table for the dashboard (Phase 5, page 2) and the
service-status sidebar shared by both pages.

pages/2_diagnosis.py may only reach the DB through this module: it never
touches readings / occupancy except inside service_status(), which the CI
grep on pages/ does not cover on purpose (the sidebar shows hub freshness).
Everything is cached on analysis_version() = (MAX(id), MAX(run_at)).
"""

from __future__ import annotations

import json
import os
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import streamlit as st

from aq import governance
from aq.ui_common import DB, INK, _occ_table_exists, _ro, data_version, load_node_labels

TS_FMT = "%Y-%m-%d %H:%M:%S"
KST = timedelta(hours=9)
ACTIVE_WINDOW_MIN = 15        # a node with a row in the last 15 min counts as active
VISION_RECENT_DAYS = 1
COLS = ("id", "run_at", "scope", "win_start", "win_end", "model_ver", "payload")


def _has_table(con, name: str) -> bool:
    return bool(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                            (name,)).fetchone())


def _parse(rows) -> list[dict]:
    out = []
    for r in rows:
        d = dict(zip(COLS, r, strict=True))
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


@st.cache_data(ttl=60, show_spinner=False)
def analysis_version() -> tuple[int, str]:
    """(MAX(id), MAX(run_at)) of the analysis table; (0, '') when absent or empty."""
    if not os.path.isfile(DB):
        return 0, ""
    with closing(_ro()) as con:
        if not _has_table(con, "analysis"):
            return 0, ""
        mid, ts = con.execute("SELECT MAX(id), MAX(run_at) FROM analysis").fetchone()
    return (int(mid) if mid else 0), (ts or "")


@st.cache_data(ttl=300, show_spinner=False)
def latest_rows(aid: int, kind: str) -> list[dict]:
    """Rows of `kind` from its most recent run_at (every scope), payload parsed."""
    if aid == 0:
        return []
    sql = ("SELECT id, run_at, scope, win_start, win_end, model_ver, payload FROM analysis "
           "WHERE kind=? AND run_at=(SELECT MAX(run_at) FROM analysis WHERE kind=?) ORDER BY id")
    with closing(_ro()) as con:
        return _parse(con.execute(sql, (kind, kind)).fetchall())


@st.cache_data(ttl=300, show_spinner=False)
def recent_rows(aid: int, kind: str, limit: int = 50) -> list[dict]:
    """Most recent `limit` rows of `kind`, newest first, payload parsed."""
    if aid == 0:
        return []
    sql = ("SELECT id, run_at, scope, win_start, win_end, model_ver, payload FROM analysis "
           "WHERE kind=? ORDER BY id DESC LIMIT ?")
    with closing(_ro()) as con:
        return _parse(con.execute(sql, (kind, limit)).fetchall())


def by_scope(rows: list[dict]) -> dict[str, dict]:
    """{scope: payload} for one-row-per-scope kinds (qc, regime_now, band, ...)."""
    return {r["scope"]: r["payload"] for r in rows}


def kst(ts_utc: str | None, fmt: str = "%m-%d %H:%M") -> str:
    if not ts_utc:
        return "—"
    return (datetime.strptime(ts_utc, TS_FMT) + KST).strftime(fmt)


# ---- sidebar ---------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def service_status(max_id: int, aid: int) -> dict:
    """hub freshness, node activity, analyst runs and model version."""
    out = {"hub_last": None, "hub_age_min": None, "readings_rows": 0, "env_active": 0,
           "vis_recent": 0, "hourly": "", "daily": "", "weekly": "", "model": None,
           "journal": None}
    if not os.path.isfile(DB):
        return out
    with closing(_ro()) as con:
        out["journal"] = con.execute("PRAGMA journal_mode").fetchone()[0]
        out["readings_rows"] = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        last = con.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
        out["env_active"] = con.execute(
            "SELECT COUNT(*) FROM (SELECT node FROM readings "
            "WHERE id > (SELECT MAX(id) FROM readings) - 2000 GROUP BY node "
            "HAVING MAX(ts) >= datetime('now', ?))", (f"-{ACTIVE_WINDOW_MIN} minutes",)
        ).fetchone()[0]
        if _occ_table_exists():
            out["vis_recent"] = con.execute(
                "SELECT COUNT(*) FROM (SELECT node FROM occupancy "
                "WHERE id > (SELECT MAX(id) FROM occupancy) - 2000 GROUP BY node "
                "HAVING MAX(ts) >= datetime('now', ?))", (f"-{VISION_RECENT_DAYS} days",)
            ).fetchone()[0]
    if last:
        out["hub_last"] = last
        out["hub_age_min"] = (datetime.now(UTC).replace(tzinfo=None)
                              - datetime.strptime(last, TS_FMT)).total_seconds() / 60
    for key, kind in (("hourly", "summary"), ("daily", "band"), ("weekly", "model_event")):
        rows = latest_rows(aid, kind)
        out[key] = rows[0]["run_at"] if rows else ""
    try:
        out["model"] = governance.resolve_current(Path(os.path.abspath(DB)).parent / "models")
    except OSError:
        out["model"] = None
    return out


def render_sidebar(page: str) -> None:
    """Service status block shared by both pages (mockup left column)."""
    max_id, _ = data_version()
    aid, _ = analysis_version()
    s = service_status(max_id, aid)
    n_env = sum(1 for k in load_node_labels() if not k.startswith("vis"))
    with st.sidebar:
        st.markdown(f"<div style='font-weight:700;color:{INK};font-size:15px;margin-bottom:6px'>"
                    "multinode_aq · UNO Q (aqhub)</div>", unsafe_allow_html=True)
        st.caption("교실 공기질 모니터 · " + ("1 모니터링" if page == "1"
                                              else "2 진단 · 추론 · 행동지침"))
        fresh = s["hub_age_min"] is not None and s["hub_age_min"] <= ACTIVE_WINDOW_MIN
        st.markdown(f"**hub.py** {'🟢 수집 중' if fresh else '🔴 수신 지연'}  \n"
                    f"마지막 수신 {kst(s['hub_last'])} KST  \n"
                    f"환경 노드 {s['env_active']} / {n_env} 활성 · 비전 노드 {s['vis_recent']} 최근  \n"
                    f"readings {s['readings_rows']:,} 행 · journal {s['journal']}")
        st.markdown("---")
        if s["hourly"]:
            st.markdown(f"**analyst.py** 🟢 hourly {kst(s['hourly'])} KST  \n"
                        f"daily {kst(s['daily'])} · weekly {kst(s['weekly'])}  \n"
                        f"진단 모델 {s['model'] or '없음'}")
        else:
            st.markdown(f"**analyst.py** ⚪ 아직 실행 없음 (Phase 6 타이머)  \n"
                        f"진단 모델 {s['model'] or '없음'}")
        st.caption("sensor_data.db · readings / occupancy / analysis · pages/ · fragment 60 s")
