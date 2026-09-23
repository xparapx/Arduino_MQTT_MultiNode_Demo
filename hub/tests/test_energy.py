"""aq.energy — 일별 에너지 적산 순수 함수."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aq import energy  # noqa: E402

B = energy.BUCKET_S


def test_accumulate_finalized_only():
    now_b = 1_789_770_000 // B * B
    hist = [[now_b - 2 * B, 60.0, 1], [now_b - B, 120.0, 2], [now_b, 999.0, 1]]
    adds, marker = energy.accumulate(hist, 0, now_b)
    # 진행 중 버킷(now_b)은 제외, 확정 2개만: 60W*5분 + 60W*5분 = 각 5 Wh
    assert marker == now_b - B
    assert sum(adds.values()) == 10.0


def test_accumulate_marker_prevents_double_count():
    now_b = 1_789_770_000 // B * B
    hist = [[now_b - 2 * B, 60.0, 1], [now_b - B, 60.0, 1]]
    adds1, m1 = energy.accumulate(hist, 0, now_b)
    adds2, m2 = energy.accumulate(hist, m1, now_b)
    assert sum(adds1.values()) == 10.0 and adds2 == {} and m2 == m1


def test_accumulate_kst_date_split():
    # KST 자정(= UTC 15:00) 직전/직후 버킷은 서로 다른 날짜로 적산
    utc_midnight_kst = 1_789_743_600 // 86400 * 86400 + 15 * 3600
    hist = [[utc_midnight_kst - B, 120.0, 1], [utc_midnight_kst, 120.0, 1]]
    adds, _ = energy.accumulate(hist, 0, utc_midnight_kst + B)
    assert len(adds) == 2 and all(v == 10.0 for v in adds.values())
    d1, d2 = sorted(adds)
    assert energy.kst_date(utc_midnight_kst - B) == d1
    assert energy.kst_date(utc_midnight_kst) == d2


def test_merge_and_prune():
    doc = {}
    energy.merge(doc, "CLASS_01", "fan", {"2026-09-23": 5.0}, 100)
    energy.merge(doc, "CLASS_01", "fan", {"2026-09-23": 2.5}, 200)
    assert doc["days"]["2026-09-23"]["CLASS_01"]["fan"] == 7.5
    assert doc["acc"]["CLASS_01"]["fan"] == 200
    for i in range(1, 250):
        doc["days"][f"2025-01-{i:03d}"] = {}
    energy.prune(doc, keep=10)
    assert len(doc["days"]) == 10 and "2026-09-23" in doc["days"]
