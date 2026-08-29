"""Page 2 -- 진단 · 추론 · 행동지침 (Phase 5).

Reads ONLY the analysis table (through aq.analysis_view); never readings or
occupancy. Sections follow docs/plan/dashboard_mockup_v2.html: A validity,
B current regime plane, C switching band, D transitions / dwell, E actions,
F forecast, G occupancy x CO2, H exploratory views, I model history.
One fragment refreshed every 5 minutes; an empty analysis table shows guidance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

import streamlit as st

HUB = Path(__file__).resolve().parent.parent
if str(HUB) not in sys.path:
    sys.path.insert(0, str(HUB))

from aq import analysis_view as av  # noqa: E402
from aq import config, governance, plots  # noqa: E402
from aq.regime import REGIMES  # noqa: E402
from aq.ui_common import (  # noqa: E402
    BG,
    H_EXPORT,
    H_OVERVIEW,
    H_STATS,
    H_TS,
    INK,
    PANEL_BG,
    _perf,
    header,
    label_of,
    load_node_labels,
    reset_perf,  # noqa: E402
)

reset_perf()
REFRESH = "5m"

st.set_page_config(page_title="진단 · 추론 · 행동지침", page_icon="*", layout="wide")
st.markdown(f"""
<style>
  .stApp {{ background:{BG}; color:{INK}; }}
  section[data-testid="stSidebar"] {{ background:{PANEL_BG}; }}
  [data-testid="stMetricValue"], .stMarkdown, p, span, label {{ color:{INK}; }}
  div[data-testid="stVerticalBlockBorderWrapper"] {{ background:{PANEL_BG}; border-radius:12px; }}
