# -*- coding: utf-8 -*-
"""보드 스냅샷 DB → 9월 확정 분석과 동일한 정의로 전처리·통계 재현 (창: 2026-07-07 ~ 09-19, 73일).
   정의 출처: 9월 분석 스크립트(make_figs.py, 감쇠 사건 검출) — 세션 기록에서 복구."""
import sqlite3, json, io, sys, os
import numpy as np, pandas as pd
from scipy import stats, optimize
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOMS = {"node_D0C12C": "CLASS_01", "node_4C22A7": "CLASS_02", "node_5040F0": "CLASS_03", "node_8C8B35": "CLASS_04",
         "node_E84DF0": "CLASS_05", "node_E04537": "CLASS_06", "node_3093F0": "CLASS_07", "node_B80DC8": "CLASS_08"}
OCC = {"node_44F2FB": "CLASS_01", "node_E29568": "CLASS_02", "node_E647F1": "CLASS_03", "node_E1B3AA": "CLASS_05"}
N_RAW_SEP = 157744            # 9월 보고서의 원시 측정 건수 — 같은 시점까지만 사용

db = sqlite3.connect(HERE + "/aq_snapshot.db")
raw = pd.read_sql("select id, ts, node, pm2p5, voc, co2 from readings order by id", db)
print("snapshot rows", len(raw), raw.ts.min(), "->", raw.ts.max())
cut = raw.iloc[:N_RAW_SEP]
print("cutoff (row %d):" % N_RAW_SEP, cut.ts.max(), "UTC")
r = cut[cut.node.isin(ROOMS)].copy(); r["room"] = r.node.map(ROOMS)
r["ts"] = pd.to_datetime(r.ts) + pd.Timedelta(hours=9)
r = r[(r.co2 > 350) & (r.co2 < 6000)].sort_values("ts")
o = pd.read_sql("select ts, node, occ_med from occupancy order by ts", db)
o = o[o.node.isin(OCC)].copy(); o["room"] = o.node.map(OCC)
o["ts"] = pd.to_datetime(o.ts) + pd.Timedelta(hours=9)
o["bucket"] = o.ts.dt.floor("5min"); r["bucket"] = r.ts.dt.floor("5min")
r["hour"] = r.ts.dt.hour; r["wd"] = r.ts.dt.weekday < 5
S = {"rows_raw": int(len(cut)), "rows_used": int(len(r)), "occ_rows": int(len(pd.read_sql("select 1 from occupancy", db))),
     "first": str(r.ts.min()), "last": str(r.ts.max())}

# 표: 주중 08–16시
sch = r[(r.wd) & (r.hour.between(8, 16))]
tbl = sch.groupby("room").agg(n=("co2", "size"), mean=("co2", "mean"), p95=("co2", lambda s: s.quantile(.95)), mx=("co2", "max"),
                              over1000=("co2", lambda s: (s > 1000).mean() * 100), over1500=("co2", lambda s: (s > 1500).mean() * 100)).round(1)
S["table"] = tbl.reset_index().to_dict("records")
try:      # 9월 확정 표와의 차이 확인(파일이 있을 때만)
    old = pd.read_csv(os.environ.get("AQ_OLD_TABLE") or (HERE + "/table_room_stats_sep.csv")).set_index("room")
    print("\n표 재현 검증 (새 값 − 9월 값):\n", (tbl[["over1000", "over1500", "mean"]] - old[["over1000", "over1500", "mean"]]).round(2).T)
except Exception as e:
    print("9월 표 비교 생략:", e)

# 재실–CO2
j = pd.merge(o.groupby(["room", "bucket"]).occ_med.max().reset_index(), r[["room", "bucket", "co2"]], on=["room", "bucket"])
j = j[(j.bucket.dt.weekday < 5) & (j.bucket.dt.hour.between(8, 17))]
S["occ"] = {}
for room, g in j.groupby("room"):
    rho, p = stats.spearmanr(g.occ_med, g.co2); sl, ic, rr, pp, se = stats.linregress(g.occ_med, g.co2)
    S["occ"][room] = {"n": int(len(g)), "rho": round(float(rho), 2), "slope": round(float(sl), 1), "icpt": round(float(ic), 1), "r2": round(float(rr ** 2), 3)}
