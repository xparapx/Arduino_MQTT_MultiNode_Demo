# -*- coding: utf-8 -*-
"""MintCap 차트 — 하나의 디자인 체계로 전부 다시 그림.
   디자인 원칙
   1) 글자는 두 단계뿐: 제목(굵게) / 그 밖의 모든 글자. 실제 인쇄 크기 기준(pt)으로 고정
      — 보고서 10/9pt, 포스터 20/16pt. 그림을 '실제 크기(mm)'로 만들고 그 크기 그대로 넣는다.
   2) 색은 의미에만: CO₂=파랑, VOC=주황, 청정·강조=민트, 복합=보라, 기준선=빨강. 나머지는 무채색.
   3) 한 그림 한 메시지: 제목이 곧 결론.
   4) 잉크 최소화: 위·오른쪽 축선 제거, 옅은 가로 격자만."""
import os, sys, io, json
import numpy as np, pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
INK = "#14283c"; SUB = "#5b6b79"; GRID = "#e3e8ec"; NEUTRAL = "#c5ced6"
CO2 = "#2f6fb5"; VOC = "#d9772b"; MINT = "#1fa97f"; MIX = "#7a5bb5"; WARN = "#d64545"
KR = {f"CLASS_0{i}": f"{i}반" for i in range(1, 9)}
r = pd.read_pickle(HERE + "/r.pkl"); o = pd.read_pickle(HERE + "/o.pkl"); ev = pd.read_pickle(HERE + "/ev.pkl")
rec = pd.read_pickle(HERE + "/rec.pkl"); j = pd.read_pickle(HERE + "/j.pkl"); S = json.load(open(HERE + "/stats.json", encoding="utf-8"))
MM = 1 / 25.4

def theme(base, title):
    k = base / 9.0
    plt.rcParams.update({
        "font.family": "Malgun Gothic", "axes.unicode_minus": False,
        "font.size": base, "axes.titlesize": base, "axes.labelsize": base, "legend.fontsize": base,
        "xtick.labelsize": base, "ytick.labelsize": base, "figure.titlesize": title,
        "text.color": INK, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "axes.edgecolor": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .7 * k,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": .6 * k, "axes.axisbelow": True,
        "xtick.major.width": .7 * k, "ytick.major.width": .7 * k, "xtick.major.size": 2.5 * k, "ytick.major.size": 2.5 * k,
        "lines.linewidth": 1.4 * k, "savefig.dpi": 400 if base < 12 else 200, "figure.dpi": 100,
        "legend.frameon": False, "legend.handlelength": 1.6, "legend.borderaxespad": .2})
    return k

def new(w, h, base, title, ttl, ncols=1, **gk):
    k = theme(base, title)
    fig, axes = plt.subplots(1, ncols, figsize=(w * MM, h * MM), layout="constrained", gridspec_kw=gk or None)
    fig.get_layout_engine().set(w_pad=1.2 * k / 72 * 4, h_pad=1.0 * k / 72 * 4, wspace=.04)
    fig.suptitle(ttl, x=0.012, ha="left", fontweight="bold", fontsize=title, color=INK)
    return fig, axes, k

def thr(ax, k, label=True, x=None):
    ax.axhline(1000, color=WARN, ls=(0, (4, 3)), lw=1.0 * k, zorder=3, label="권고 기준 1,000 ppm" if label else None)

def save(fig, out):
    fig.savefig(out, facecolor="white"); plt.close(fig); print("saved", os.path.basename(out))

