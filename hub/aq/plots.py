"""Plotly figures and tables for page 2 (Phase 5), built only from analysis payloads.

Nothing here touches readings / occupancy: every function takes the parsed
payloads that aq.analysis_view returns. Colours follow the page-1 theme.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from aq.derive import (  # noqa: F401  (re-exported for pages and tests)
    ACTION_WORDS,
    DEVICE_KO,
    HOLD,
    LABEL_NEAR,
    LABEL_SLOTS,
    REGIME_KO,
    action_summary,
    label_positions,
    pool_transitions,
)
from aq.regime import REGIMES
from aq.ui_common import GRID, INK, INK_DIM, PASTEL, node_color

REGIME_COLOR = {"clean": PASTEL["green"], "matter": PASTEL["orange"],
                "human": PASTEL["blue"], "mixed": PASTEL["red"], None: "#3a414e"}
KST = timedelta(hours=9)
TS_FMT = "%Y-%m-%d %H:%M:%S"
DENSITY_SCALE = [[0.0, "rgba(0,0,0,0)"], [0.15, "rgba(120,170,255,0.10)"],
                 [0.5, "rgba(120,170,255,0.28)"], [1.0, "rgba(90,140,255,0.55)"]]



def _layout(fig: go.Figure, height: int, **kw) -> go.Figure:
    fig.update_layout(height=height, paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font={"color": INK},
                      margin=dict(l=10, r=10, t=36, b=36), **kw)
    return fig


def _kst(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FMT) + KST


# ---- B: fixed-scale plane ----------------------------------------------------------

def plane_figure(regime_now: dict, labels: dict, cfg: dict, model_meta: dict | None) -> go.Figure:
    """CO2/400 x VOC/100 plane: anchor lines, quadrant names, GMM centroids of the
    current model and one star per node at its latest position."""
    reg = cfg["regime"]
    a_co2 = reg["anchor_co2_ppm"] / reg["co2_scale"]
    a_voc = reg["anchor_voc_index"] / reg["voc_scale"]
    fig = go.Figure()
    xs = [p["co2"] / reg["co2_scale"] for p in regime_now.values() if p["co2"] == p["co2"]]
    ys = [p["voc"] / reg["voc_scale"] for p in regime_now.values() if p["voc"] == p["voc"]]
    xmax = max([5.0, *xs, *(c["mu_scaled"][0] for c in (model_meta or {}).get("components", []))])
    ymax = max([3.0, *ys, *(c["mu_scaled"][1] for c in (model_meta or {}).get("components", []))])
    xmax, ymax = xmax * 1.1, ymax * 1.15
    fig.add_vline(x=a_co2, line_dash="dash", line_color=INK_DIM)
    fig.add_hline(y=a_voc, line_dash="dash", line_color=INK_DIM)
    for name, (qx, qy) in {"clean": (a_co2 / 2, a_voc / 2), "matter": (a_co2 / 2, (a_voc + ymax) / 2),
                           "human": ((a_co2 + xmax) / 2, a_voc / 2),
                           "mixed": ((a_co2 + xmax) / 2, (a_voc + ymax) / 2)}.items():
        fig.add_annotation(x=qx, y=qy, text=f"{REGIME_KO[name]} · {name}", showarrow=False,
                           font={"size": 12, "color": REGIME_COLOR[name]}, opacity=0.8)
    for c in (model_meta or {}).get("components", []):
        fig.add_trace(go.Scatter(x=[c["mu_scaled"][0]], y=[c["mu_scaled"][1]], mode="markers",
                                 marker=dict(symbol="x", size=14, color=REGIME_COLOR[c["regime"]],
                                             line=dict(width=1, color=INK)),
                                 name=f"centroid {c['regime']}", showlegend=False,
                                 hovertemplate=(f"{c['regime']} centroid<br>co2 {c['mu_raw'][0]:.0f}"
                                                f" ppm · voc {c['mu_raw'][1]:.0f}<extra></extra>")))
    stars = [(node, p, p["co2"] / reg["co2_scale"], p["voc"] / reg["voc_scale"])
             for node, p in regime_now.items() if p["co2"] == p["co2"] and p["voc"] == p["voc"]]
    positions = label_positions([(x / xmax, y / ymax) for _, _, x, y in stars])
    for (node, p, x, y), pos in zip(stars, positions, strict=True):
        room = labels.get(node, node)
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers+text", text=[room], textposition=pos,
            textfont={"size": 10, "color": node_color(node)},
            marker=dict(symbol="star", size=16, color=node_color(node), line=dict(width=1.2, color=INK)),
            name=room, showlegend=False,
            hovertemplate=(f"{room}<br>{REGIME_KO.get(p['regime'], p['regime'])} · co2 {p['co2']:.0f}"
                           f" ppm · voc {p['voc']:.0f}<br>dwell {'≥' if p['dwell_censored'] else ''}"
                           f"{p['dwell_min']:.0f} min<extra></extra>")))
    _layout(fig, 440, xaxis=dict(title=f"CO₂ / {reg['co2_scale']}", range=[0, xmax], gridcolor=GRID,
                                 tickfont={"color": INK_DIM}),
            yaxis=dict(title=f"VOC / {reg['voc_scale']}", range=[0, ymax], gridcolor=GRID,
                       tickfont={"color": INK_DIM}))
    return fig


def regime_table(regime_now: dict, actions: dict, labels: dict) -> pd.DataFrame:
    rows = []
    for node, p in regime_now.items():
        rows.append({"교실": labels.get(node, node),
                     "레짐": REGIME_KO.get(p["regime"], "보류" if p["regime"] == HOLD else p["regime"]),
                     "CO₂": None if p["co2"] != p["co2"] else round(p["co2"]),
                     "VOC": None if p["voc"] != p["voc"] else round(p["voc"]),
                     "체류(min)": f"{'≥' if p['dwell_censored'] else ''}{p['dwell_min']:.0f}",
                     "행동": action_summary(actions.get(node, {}))["word"]})
    return pd.DataFrame(rows)


# ---- C: band ----------------------------------------------------------------------

def band_figure(bands: dict, labels: dict) -> go.Figure:
    """Rooms x hourly slots heatmap of the smoothed regime (grey = missing / gated out)."""
    idx = {r: i for i, r in enumerate(REGIMES)}
    nodes = sorted(bands, key=lambda n: labels.get(n, n))
    slots = sorted({s["bucket"] for p in bands.values() for s in p["slots"]})
    z = np.full((len(nodes), len(slots)), np.nan)
    col = {s: j for j, s in enumerate(slots)}
    text = np.full(z.shape, "", dtype=object)
    for i, n in enumerate(nodes):
        for s in bands[n]["slots"]:
            if s["regime"] is not None:
                z[i, col[s["bucket"]]] = idx[s["regime"]]
                text[i, col[s["bucket"]]] = REGIME_KO[s["regime"]]
    colorscale = []
    for i, r in enumerate(REGIMES):
        lo, hi = i / len(REGIMES), (i + 1) / len(REGIMES)
        colorscale += [[lo, REGIME_COLOR[r]], [hi, REGIME_COLOR[r]]]
    fig = go.Figure(go.Heatmap(
        z=z, x=[_kst(s) for s in slots], y=[labels.get(n, n) for n in nodes],
        zmin=-0.5, zmax=len(REGIMES) - 0.5, colorscale=colorscale, showscale=False,
        xgap=1, ygap=3, text=text, hovertemplate="%{y} · %{x|%m-%d %H:%M} KST · %{text}<extra></extra>",
    ))
    fig.update_layout(plot_bgcolor=REGIME_COLOR[None])
    return _layout(fig, 80 + 34 * max(len(nodes), 3), xaxis=dict(tickfont={"color": INK_DIM}),
                   yaxis=dict(tickfont={"color": INK}, autorange="reversed"))


def band_share(bands: dict) -> dict:
    """% of slots per regime (missing counted separately)."""
    c = Counter(s["regime"] for p in bands.values() for s in p["slots"])
    tot = sum(c.values()) or 1
    return {k: round(100 * v / tot, 1) for k, v in c.items()}


# ---- D: transitions -----------------------------------------------------------------

def transition_summary(transitions: dict) -> tuple[pd.DataFrame, dict]:
    """Pooled per-regime table (aq.derive.pool_transitions) + totals."""
    pooled = pool_transitions(transitions)
    rows = []
    for r in pooled["rows"]:
        rows.append({"레짐": f"{REGIME_KO[r['regime']]} · {r['regime']}",
                     "지속확률": r["persist"], "중앙 체류(min)": r["dwell_median"],
                     "가장 흔한 다음 전이": (f"→ {REGIME_KO[r['next']]} {r['next_p']:.3f}"
                                    if r["next"] else "—"),
                     "관측 쌍": r["pairs"]})
    return pd.DataFrame(rows), {"gap_pairs": pooled["gap_pairs"],
                                "valid_pairs": pooled["valid_pairs"], "counts": pooled["counts"]}


def transition_matrix_figure(counts: dict) -> go.Figure:
    z = [[(counts[a][b] / sum(counts[a].values())) if sum(counts[a].values()) else 0
          for b in REGIMES] for a in REGIMES]
    names = [REGIME_KO[r] for r in REGIMES]
    fig = go.Figure(go.Heatmap(z=z, x=names, y=names, zmin=0, zmax=1,
                               colorscale=[[0, "#242832"], [1, PASTEL["blue"]]],
                               text=[[f"{v:.3f}" for v in row] for row in z], texttemplate="%{text}",
                               textfont={"color": INK}, showscale=False, xgap=2, ygap=2))
    return _layout(fig, 300, xaxis=dict(title="다음", tickfont={"color": INK_DIM}),
                   yaxis=dict(title="현재", tickfont={"color": INK_DIM}, autorange="reversed"))


# ---- E / F / G / I tables ----------------------------------------------------------

def actions_table(actions: dict, labels: dict, run_at: str | None = None) -> pd.DataFrame:
    """One row per room: 행동 · 근거 · 판정 시각 (the hourly run, KST) · 유지 (when
    something is ON: since when, plus the minimum-run end while it still binds)."""
    rows = []
    for node, devs in actions.items():
        a = action_summary(devs)
        keep = "—"
        if a["since"]:
            keep = f"{_kst(a['since']).strftime('%m-%d %H:%M')}부터"
            if run_at is None or a["hold_until"] > run_at:
                keep += f" · 최소 ~{_kst(a['hold_until']).strftime('%H:%M')}"
        rows.append({"교실": labels.get(node, node), "행동": a["word"], "근거": a["reason"],
                     "판정 시각": _kst(run_at).strftime("%m-%d %H:%M") if run_at else "—",
                     "유지": keep})
    return pd.DataFrame(rows)


def forecast_table(forecasts: dict, regime_now: dict, labels: dict, cfg: dict) -> pd.DataFrame:
    rows = []
    for node, p in forecasts.items():
        now = regime_now.get(node, {})
        rows.append({"교실": labels.get(node, node),
                     "CO₂ now": None if now.get("co2", float("nan")) != now.get("co2") else round(now["co2"]),
                     f"CO₂ +{p['horizon_min']}min": round(p["co2_pred"]),
                     "VOC now": None if now.get("voc", float("nan")) != now.get("voc") else round(now["voc"]),
                     f"VOC +{p['horizon_min']}min": round(p["voc_pred"]),
                     "경보": "⚠ 임계 초과 예상" if p["alert"] else "—",
                     "학습 행": p.get("train_rows")})
    return pd.DataFrame(rows)


def occ_table(payload: dict, labels: dict, win_start: str | None = None) -> pd.DataFrame:
    """One row per room with a vision node. 마지막 비전 버킷 = last occupancy
    bucket (KST); a room whose last bucket is before win_start is marked 중단."""
    rows = []
    for room, s in payload.get("by_room", {}).items():
        last = s.get("last_bucket")
        if not last:
            seen = "—"
        else:
            seen = _kst(last).strftime("%m-%d %H:%M")
            if win_start and last < win_start:
                seen += " · 중단"
        rows.append({"교실": room, "조인 행": s["n"], "Spearman ρ": s["rho"],
                     "기울기 (ppm/인)": None if s["slope"] is None else round(s["slope"], 1),
                     "마지막 비전 버킷 (KST)": seen})
    return pd.DataFrame(rows)


def model_history_table(events: list[dict]) -> pd.DataFrame:
    rows = []
    for e in events:
        p = e["payload"]
        meta = p.get("meta", {})
        rows.append({"run_at (KST)": _kst(e["run_at"]).strftime("%m-%d %H:%M"),
                     "후보": p.get("candidate_ver"), "결정": p.get("decision"),
                     "학습 창": f"{meta.get('win_start', '')[:10]} → {meta.get('win_end', '')[:10]}"
                     if meta else "—",
                     "행 수": meta.get("rows"), "중심 이동": p.get("centroid_shift"),
                     "로그우도 Δ": p.get("loglik_delta"), "current": p.get("current_after"),
                     "사유": p.get("reason", "")[:120]})
    return pd.DataFrame(rows)


# ---- H: exploratory views -------------------------------------------------------------

def corr_figure(explore: dict) -> go.Figure:
    vars_ = explore["vars"]
    z = [[explore["corr"][a].get(b) for b in vars_] for a in vars_]
    fig = go.Figure(go.Heatmap(
        z=z, x=vars_, y=vars_, zmin=-1, zmax=1, zmid=0,
        colorscale=[[0.0, PASTEL["red"]], [0.5, "#eceff4"], [1.0, PASTEL["blue"]]],
        text=[[("" if v is None else f"{v:.2f}") for v in row] for row in z], texttemplate="%{text}",
        textfont={"color": "#2a2d34", "size": 10}, xgap=2, ygap=2,
        colorbar=dict(title="ρ", tickfont={"color": INK_DIM})))
    return _layout(fig, 320, title=dict(text="Spearman 상관 (28일)", x=0.5, font=dict(size=12, color=INK_DIM)),
                   xaxis=dict(tickfont={"size": 10, "color": INK_DIM}),
                   yaxis=dict(tickfont={"size": 10, "color": INK_DIM}, autorange="reversed"))


def _density_figure(d: dict, title: str, current: list[tuple[str, float, float, str]],
                    height: int) -> go.Figure:
    amax, bins = d["amax"], d["bins"]
    edges = np.linspace(-amax, amax, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    fig = go.Figure(go.Heatmap(z=np.array(d["hist"]).T, x=centers, y=centers, colorscale=DENSITY_SCALE,
                               showscale=False, zsmooth="best", hoverinfo="skip"))
    for room, x, y, col in current:
        cx, cy = max(-amax, min(amax, x)), max(-amax, min(amax, y))
        fig.add_annotation(x=cx, y=cy, ax=0, ay=0, xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=2, arrowwidth=2, arrowcolor=col, opacity=0.9)
        fig.add_trace(go.Scatter(x=[cx], y=[cy], mode="markers+text", text=[room],
                                 textposition="top center", textfont={"size": 9, "color": col},
                                 marker=dict(symbol="star" if (cx == x and cy == y) else "diamond-open",
                                             size=13, color=col, line=dict(width=1, color=INK)),
                                 showlegend=False, hoverinfo="skip"))
    for qx, qy, qt in [(amax * 0.6, amax * 0.6, "Human ≈ Matter"), (-amax * 0.6, amax * 0.6, "Matter > Human"),
                       (amax * 0.6, -amax * 0.6, "Human > Matter"), (-amax * 0.6, -amax * 0.6, "Clean")]:
        fig.add_annotation(x=qx, y=qy, text=qt, showarrow=False, font={"size": 10, "color": INK_DIM})
    axis = dict(gridcolor=GRID, dtick=1, range=[-amax, amax], tickfont={"color": INK_DIM},
                zeroline=True, zerolinecolor=INK, zerolinewidth=2, showline=True, linecolor=INK_DIM,
                mirror=True)
    return _layout(fig, height, title=dict(text=title, x=0.5, font=dict(size=12, color=INK_DIM)),
                   xaxis=dict(title="CO₂ (robust)", **axis), yaxis=dict(title="VOC (robust)", **axis))


def _rc(v, med, iqr):
    return (v - med) / iqr if iqr and iqr > 0 else 0.0


def pooled_figure(explore: dict, regime_now: dict, labels: dict) -> go.Figure | None:
    d = explore.get("pooled")
    if not d:
        return None
    cur = [(labels.get(n, n), _rc(p["co2"], d["co2_med"], d["co2_iqr"]),
            _rc(p["voc"], d["voc_med"], d["voc_iqr"]), node_color(n))
           for n, p in regime_now.items() if p["co2"] == p["co2"] and p["voc"] == p["voc"]]
    return _density_figure(d, f"Pooled 상대 레짐 — 노드 간 비교 · ★ 현재 (n={d['n']:,})", cur, 440)


def within_figure(explore: dict, node: str, regime_now: dict, labels: dict) -> go.Figure | None:
    d = explore.get("nodes", {}).get(node)
    if not d:
        return None
    p = regime_now.get(node)
    cur = []
    if p and p["co2"] == p["co2"] and p["voc"] == p["voc"]:
        cur = [(labels.get(node, node), _rc(p["co2"], d["co2_med"], d["co2_iqr"]),
                _rc(p["voc"], d["voc_med"], d["voc_iqr"]), PASTEL["orange"])]
    return _density_figure(d, f"{labels.get(node, node)} 자기 기준 (within-node, n={d['n']:,})", cur, 440)
