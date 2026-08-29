"""aq.plots tables that page 2 renders from action / occ_co2 payloads, and the
label-slot spreading of the fixed-scale plane."""

from aq import plots

LABELS = {"env_01": "CLASS_01", "env_02": "CLASS_02"}
RUN = "2026-08-29 06:05:15"


def _act(device, state, rule, value, since="2026-08-29 05:05:00", hold="2026-08-29 05:15:00"):
    var = "co2" if device == "fan" else "voc"
    return {"device": device, "state": state, "rule": rule,
            "values": {"regime": "human" if rule != "hold" else "hold", var: value},
            "since": since, "hold_until": hold}


def test_action_summary_words():
    fan_on = _act("fan", 1, "co2 > 1000 in human/mixed", 1180.0)
    pur_off = _act("purifier", 0, "voc < 120", 85.0)
    a = plots.action_summary({"fan": fan_on, "purifier": pur_off})
    assert a["word"] == plots.ACTION_WORDS["fan"] and not a["kept"]
    assert a["reason"].startswith("레짐 인체 · 환풍기 co2 > 1000") and "(voc 85)" in a["reason"]
    assert a["since"] == fan_on["since"] and a["hold_until"] == fan_on["hold_until"]

    pur_on = _act("purifier", 1, "voc > 200 in matter/mixed", 240.0)
    both = plots.action_summary({"fan": fan_on, "purifier": pur_on})
    assert both["word"] == plots.ACTION_WORDS["both"]

    none = plots.action_summary({"fan": _act("fan", 0, "co2 < 700", 520.0), "purifier": pur_off})
    assert none["word"] == plots.ACTION_WORDS["none"]

    kept = plots.action_summary({"fan": _act("fan", 1, "keep (hysteresis band)", 850.0),
                                 "purifier": pur_off})
    assert kept["word"] == plots.ACTION_WORDS["fan"] + plots.ACTION_WORDS["keep"] and kept["kept"]
    min_run = plots.action_summary({"fan": _act("fan", 1, "min_run 10 min (wanted 0)", 650.0),
                                    "purifier": pur_off})
    assert min_run["word"].endswith(plots.ACTION_WORDS["keep"])

    hold = plots.action_summary({"fan": _act("fan", 1, "hold", None),
                                 "purifier": _act("purifier", 0, "hold", None)})
    assert hold["word"] == plots.ACTION_WORDS["hold"] and "레짐" not in hold["reason"]
    assert plots.action_summary({})["word"] == "—"


def test_actions_table_one_row_per_room_and_hold_until():
    actions = {"env_01": {"fan": _act("fan", 1, "co2 > 1000 in human/mixed", 1180.0,
                                      since="2026-08-29 06:05:15", hold="2026-08-29 06:15:15"),
                          "purifier": _act("purifier", 0, "voc < 120", 85.0)},
               "env_02": {"fan": _act("fan", 0, "co2 < 700", 520.0),
                          "purifier": _act("purifier", 0, "voc < 120", 60.0)}}
    df = plots.actions_table(actions, LABELS, RUN)
    assert list(df.columns) == ["교실", "행동", "근거", "판정 시각", "유지"]
    assert len(df) == 2 and list(df["교실"]) == ["CLASS_01", "CLASS_02"]
    r1, r2 = df.iloc[0], df.iloc[1]
    assert r1["행동"] == plots.ACTION_WORDS["fan"] and r1["판정 시각"] == "08-29 15:05"
    assert r1["유지"] == "~15:15"                       # hold_until after run_at -> binding
    assert r2["행동"] == plots.ACTION_WORDS["none"] and r2["유지"] == "—"


def test_regime_table_has_action_column():
    regime_now = {"env_01": {"regime": "human", "co2": 1180.0, "voc": 85.0, "dwell_min": 40,
                             "dwell_censored": True}}
    actions = {"env_01": {"fan": _act("fan", 1, "co2 > 1000 in human/mixed", 1180.0),
                          "purifier": _act("purifier", 0, "voc < 120", 85.0)}}
    df = plots.regime_table(regime_now, actions, LABELS)
    assert "행동" in df.columns and "환풍기" not in df.columns
    assert df.iloc[0]["행동"] == plots.ACTION_WORDS["fan"] and df.iloc[0]["체류(min)"] == "≥40"


def test_occ_table_last_bucket_and_stopped():
    payload = {"by_room": {
        "CLASS_01": {"rho": 0.5, "n": 300, "slope": 12.34, "last_bucket": "2026-08-28 21:55:00"},
        "CLASS_02": {"rho": None, "n": 0, "slope": None, "last_bucket": "2026-08-14 22:00:00"},
        "CLASS_03": {"rho": None, "n": 0, "slope": None, "last_bucket": None}}}
    df = plots.occ_table(payload, LABELS, win_start="2026-08-22 06:00:17")
    col = "마지막 비전 버킷 (KST)"
    assert list(df[col]) == ["08-29 06:55", "08-15 07:00 · 중단", "—"]
    assert df.iloc[0]["기울기 (ppm/인)"] == 12.3 and df.iloc[1]["조인 행"] == 0


def test_label_positions_spread_close_points():
    pts = [(0.20, 0.30), (0.21, 0.31), (0.22, 0.29), (0.80, 0.80)]
    pos = plots.label_positions(pts)
    assert len(set(pos[:3])) == 3                       # three neighbours, three slots
    assert pos[3] == plots.LABEL_SLOTS[0]               # isolated point keeps the default
    assert plots.label_positions([]) == []
