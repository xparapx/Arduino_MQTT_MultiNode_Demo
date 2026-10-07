"""band_slots: NaN만 있는 슬롯이 daily run 전체를 죽이던 회귀(2026-10-05~06 보드 저널 IndexError)."""
import math
import pandas as pd
import analyst


def test_band_slots_nan_only_slot_is_null():
    cfg = {"run": {"band_slot_minutes": 30}}
    buckets = pd.Series(pd.to_datetime(["2026-10-06 08:00", "2026-10-06 08:05", "2026-10-06 08:40", "2026-10-06 08:45"]))
    sm = pd.Series([math.nan, None, "clean", "clean"])
    out = analyst.band_slots(sm, buckets, cfg)
    assert [o["regime"] for o in out] == [None, "clean"]