</style>
""", unsafe_allow_html=True)

av.render_sidebar("2")
st.markdown(f"<h1 style='color:{INK};margin-bottom:2px;'>진단 · 추론 · 행동지침</h1>",
            unsafe_allow_html=True)
st.caption("analyst.py가 저장한 analysis 테이블만 읽어 표시 — ML(GMM)이 \"무엇이 문제인지\", "
           "규칙이 \"행동할 때인지\" · 이 페이지는 readings를 직접 읽지 않음")

CFG = config.load()
LABELS = load_node_labels()


def model_meta_for(ver: str | None) -> dict | None:
    """Meta JSON of a model version (models/gmm_vN.json); None when unknown."""
    if not ver or ver == "adhoc":
        return None
    p = HUB / CFG["governance"]["models_dir"] / f"{ver}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def empty_state() -> None:
    st.info("아직 분석 결과가 없습니다 — `analysis` 테이블이 비어 있습니다. "
            "analyst.py가 처음 실행되면(Phase 6 타이머: hourly *:05 / daily 06:00 / weekly Sun 06:30 UTC) "
            "이 페이지가 채워집니다. 그 전까지는 페이지 1(모니터링)을 보세요.")
    with st.expander("여기에 나타날 내용"):
        st.markdown("- **A 유효 범위** — 분석 창·모델 버전·노드별 QC 판정\n"
                    "- **B 현재 레짐** — 고정 스케일 CO₂×VOC 평면 위의 교실 위치와 체류시간\n"
                    "- **C 레짐 스위칭 밴드** — 7일 × 교실, 시간 단위\n"
                    "- **D 전이확률 · 체류시간** — 지속확률, 가장 흔한 다음 전이\n"
                    "- **E 행동지침** — 환풍기/공기청정기 ON/OFF와 그 규칙\n"
                    "- **F 예측 · 경보** — 30분 후 CO₂·VOC\n"
                    "- **G 재실 × CO₂** — 비전 노드 조인 상관\n"
                    "- **H 탐색 시각화** — 상관 히트맵, RobustScaling 산점도(페이지 1에서 이관)\n"
                    "- **I 모델 이력** — weekly refit → 비교 → 조건부 승격")
    st.code("cd ~/multinode_aq/hub && .venv/bin/python analyst.py run --mode hourly --dry-run | head",
            language="bash")


aid, last_run = av.analysis_version()
if aid == 0:
    empty_state()
    _perf("page2 empty")
    st.stop()


@st.fragment(run_every=REFRESH)
def diagnosis() -> None:
    t = perf_counter()
    aid, _ = av.analysis_version()
    regime_now = av.by_scope(av.latest_rows(aid, "regime_now"))
    actions: dict[str, dict] = {}
    for r in av.latest_rows(aid, "action"):
        actions.setdefault(r["scope"], {})[r["payload"]["device"]] = r["payload"]
    forecasts = av.by_scope(av.latest_rows(aid, "forecast"))
    qc_hourly = av.by_scope(av.latest_rows(aid, "qc"))
    bands = av.by_scope(av.latest_rows(aid, "band"))
    transitions = av.by_scope(av.latest_rows(aid, "transition"))
    occ_rows = av.latest_rows(aid, "occ_co2")
    explore_rows = av.latest_rows(aid, "explore")
    events = av.recent_rows(aid, "model_event", 20)
    summary = av.latest_rows(aid, "summary")
    reg_rows = av.latest_rows(aid, "regime_now")
    model_ver = reg_rows[0]["model_ver"] if reg_rows else None
    daily_rows = av.latest_rows(aid, "band")
    meta = model_meta_for(model_ver)

    if summary:
        with st.container(border=True):
            st.markdown("**이번 시간 핵심 요약**  \n" + "  \n".join(
                f"• {ln}" for ln in summary[0]["payload"]["lines"]))
            st.caption(f"hourly {av.kst(summary[0]['run_at'])} KST")

    # ---- A
    header("A) 유효 범위 — 이 페이지의 해석이 성립하는 조건", H_OVERVIEW)
    c1, c2, c3, c4 = st.columns(4)
    if daily_rows:
        c1.metric("daily 분석 창", f"{daily_rows[0]['win_start'][5:10]} → {daily_rows[0]['win_end'][5:10]}",
                  f"daily {av.kst(daily_rows[0]['run_at'])} KST")
    else:
        c1.metric("daily 분석 창", "—", "daily 미실행")
    c2.metric("진단 모델", model_ver or "—",
              f"{meta['rows']:,}행 · {meta.get('window_days', '')}d 학습" if meta else "")
    if transitions:
        _, tot = plots.transition_summary(transitions)
        c3.metric("전이 집계 유효 쌍", f"{tot['valid_pairs']:,}", f"결측 단절 {tot['gap_pairs']}회 제외")
    else:
        c3.metric("전이 집계", "—")
    c4.metric("hourly 마지막 실행", av.kst(reg_rows[0]["run_at"]) if reg_rows else "—",
              f"{len(reg_rows)}노드 판정")
    if qc_hourly:
        import pandas as pd

        qdf = pd.DataFrame([{"교실": label_of(n, LABELS), "노드": n,
                             "CO₂ 유효율": f"{p['valid_co2_pct']:.1f}%",
                             "VOC 유효율": f"{p['valid_voc_pct']:.1f}%",
                             "판정": "사용" if p["passed"] else "제외",
                             "사유": p["reason"] or "—"} for n, p in qc_hourly.items()])
        st.dataframe(qdf, width="stretch", hide_index=True)
    st.caption("QC: 노드×일 CO₂ 유효율 ≥ 95%(수신 행 기준, KST 일)만 사용 · 5분 floor 버킷 · 보간 없음")

    # ---- B
    header("B) 현재 레짐 — 고정 스케일 CO₂×VOC 평면", H_STATS)
    st.caption(f"hourly · {model_ver or '—'} predict · 45분 평활 · CO₂÷{CFG['regime']['co2_scale']} · "
               f"VOC÷{CFG['regime']['voc_scale']} · 체류 = 현재 레짐에 머문 시간(관측 하한)")
    b1, b2 = st.columns([3, 2])
    if regime_now:
        b1.plotly_chart(plots.plane_figure(regime_now, LABELS, CFG, meta), width="stretch",
                        key="plane")
        b2.dataframe(plots.regime_table(regime_now, actions, LABELS), width="stretch", hide_index=True)
    else:
        b1.info("hourly 판정 없음")

    # ---- C
    header("C) 레짐 스위칭 밴드 — 7일 × 교실", H_TS)
    if bands:
        share = plots.band_share(bands)
        st.caption("daily · 시간 단위 mode · 회색 = 결측/게이트 탈락 · " + " · ".join(
            f"{plots.REGIME_KO[r]} {share.get(r, 0):.1f}%" for r in REGIMES)
            + (f" · 결측 {share[None]:.1f}%" if None in share else ""))
        st.plotly_chart(plots.band_figure(bands, LABELS), width="stretch", key="band")
    else:
        st.info("daily 실행 후 표시됩니다.")

    # ---- D
    header("D) 전이확률 · 체류시간", H_TS)
    if transitions:
        tdf, tot = plots.transition_summary(transitions)
        st.caption(f"Δt = {CFG['time']['transition_dt_minutes']} min ± "
                   f"{CFG['time']['transition_dt_tolerance']} · 단절 쌍 {tot['gap_pairs']}개 제외 · "
                   "체류시간은 결측 단절로 잘린 구간을 포함하므로 하한")
        d1, d2 = st.columns([3, 2])
        d1.dataframe(tdf, width="stretch", hide_index=True)
        d2.plotly_chart(plots.transition_matrix_figure(tot["counts"]), width="stretch", key="trans")
    else:
        st.info("daily 실행 후 표시됩니다.")

    # ---- E
    header("E) 행동지침 — 레짐(ML) × 임계(규칙) × 히스테리시스", H_EXPORT)
    r = CFG["rules"]
    st.caption(f"hourly · 환풍기 ON CO₂>{r['fan']['on_co2']:g} / OFF <{r['fan']['off_co2']:g} · "
               f"공청기 ON VOC>{r['purifier']['on_voc']:g} / OFF <{r['purifier']['off_voc']:g} · "
               f"최소 동작 {r['min_run_minutes']}분 · QC 탈락 노드는 hold")
    if actions:
        st.dataframe(plots.actions_table(actions, LABELS), width="stretch", hide_index=True)
    else:
        st.info("hourly 판정 없음")

    # ---- F
    header("F) 예측 · 경보 — 30분 후 CO₂ · VOC", H_EXPORT)
    st.caption("hourly · 다중출력 회귀(StandardScaler → Ridge) · 타깃 = 미래 실측값 · 경보 = 예측값이 ON 임계 초과")
    if forecasts:
        st.dataframe(plots.forecast_table(forecasts, regime_now, LABELS, CFG), width="stretch",
                     hide_index=True)
    else:
        st.info("예측 없음 (연속 버킷이 4시간 미만이거나 QC 탈락)")

    # ---- G
    header("G) 재실 × CO₂ — 비전 노드 조인", H_OVERVIEW)
    st.caption(f"daily · (교실, 5분 버킷) 정확 조인 · occ n ≥ {CFG['occ_co2']['min_occ_n']} · "
               "ρ는 포화형 관계라 Spearman · 기울기는 참고값")
    if occ_rows:
        p = occ_rows[0]["payload"]
        g1, g2 = st.columns([1, 2])
        g1.metric("pooled Spearman ρ", "—" if p["spearman_rho"] != p["spearman_rho"] else f"{p['spearman_rho']:.2f}",
                  f"n = {p['n']:,}")
        odf = plots.occ_table(p, LABELS)
        if len(odf):
            g2.dataframe(odf, width="stretch", hide_index=True)
        else:
            g2.info("조인된 (교실, 버킷)이 없습니다 — 비전 노드 데이터 확인")
    else:
        st.info("daily 실행 후 표시됩니다.")

    # ---- H
    header("H) 탐색 시각화 — 상관 · 상대 레짐 (RobustScaling)", H_STATS)
    st.caption("daily · 페이지 1에서 이관 · 판정에 쓰지 않음 · 서버 집계본(24×24 / 20×20)")
    if explore_rows:
        ex = explore_rows[0]["payload"]
        h1, h2 = st.columns([2, 3])
        h1.plotly_chart(plots.corr_figure(ex), width="stretch", key="corr")
        pooled = plots.pooled_figure(ex, regime_now, LABELS)
        if pooled:
            h2.plotly_chart(pooled, width="stretch", key="pooled")
        nodes = sorted(ex.get("nodes", {}), key=lambda n: label_of(n, LABELS))
        if nodes:
            sel = st.selectbox("자기 기준 산점도 — 교실", nodes, format_func=lambda n: label_of(n, LABELS),
                               key="within_node")
            within = plots.within_figure(ex, sel, regime_now, LABELS)
            if within:
                st.plotly_chart(within, width="stretch", key="within")
        st.caption("여기 두 산점도는 \"층위 1: 보는 도구\". 판정 엔진(B~E)은 고정 스케일 GMM만 사용 — "
                   "데이터 의존 스케일러는 재학습 때 군집이 뒤집히기 때문.")
    else:
        st.info("daily 실행 후 표시됩니다.")

    # ---- I
    header("I) 모델 이력", H_EXPORT)
    gov = CFG["governance"]
    st.caption(f"weekly · refit → 비교 → 조건부 승격: 4분면 상이 ∧ (로그우도 +{gov['loglik_gain_min']:.0%} "
               f"∨ 중심 이동 ≥ {gov['centroid_shift_min']}) ∨ 학사 경계일 · 학습 창 {gov['train_window_days']}d")
    versions = governance.list_versions(HUB / gov["models_dir"])
    cur = governance.resolve_current(HUB / gov["models_dir"], gov["current_link"])
    st.markdown(f"저장된 버전: {', '.join(versions) or '없음'} · current **{cur or '없음'}**")
    if events:
        st.dataframe(plots.model_history_table(events), width="stretch", hide_index=True)
    else:
        st.info("weekly 실행 후 표시됩니다.")
    _perf("page2", t)


diagnosis()
_perf("page2 full run")
