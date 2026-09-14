"""자동 제어 계획(aq.autoctl): actuator_state 읽기 + 순수 reconcile plan."""
import json
import sqlite3
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

from aq import autoctl, db  # noqa: E402


def _dev(online=True, output=False, mac="aabbccddeeff"):
    return {"mac": mac, "online": online, "output": output, "apower": 0.0}


def test_plan_only_acts_on_real_differences():
    desired = {"CLASS_01": {"purifier": 1, "fan": 0}}
    plugs = {"CLASS_01": {"purifier": _dev(output=False), "fan": None}}
    assert autoctl.plan(desired, plugs, "auto") == [
        ("CLASS_01", "purifier", "aabbccddeeff", "on")]
    plugs["CLASS_01"]["purifier"]["output"] = True          # already matches
    assert autoctl.plan(desired, plugs, "auto") == []
    desired["CLASS_01"]["purifier"] = 0                     # judged off -> turn off
    assert autoctl.plan(desired, plugs, "auto") == [
        ("CLASS_01", "purifier", "aabbccddeeff", "off")]


def test_plan_guards():
    desired = {"CLASS_01": {"purifier": 1}}
    on = {"CLASS_01": {"purifier": _dev(output=False)}}
    assert autoctl.plan(desired, on, "manual") == []                       # 수동 모드 무동작
    off = {"CLASS_01": {"purifier": _dev(online=False, output=False)}}
    assert autoctl.plan(desired, off, "auto") == []                        # 미접속 플러그 제외
    unknown = {"CLASS_01": {"purifier": _dev(output=None)}}
    assert autoctl.plan(desired, unknown, "auto") == []                    # 릴레이 상태 미확인
    assert autoctl.plan({}, on, "auto") == []                              # 판정 없으면 무동작
    assert autoctl.plan({"CLASS_02": {"purifier": 1}}, on, "auto") == []   # 다른 교실 판정


def test_desired_states_reads_actuator_state(tmp_path):
    dbp = tmp_path / "sensor_data.db"
    con = sqlite3.connect(dbp)
    db.ensure_schema(con)
    con.executemany("INSERT INTO actuator_state(node, device, state, since) VALUES(?,?,?,?)",
                    [("env_01", "purifier", 1, "2026-09-14 00:00:00"),
                     ("env_01", "fan", 0, "2026-09-14 00:00:00"),
                     ("env_99", "purifier", 1, "2026-09-14 00:00:00")])   # 라벨 없는 노드
    con.commit()
    con.close()
    nodes = tmp_path / "nodes.json"
    nodes.write_text(json.dumps({"env_01": "CLASS_01"}), encoding="utf-8")
    d = autoctl.desired_states(str(dbp), str(nodes))
    assert d == {"CLASS_01": {"purifier": 1, "fan": 0}}
    assert autoctl.desired_states(str(tmp_path / "none.db"), str(nodes)) == {}