rates = {}
for room in OCC.values():
    gg = r[r.room == room].set_index("bucket").sort_index()
    occ = o[o.room == room].groupby("bucket").occ_med.max()
    gg = gg.join(occ, how="inner"); gg["dco2"] = gg.co2.diff(); gg["dtm"] = gg.index.to_series().diff().dt.total_seconds() / 60
    gg = gg[(gg.dtm == 5) & gg.dco2.notna() & (gg.index.hour >= 8) & (gg.index.hour <= 17) & (gg.index.weekday < 5)]
    sl2, ic2, rr2, pp2, se2 = stats.linregress(gg.occ_med, gg.dco2 / gg.dtm)
    rates[room] = (round(float(sl2), 2), round(float(se2), 2))
S["rates"] = rates

# 레짐 (최근 30일)
rec = r[r.ts > r.ts.max() - pd.Timedelta(days=30)].copy()
iqr_c = rec.co2.quantile(.75) - rec.co2.quantile(.25); iqr_v = rec.voc.quantile(.75) - rec.voc.quantile(.25)
rec["zc"] = (rec.co2 - rec.co2.median()) / iqr_c; rec["zv"] = (rec.voc - rec.voc.median()) / iqr_v
rec = rec[(rec.zc.abs() < 3) & (rec.zv.abs() < 3)]
hc = rec.zc > 0.5; hv = rec.zv > 0.5
rec["regime"] = np.select([hc & hv, hc, hv], ["복합", "인체", "물질"], default="청정")
S["regime_share"] = (rec.regime.value_counts(normalize=True) * 100).round(1).to_dict()

# 감쇠 사건
ev = []
for room, g in r.groupby("room"):
    g = g.set_index("ts").sort_index().co2.resample("5min").mean().interpolate(limit=2)
    i = 0; vals = g.values; idx = g.index
    while i < len(g) - 6:
        if vals[i] > 1100 and all(np.diff(vals[i:i + 7]) < 0):
            k = i
            while k < len(g) - 1 and vals[k + 1] < vals[k]: k += 1
            drop = vals[i] - vals[k]; dur = (k - i) * 5
            if drop > 300 and dur >= 30:
                t = np.arange(k - i + 1) * 5.0; y = vals[i:k + 1]
                try:
                    popt, _ = optimize.curve_fit(lambda t, A, tau: A * np.exp(-t / tau) + 420, t, y, p0=[y[0] - 420, 30], maxfev=5000)
                    ev.append((room, idx[i], vals[i], drop, dur, popt[1]))
                except Exception: pass
            i = k + 1
        else: i += 1
ev = pd.DataFrame(ev, columns=["room", "start", "co2_0", "drop", "dur_min", "tau_min"]); ev = ev[(ev.tau_min > 3) & (ev.tau_min < 300)]
S["decay"] = {"n": int(len(ev)), "tau_med": round(float(ev.tau_min.median()), 1), "q1": round(float(ev.tau_min.quantile(.25)), 1), "q3": round(float(ev.tau_min.quantile(.75)), 1),
              "by_room": ev.groupby("room").tau_min.median().round(1).to_dict()}

r.to_pickle(HERE + "/r.pkl"); o.to_pickle(HERE + "/o.pkl"); ev.to_pickle(HERE + "/ev.pkl"); rec.to_pickle(HERE + "/rec.pkl"); j.to_pickle(HERE + "/j.pkl")
json.dump(S, open(HERE + "/stats.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in S.items() if k != "table"}, ensure_ascii=False, indent=1, default=str))
