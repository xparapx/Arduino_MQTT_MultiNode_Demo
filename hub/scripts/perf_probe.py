"""Server-side cost of one dashboard.py cycle (Phase 1b before/after table).

Runs dashboard.py in Streamlit *bare mode* (no server, widgets return their
defaults) against the DB in ``--dir`` and reports, per step:
  - seconds spent (loaders are timed uncached, i.e. the real cost of a cache miss)
  - payload bytes the step would push to the browser (figure JSON / CSV bytes)

    .venv/bin/python scripts/perf_probe.py            # board: ~/multinode_aq/hub
    uv run python scripts/perf_probe.py --dir <copy>  # PC: dir with sensor_data.db + nodes.json

Read-only: opens the DB, never writes. Prints a markdown table (and JSON with --json).
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import runpy
import sys
from pathlib import Path
from time import perf_counter

# also runnable from stdin on the board:
#   ssh q 'cd ~/multinode_aq/hub && .venv/bin/python -' < scripts/perf_probe.py
_f = globals().get("__file__", "<stdin>")
HUB = Path.cwd() if _f.startswith("<") else Path(_f).resolve().parent.parent


def kb(n: int) -> str:
    return f"{n / 1024:,.0f}"


def fig_bytes(fig) -> int:
    return len(fig.to_json().encode())


def csv_bytes(df) -> int:
    return len(df.to_csv(index=False).encode("utf-8-sig")) if df is not None and not df.empty else 0


def uncached(f):
    """Underlying function of an @st.cache_data wrapper (or f itself)."""
    return getattr(f, "__wrapped__", f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(HUB), help="dir holding sensor_data.db + nodes.json")
    ap.add_argument("--json", action="store_true", help="also print a JSON summary")
    a = ap.parse_args()
    os.chdir(a.dir)
    sys.path.insert(0, str(HUB))
    logging.getLogger("streamlit").setLevel(logging.ERROR)  # hide bare-mode warnings

    rows: list[tuple[str, float, int]] = []

    def T(name, fn, size=None):
        t = perf_counter()
        r = fn()
        dt = perf_counter() - t
        rows.append((name, dt, size(r) if size else 0))
        return r

    # 1) whole-script runs: cold (caches empty) then warm (caches primed)
    t = perf_counter()
    ns = runpy.run_path(str(HUB / "dashboard.py"), run_name="dashboard")
    cold = perf_counter() - t
    t = perf_counter()
    runpy.run_path(str(HUB / "dashboard.py"), run_name="dashboard")
    warm = perf_counter() - t

    d = type("NS", (), ns)  # attribute access over the script namespace
    labels = d.load_node_labels()

    # 2) loaders, uncached. New API (Phase 1b): data_version() -> (max_id, bucket)
    new_api = hasattr(d, "data_version")
    if new_api:
        max_id, bucket = T("data_version", lambda: d.data_version())
        df = T("load_df(5000)", lambda: uncached(d.load_df)(max_id))
    else:
        df = T("load_df(5000)", lambda: uncached(d.load_df)())
    nodes = sorted(df["node"].dropna().unique(), key=d._node_sort_key)
    latest = {n: df[df["node"] == n].iloc[-1].to_dict() for n in nodes}
    sel = nodes[0]
    if new_api:
        dfa = T("load_all_for_stats", lambda: uncached(d.load_all_for_stats)(bucket))
    else:
        dfa = T("load_all_for_stats", lambda: uncached(d.load_all_for_stats)())
    rows.append(("  rows in dfa", 0.0, len(dfa)))

    # 3) section 1: radars
    T(f"sec1 radar x{len(nodes)}",
      lambda: [d.make_node_radar(latest[n], n) for n in nodes],
      lambda figs: sum(fig_bytes(f) for f in figs))

    # 4) section 2 figures (old API: builders take dfa; new API: stats_figures(max_id))
    if new_api:
        figs = T("sec2 stats_figures (uncached)",
                 lambda: uncached(d.stats_figures)(bucket),
                 lambda fs: sum(fig_bytes(f) for k, f in fs.items() if k != "regime_meta"))
        T("sec2 stats_figures (cached hit)", lambda: d.stats_figures(bucket))
        T("sec2 overlay ★ on regime",
          lambda: d.overlay_current(copy.deepcopy(figs["regime"]), figs["regime_meta"],
                                    latest, labels),
          fig_bytes)
    else:
        T("sec2 boxplots", lambda: d.make_boxplots(dfa), fig_bytes)
        T("sec2 corr", lambda: d.make_corr(dfa), fig_bytes)
        T("sec2 bar co2+voc",
          lambda: [d.make_target_by_node(dfa, labels, k) for k in ("co2", "voc")],
          lambda figs: sum(fig_bytes(f) for f in figs))
        T("sec2 regime scatter", lambda: d.make_regime_scatter(dfa, labels, latest), fig_bytes)

    # 5) section 3
    dfn = df[df["node"] == sel].tail(60)
    T("sec3 timeseries", lambda: d.make_timeseries(dfn), fig_bytes)
    if new_api:
        T("sec3 node regime (uncached)",
          lambda: uncached(d.node_regime_figure)(bucket, sel)[0], fig_bytes)
    else:
        T("sec3 node regime", lambda: d.make_node_regime_scatter(dfa, sel, labels, latest),
          fig_bytes)
    T("sec3 occ latest+hist",
      lambda: (uncached(d.load_occ_latest)(), None))

    # 6) section 5: what the export section pushes every cycle (old code) or
    #    nothing until a button is pressed (new code)
    if hasattr(d, "EXPORT_ON_DEMAND"):
        rows.append(("sec5 export (on demand)", 0.0, 0))
    else:
        T("sec5 load_df(all)+csv", lambda: uncached(d.load_df)(10_000_000), csv_bytes)
        T("sec5 merged+csv", lambda: uncached(d.load_merged_analysis)(), csv_bytes)
        T("sec5 occ_all+csv", lambda: d.load_occ_all(), csv_bytes)
        lo, hi = d.get_time_bounds()
        T("sec5 query_range(all)+csv", lambda: d.query_range(lo, hi), csv_bytes)

    total_s = sum(r[1] for r in rows)
    total_b = sum(r[2] for r in rows if not r[0].startswith("  "))
    print("| step | s | payload KB |\n|---|---:|---:|")
    print(f"| full script, cold caches | {cold:.2f} | |")
    print(f"| full script, warm caches | {warm:.2f} | |")
    for name, dt, size in rows:
        print(f"| {name} | {dt:.3f} | {kb(size) if size else ''} |")
    print(f"| **sum of steps** | **{total_s:.2f}** | **{kb(total_b)}** |")
    if a.json:
        print(json.dumps({"cold": cold, "warm": warm,
                          "steps": [{"name": n, "s": s, "bytes": b} for n, s, b in rows]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
