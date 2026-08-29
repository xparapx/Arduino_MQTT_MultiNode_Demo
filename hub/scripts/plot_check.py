"""Qualitative check of the regime model (Phase 3 verification).

    uv run python scripts/plot_check.py --db fixtures/sample.db --nodes fixtures/nodes.json \
        --as-of "2026-08-29 00:00:00" --out ../scratch

Writes two self-contained HTML figures (plotly, no kaleido needed):
  plane.html : CO2/400 vs VOC/100 scatter coloured by regime + GMM centroids + anchors
  band.html  : per-node regime band over the daily window (smoothed)
Compare them with the slide deck (실제분석사례_교실공기질).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import analyst  # noqa: E402
from aq import config, db, qc, regime  # noqa: E402

COLORS = {"clean": "#8de5a1", "matter": "#ffb482", "human": "#a1c9f4", "mixed": "#ff9f9b"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--nodes", default=str(HUB / "nodes.json"))
    ap.add_argument("--as-of", dest="as_of", default=None)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    cfg = config.load()
    labels_map = analyst.load_labels(Path(a.nodes))
    as_of = analyst.parse_as_of(a.as_of)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    ro = db.connect_ro(a.db)
    model, labels, meta, n = analyst.fit_candidate(ro, cfg, as_of,
                                                   cfg["governance"]["train_window_days"])
    start = as_of - timedelta(days=cfg["run"]["daily_window_days"])
    masked, gate = analyst.prepare(ro, cfg, start, as_of)
    ro.close()
    clean = qc.apply_gate(masked, gate, cfg)
    pred = regime.predict(model, labels, clean, cfg)
    clean = clean.assign(regime=pred)

    # --- plane
    fig = go.Figure()
    for name, g in clean.dropna(subset=["regime"]).groupby("regime"):
        fig.add_trace(go.Scattergl(x=g["co2"] / cfg["regime"]["co2_scale"],
                                   y=g["voc"] / cfg["regime"]["voc_scale"], mode="markers",
                                   name=f"{name} ({len(g)})",
                                   marker=dict(size=4, opacity=0.35, color=COLORS[name])))
    for c in meta["components"]:
        fig.add_trace(go.Scatter(x=[c["mu_scaled"][0]], y=[c["mu_scaled"][1]],
                                 mode="markers+text", textposition="top center",
                                 text=[f"{c['regime']} w={c['weight']:.2f}"],
                                 marker=dict(size=16, symbol="x", color="black"), showlegend=False))
    a_co2, a_voc = regime.anchors(cfg)
    fig.add_vline(x=a_co2, line_dash="dash", line_color="gray")
    fig.add_hline(y=a_voc, line_dash="dash", line_color="gray")
    fig.update_layout(title=f"CO2/VOC plane, GMM on {n} rows "
                            f"({meta['win_start']} .. {meta['win_end']})",
                      xaxis_title="co2 / 400", yaxis_title="voc / 100", height=600)
    fig.write_html(out / "plane.html", include_plotlyjs="cdn")

    # --- band
    nodes = sorted(clean["node"].unique(), key=lambda x: labels_map.get(x, x))
    fig2 = go.Figure()
    for i, node in enumerate(nodes):
        g = clean[clean["node"] == node].reset_index(drop=True)
        sm = regime.smooth(g["regime"], g["bucket"], cfg)
        t = pd.to_datetime(g["bucket"])
        for name in regime.REGIMES:
            m = (sm == name).to_numpy()
            if m.any():
                fig2.add_trace(go.Scatter(x=t[m], y=[labels_map.get(node, node)] * int(m.sum()),
                                          mode="markers", marker=dict(symbol="square", size=9,
                                                                      color=COLORS[name]),
                                          name=name, legendgroup=name, showlegend=(i == 0)))
    fig2.update_layout(title=f"Smoothed regime band, {start:%Y-%m-%d} .. {as_of:%Y-%m-%d} (UTC)",
                       height=120 + 60 * len(nodes), xaxis_title="bucket (UTC)")
    fig2.write_html(out / "band.html", include_plotlyjs="cdn")
    print(f"wrote {out / 'plane.html'} and {out / 'band.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