# ---------------- 1. 수업일 하루 ----------------
def day(w, h, base, title, out):
    fig, ax, k = new(w, h, base, title, "수업일 하루 — 사람이 들어오면 CO₂가 오른다 (1반, 9월 15일)" if base < 12 else "수업일 하루 — 사람이 오면 오른다")
    d = "2026-09-15"
    g = r[r.room == "CLASS_01"].set_index("ts").sort_index().loc[d]
    og = o[o.room == "CLASS_01"].set_index("ts").sort_index().loc[d].occ_med.resample("5min").max().fillna(0)
    ax2 = ax.twinx(); ax2.grid(False); ax2.spines["right"].set_visible(False); ax2.spines["top"].set_visible(False)
    ax2.fill_between(og.index, 0, og.values, step="mid", color=NEUTRAL, lw=0, alpha=.9, label="재실 인원(탐지)")
    ax2.set_ylim(0, 9); ax2.set_yticks([]); ax2.set_zorder(1)
    ax.set_zorder(2); ax.patch.set_alpha(0)
    ax.plot(g.index, g.co2, color=CO2, label="CO₂")
    ax.set_xlim(pd.Timestamp(d), pd.Timestamp(d) + pd.Timedelta(days=1))
    thr(ax, k)
    ax.set_ylabel("CO₂ (ppm)"); ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 4)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H시"))
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", ncols=3 if base < 12 else 1)
    save(fig, out)

# ---------------- 2. 시간대별 ----------------
def hourly(w, h, base, title, out):
    fig, axes, k = new(w, h, base, title, "시간대별 CO₂ — 두 봉우리는 주중에만 나타난다 (73일, 8개 교실)" if base < 12 else "두 봉우리는 주중에만 나타난다", ncols=2)
    for i, (ax, (wd, lab)) in enumerate(zip(axes, [(True, "주중"), (False, "주말")])):
        q = r[r.wd == wd].groupby("hour").co2.quantile([.25, .5, .75]).unstack()
        ax.fill_between(q.index, q[.25], q[.75], color=CO2, alpha=.18, lw=0, label="가운데 50% 범위")
        ax.plot(q.index, q[.5], color=CO2, label="중앙값")
        thr(ax, k, label=(i == 1), x=0)
        ax.set_xlim(0, 23); ax.set_ylim(350, 1900); ax.set_xticks(range(0, 24, 6)); ax.set_xlabel(lab + " · 시각(시)")
        if i: ax.tick_params(labelleft=False)
    axes[0].set_ylabel("CO₂ (ppm)"); axes[1].legend(loc="upper right")
    save(fig, out)

# ---------------- 3. 교실별 초과율 ----------------
def exceed(w, h, base, title, out=None, ax=None, k=None):
    own = ax is None
    if own: fig, ax, k = new(w, h, base, title, "교실별 기준 초과율 — 수업시간의 31–45%가 1,000 ppm 초과")
    t = pd.DataFrame(S["table"]).set_index("room")
    x = np.arange(8); v = t.over1000.values
    ax.bar(x, v, width=.62, color=CO2)
    for xi, vi in zip(x, v): ax.text(xi, vi + 1, f"{vi:.0f}", ha="center", va="bottom")
    ax.axhline(v.mean(), color=INK, lw=.8 * k, ls=(0, (2, 2)), label=f"8개 교실 평균 {v.mean():.0f}%"); ax.legend(loc="upper left")
    ax.set_xticks(x, [KR[i] for i in t.index]); ax.set_ylim(0, 66); ax.set_yticks([0, 20, 40]); ax.set_ylabel("초과 비율 (%)")
    if own: save(fig, out)

# ---------------- 4. 재실–CO₂ ----------------
def _scatter(ax, k):
    g1 = j[j.room == "CLASS_01"]; rng = np.random.default_rng(7)
    ax.scatter(g1.occ_med + rng.uniform(-.2, .2, len(g1)), g1.co2, s=5 * k * k, color=CO2, alpha=.18, edgecolors="none", rasterized=True)
    sl, ic = S["occ"]["CLASS_01"]["slope"], S["occ"]["CLASS_01"]["icpt"]
    xs = np.array([0, g1.occ_med.max()]); ax.plot(xs, ic + sl * xs, color=INK, lw=1.6 * k)
    ax.text(xs[1], ic + sl * xs[1] + 150, f"탐지 1명당 +{sl:.0f} ppm", ha="right", va="bottom", fontweight="bold")
    ax.set_xlabel("탐지 재실 인원 (명) — 1반"); ax.set_ylabel("CO₂ (ppm)"); ax.set_xticks(range(0, int(g1.occ_med.max()) + 1)); ax.set_ylim(350, 5400)

