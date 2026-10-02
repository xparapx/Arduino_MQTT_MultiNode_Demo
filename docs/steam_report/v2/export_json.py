# -*- coding: utf-8 -*-
"""pkl(분석 결과) → 차트용 compact JSON. HTML 차트 컴포넌트는 이 파일만 읽는다(pandas 불필요)."""
import os, sys, io, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.normpath(HERE + "/../../data")
r = pd.read_pickle(D + "/r.pkl"); o = pd.read_pickle(D + "/o.pkl"); ev = pd.read_pickle(D + "/ev.pkl")
rec = pd.read_pickle(D + "/rec.pkl"); j = pd.read_pickle(D + "/j.pkl"); S = json.load(open(D + "/stats.json", encoding="utf-8"))
out = {"stats": S}

# 1. 수업일 하루 (1반 9/15) — 5분 CO₂ + 탐지 인원
d = "2026-09-15"
g = r[r.room == "CLASS_01"].set_index("ts").sort_index().loc[d]
og = o[o.room == "CLASS_01"].set_index("ts").sort_index().loc[d].occ_med.resample("5min").max().fillna(0)
out["day"] = {"date": d, "room": "CLASS_01",
              "co2": [[t.strftime("%H:%M"), round(float(v), 1)] for t, v in zip(g.index, g.co2)],
              "occ": [[t.strftime("%H:%M"), float(v)] for t, v in zip(og.index, og.values)]}

# 2. 시간대별 분위수 (주중/주말)
hq = {}
for wd, lab in [(True, "weekday"), (False, "weekend")]:
    q = r[r.wd == wd].groupby("hour").co2.quantile([.25, .5, .75]).unstack()
    hq[lab] = [[int(h), round(float(q.loc[h, .25])), round(float(q.loc[h, .5])), round(float(q.loc[h, .75]))] for h in q.index]
out["hourly"] = hq

# 3. 재실–CO₂ 산점 (1반, 최대 2500점 샘플) + 회귀
g1 = j[j.room == "CLASS_01"]; rng = np.random.default_rng(7)
idx = rng.choice(len(g1), size=min(2500, len(g1)), replace=False)
out["occ_scatter"] = {"room": "CLASS_01", "n_total": int(len(g1)),
                      "points": [[float(a), round(float(b))] for a, b in zip(g1.occ_med.values[idx], g1.co2.values[idx])],
                      "slope": S["occ"]["CLASS_01"]["slope"], "icpt": S["occ"]["CLASS_01"]["icpt"], "rho": S["occ"]["CLASS_01"]["rho"],
                      "xmax": float(g1.occ_med.max())}
# 인원별 중앙값·IQR (박스 요약)
box = g1.groupby(g1.occ_med.round()).co2.describe(percentiles=[.25, .5, .75])
out["occ_box"] = [[int(k), int(v["count"]), round(float(v["25%"])), round(float(v["50%"])), round(float(v["75%"]))] for k, v in box.iterrows()]

# 4. 레짐 평면 — 2D 히스토그램 (48×48, 범위 -1.6~3.2)
lo, hi, n = -1.6, 3.2, 48
H, xe, ye = np.histogram2d(rec.zc.clip(lo, hi - 1e-9), rec.zv.clip(lo, hi - 1e-9), bins=n, range=[[lo, hi], [lo, hi]])
out["regime"] = {"lo": lo, "hi": hi, "n": n, "counts": H.astype(int).tolist(), "total": int(len(rec)),
                 "share": S["regime_share"], "threshold": 0.5}

# 5. 감쇠 — 대표 사건 + 교실별 τ
# 대표 사건: τ가 중앙값(42분)에 가깝고 실외 기준선 근처(≈560 ppm)까지 내려간 사례 — 4반 2026-09-14 14:20 (도메인 검토 반영)
e = ev[(ev.room == "CLASS_04") & (ev.start == pd.Timestamp("2026-09-14 14:20"))].iloc[0]
gg = r[r.room == e.room].set_index("ts").sort_index()
seg = gg.loc[e.start - pd.Timedelta("30min"): e.start + pd.Timedelta(minutes=int(e.dur_min) + 20)]
t = np.arange(0, int(e.dur_min) + 1, 5.0); fit_idx = seg.loc[e.start:].index[:len(t)]
out["decay_case"] = {"room": e.room, "start": e.start.strftime("%Y-%m-%d %H:%M"), "tau": round(float(e.tau_min), 1),
                     "co2_0": round(float(e.co2_0)), "baseline": 420,
                     "series": [[ts.strftime("%H:%M"), round(float(v))] for ts, v in zip(seg.index, seg.co2)],
                     "fit": [[ts.strftime("%H:%M"), round(float((e.co2_0 - 420) * np.exp(-tt / e.tau_min) + 420))] for ts, tt in zip(fit_idx, t)]}
out["decay_rooms"] = S["decay"]
out["tau_all"] = [round(float(x), 1) for x in ev.tau_min.values]

json.dump(out, open(HERE + "/data.json", "w", encoding="utf-8"), ensure_ascii=False)
print("data.json", os.path.getsize(HERE + "/data.json") // 1024, "KB; keys", list(out))
