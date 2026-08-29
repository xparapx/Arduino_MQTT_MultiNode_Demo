"""aq.qc: range rules -> NaN (fixture's abnormal rows included), daily gate with the
95 % boundary inclusive, silent nodes fail, rows are never dropped by range_mask."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from aq import config, db, qc


@pytest.fixture(scope="module")
def cfg():
    return config.load()


def test_range_mask_rules(cfg):
    df = pd.DataFrame({
        "node": ["a"] * 6, "bucket": ["2026-08-29 00:00:00"] * 6,
        "co2": [349, 350, 5000, 5001, 0, np.nan],
        "temp": [-11, -10, 50, 51, 20, 20],
        "hum": [-1, 0, 100, 101, 50, 50],
        "voc": [0, 1, 500, 501, 100, 100],
        "pm2p5": [-1, 0, 999.9, 1000, 5, 5],
    })
    out = qc.range_mask(df, cfg)
    assert len(out) == len(df)                       # never drops rows
    assert out["co2"].isna().tolist() == [True, False, False, True, True, True]
    assert out["temp"].isna().tolist() == [True, False, False, True, False, False]
    assert out["hum"].isna().tolist() == [True, False, False, True, False, False]
    assert out["voc"].isna().tolist() == [True, False, False, True, False, False]
    assert out["pm2p5"].isna().tolist() == [True, False, False, True, False, False]  # 1000 excl.
    assert df["co2"].iloc[4] == 0                    # input untouched (copy)


def test_fixture_abnormal_rows_become_nan(fixture_path, cfg):
    conn = db.connect_ro(fixture_path)
    raw = db.load_readings(conn, "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    conn.close()
    bad = raw[(raw["co2"] <= 0) | (raw["temp"] < -50)]
    assert len(bad) > 0, "fixture must contain out-of-range rows"
    masked = qc.range_mask(raw, cfg)
    assert masked.loc[bad.index, "co2"].isna().all() or masked.loc[bad.index, "temp"].isna().all()
    assert masked["co2"].notna().sum() < raw["co2"].notna().sum()


def _day(node, n_valid, n_bad, day="2026-08-28"):
    n = n_valid + n_bad
    return pd.DataFrame({"node": [node] * n,
                         "bucket": [f"{day} {i // 12:02d}:{(i % 12) * 5:02d}:00" for i in range(n)],
                         "co2": [600.0] * n_valid + [np.nan] * n_bad,
                         "voc": [100.0] * n})


def test_daily_gate_boundary_and_failure(cfg):
    # 95.0 % exactly passes (inclusive); 94.9 % fails
    ok = _day("env_ok", 95, 5)                      # 95 / 100 (100 rows stay inside one KST day)
    bad = _day("env_bad", 94, 6)                    # 94.0 %
    gate = qc.daily_gate(pd.concat([ok, bad]), cfg)
    assert len(gate) == 2
    g = gate.set_index("node")
    assert g.loc["env_ok", "passed"] and g.loc["env_ok", "valid_co2_pct"] == 95.0
    assert not g.loc["env_bad", "passed"] and "94.0%" in g.loc["env_bad", "reason"]
    assert gate["date"].iloc[0] == date(2026, 8, 28)  # 00:00 UTC bucket -> 09:00 KST same day


def test_daily_gate_kst_day_and_silent_node(cfg):
    late = _day("env_01", 10, 0, day="2026-08-28").assign(
        bucket=[f"2026-08-28 {15 + i // 12:02d}:{(i % 12) * 5:02d}:00" for i in range(10)])
    gate = qc.daily_gate(late, cfg, nodes=["env_01", "env_down"], days=[date(2026, 8, 29)])
    # 15:xx UTC on 08-28 is 00:xx KST on 08-29
    assert gate[gate["node"] == "env_01"]["date"].tolist() == [date(2026, 8, 29)]
    down = gate[gate["node"] == "env_down"].iloc[0]
    assert down["rows"] == 0 and not down["passed"] and down["reason"] == "no rows"


def test_fixture_has_a_gated_out_node_day(fixture_path, cfg):
    conn = db.connect_ro(fixture_path)
    raw = db.load_readings(conn, "2000-01-01 00:00:00", "2100-01-01 00:00:00")
    conn.close()
    gate = qc.daily_gate(qc.range_mask(raw, cfg), cfg)
    assert (~gate["passed"]).any(), "expected at least one node-day below 95 % valid CO2"
    kept = qc.apply_gate(raw, gate, cfg)
    assert 0 < len(kept) < len(raw)


def test_gate_payload_shape(cfg):
    gate = qc.daily_gate(_day("n", 100, 0), cfg)
    p = qc.gate_payload(gate, "n", date(2026, 8, 28))
    assert p == {"valid_co2_pct": 100.0, "valid_voc_pct": 100.0, "rows": 100, "passed": True,
                 "reason": ""}
    assert qc.gate_payload(gate, "n", date(2026, 1, 1))["reason"] == "no rows"