def _rates(ax, k):
    rooms = ["CLASS_01", "CLASS_02", "CLASS_03", "CLASS_05"]
    v = [S["rates"][x][0] for x in rooms]; e = [S["rates"][x][1] * 1.96 for x in rooms]
    ax.bar(range(4), v, yerr=e, width=.58, color=CO2, ecolor=INK, capsize=2.5 * k, error_kw={"lw": .9 * k})
    ax.set_xticks(range(4), [KR[x] for x in rooms]); ax.set_ylabel("탐지 1명당 상승률 (ppm/분)"); ax.set_ylim(0, 10)

def occ(w, h, base, title, out, single=False):
    if single:
        fig, ax, k = new(w, h, base, title, "재실 인원이 늘면 CO₂도 높다"); _scatter(ax, k)
    else:
        fig, axes, k = new(w, h, base, title, "재실 인원과 CO₂ — 사람이 늘면 높아지고, 더 빨리 오른다 (ρ 0.31–0.58)", ncols=2, width_ratios=[1.25, 1])
        _scatter(axes[0], k); _rates(axes[1], k)
    save(fig, out)

# ---------------- 5. 레짐 지도 ----------------
def regime(w, h, base, title, out):
    fig, ax, k = new(w, h, base, title, "CO₂–VOC 평면 — 교실 공기는 4개의 레짐으로 갈린다" if base < 12 else "공기는 4개의 레짐으로 갈린다")
    lo, hi = -1.6, 3.2
    for (x0, x1, y0, y1, c) in [(lo, .5, lo, .5, MINT), (.5, hi, lo, .5, CO2), (lo, .5, .5, hi, VOC), (.5, hi, .5, hi, MIX)]:
        ax.fill_between([x0, x1], y0, y1, color=c, alpha=.10, lw=0)
    cm = LinearSegmentedColormap.from_list("ink", ["#dfe5ea", "#8fa0ae", INK])
    ax.hexbin(rec.zc, rec.zv, gridsize=42, cmap=cm, mincnt=3, bins="log", linewidths=0, extent=(lo, hi, lo, hi))
    ax.axvline(.5, color=INK, lw=.8 * k, ls=(0, (4, 3))); ax.axhline(.5, color=INK, lw=.8 * k, ls=(0, (4, 3)))
    sh = {a: int(b + .5) for a, b in S["regime_share"].items()}; kw = dict(fontweight="bold", ha="center", va="center")
    big = base >= 12
    ax.text(-.9, -1.3, f"청정 {sh['청정']}%", color="#12775a", **kw); ax.text(2.0, -1.3, f"인체 {sh['인체']}%" + ("" if big else " → 환풍기"), color=CO2, **kw)
    ax.text(-.75 if big else -.6, 2.85, f"물질 {sh['물질']}%" + ("" if big else " → 공기청정기"), color="#a85716", **kw); ax.text(2.25, 2.85, f"복합 {sh['복합']}%" + ("" if big else " → 둘 다"), color=MIX, **kw)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi); ax.grid(False)
    ax.set_xlabel("CO₂ (표준화) — 사람 →"); ax.set_ylabel("VOC (표준화) — 물질 →" if base < 12 else "VOC — 물질 →")
    ax.set_xticks([-1, 0, 1, 2, 3]); ax.set_yticks([-1, 0, 1, 2, 3])
    save(fig, out)

