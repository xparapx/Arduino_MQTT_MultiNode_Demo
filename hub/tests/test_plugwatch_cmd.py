"""plug_cmd.json 실행 가드 — 오래된 명령은 발행하지 않고 폐기(2026-10-07 재기동 시 6일 묵은 ALL ON 발행 사고)."""
import json
import os
import time
for _k in ("MQTT_BROKER", "MQTT_USERNAME", "MQTT_PASSWORD"):   # plugwatch는 import 시 broker 자격을 요구
    os.environ.setdefault(_k, "test")
import plugwatch  # noqa: E402


class _Client:
    def __init__(self): self.pub = []
    def publish(self, topic, payload, qos=0): self.pub.append((topic, payload))


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as f: json.dump(doc, f)


def test_stale_command_dropped(tmp_path, monkeypatch):
    cmd = tmp_path / "plug_cmd.json"
    monkeypatch.setattr(plugwatch, "CMD_PATH", str(cmd))
    monkeypatch.setattr(plugwatch, "MAC2LOC", {"aa": ("CLASS_01", "fan")})
    _write(cmd, {"action": "all", "on": True, "ts": int(time.time()) - 6 * 86400})
    c = _Client()
    assert plugwatch.run_command(c) is False
    assert c.pub == [] and not cmd.exists()


def test_fresh_command_executed(tmp_path, monkeypatch):
    cmd = tmp_path / "plug_cmd.json"
    monkeypatch.setattr(plugwatch, "CMD_PATH", str(cmd))
    monkeypatch.setattr(plugwatch, "MAC2LOC", {"aa": ("CLASS_01", "fan")})
    _write(cmd, {"action": "all", "on": False, "ts": int(time.time())})
    c = _Client()
    assert plugwatch.run_command(c) is True
    assert c.pub == [("shellyplugsg3-aa/command/switch:0", "off")] and not cmd.exists()