# ---------------- 6. 환기 감쇠 ----------------
def _decay_case(ax, k):
    e = ev[(ev.room == "CLASS_01") & (ev["drop"] > 800) & (ev.tau_min < 60)].sort_values("drop", ascending=False).iloc[0]
    g = r[r.room == "CLASS_01"].set_index("ts").sort_index()
    seg = g.loc[e.start - pd.Timedelta("30min"): e.start + pd.Timedelta("120min")]
    ax.plot(seg.index, seg.co2, color=CO2, marker="o", ms=2.2 * k, label="CO₂ 측정값")
    t = np.arange(0, int(e.dur_min) + 1, 5.0); idx = seg.loc[e.start:].index[:len(t)]
    ax.plot(idx, (e.co2_0 - 420) * np.exp(-t[:len(idx)] / e.tau_min) + 420, color=INK, ls=(0, (4, 2)), lw=1.6 * k, label=f"지수 감쇠 적합 (τ = {e.tau_min:.0f}분)")
    ax.set_ylabel("CO₂ (ppm)"); ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30]))
    ax.set_xlabel(f"시각 — 1반, {e.start.month}월 {e.start.day}일 환기"); ax.legend(loc="upper right")

def _decay_rooms(ax, k):
    b = S["decay"]["by_room"]; v = [b[x] for x in sorted(b)]
    ax.bar(range(8), v, width=.62, color=NEUTRAL)
    for xi, vi in enumerate(v): ax.text(xi, vi + 1.2, f"{vi:.0f}", ha="center", va="bottom")
    m = S["decay"]["tau_med"]; ax.axhline(m, color=MINT, lw=1.2 * k); ax.text(-.45, 74, f"━ 전체 중앙값 {m:.0f}분", color="#12775a", fontweight="bold", va="top")
    ax.set_xticks(range(8), [KR[x] for x in sorted(b)]); ax.set_ylabel("회복 시정수 τ (분)"); ax.set_ylim(0, 78)

def decay(w, h, base, title, out):
    fig, axes, k = new(w, h, base, title, "환기의 효과 — CO₂는 지수적으로 줄어든다 (520건, τ 중앙값 42분)", ncols=2, width_ratios=[1.15, 1])
    _decay_case(axes[0], k); _decay_rooms(axes[1], k); save(fig, out)

def exceed_decay(w, h, base, title, out):          # 포스터 넓은 칸용
    fig, axes, k = new(w, h, base, title, "수업시간의 31–45%가 기준 초과  ·  환기하면 지수적으로 줄어든다 (τ 중앙값 42분)", ncols=2, width_ratios=[1, 1.1])
    exceed(0, 0, base, title, ax=axes[0], k=k); _decay_case(axes[1], k); save(fig, out)

if __name__ == "__main__":
    R = HERE + "/../report2/figs"; P = HERE + "/../report2/pfigs"; os.makedirs(R, exist_ok=True); os.makedirs(P, exist_ok=True)
    W = 159                                    # 보고서: 본문 폭 159mm, 제목 10pt / 글자 9pt
    day(W, 72, 9, 10, R + "/r_day.png"); hourly(W, 66, 9, 10, R + "/r_hourly.png"); exceed(W, 60, 9, 10, R + "/r_exceed.png")
    occ(W, 70, 9, 10, R + "/r_occ.png"); regime(120, 104, 9, 10, R + "/r_regime.png"); decay(W, 68, 9, 10, R + "/r_decay.png")
    CW, CH = 143, 85                           # 포스터 그림 칸(148×88mm) 안쪽, 제목 20pt / 글자 16pt
    day(CW, CH, 16, 20, P + "/p_day.png"); hourly(CW, CH, 16, 20, P + "/p_hourly.png")
    occ(CW, CH, 16, 20, P + "/p_occ.png", single=True); regime(CW, CH, 16, 20, P + "/p_regime.png")
    exceed_decay(288, 84, 16, 20, P + "/p_exceed_decay.png")
