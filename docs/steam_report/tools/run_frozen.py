# -*- coding: utf-8 -*-
"""픽스처 대시보드를 '고정된 현재 시각'으로 실행 — 포스터 캡처용 (수신 지연 표시 방지).
   frozen = 2026-08-28 05:36 UTC (금 14:36 KST, 수업시간) — 픽스처 DB 마지막 수신 직후.
   freezegun(tick)은 ThreadingHTTPServer와 스택오버플로 → webdata의 datetime과
   SQLite datetime('now', ...)만 교체(앱 정의 함수가 내장 함수를 덮어씀)."""
import sys, os, re, runpy, sqlite3
import datetime as _dt

HUB = os.environ.get("AQ_HUB") or os.path.abspath(os.path.join(os.path.expanduser("~"), "Projects", "Arduino_MQTT_MultiNode_Demo", "hub"))
EN = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HUB); os.chdir(HUB)

BASE = _dt.datetime(2026, 8, 28, 5, 36, 0, tzinfo=_dt.timezone.utc)
T0 = _dt.datetime.now(_dt.timezone.utc)
def _now_utc():
    return BASE + (_dt.datetime.now(_dt.timezone.utc) - T0)


class FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        n = _now_utc()
        return n.astimezone(tz) if tz else n.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return _now_utc().replace(tzinfo=None)


_MOD = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(second|minute|hour|day)s?\s*$")
def _sql_datetime(*args):
    """SQLite datetime() 대체 — 'now'는 고정 시각, 그 외는 ISO 문자열 파싱. 수정자: ±N minutes/hours/days."""
    if not args:
        return _now_utc().strftime("%Y-%m-%d %H:%M:%S")
    base = args[0]
    if base is None:
        return None
    if base == "now":
        t = _now_utc().replace(tzinfo=None)
    else:
        s = str(base).replace("T", " ")
        try:
            t = _dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                t = _dt.datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
    for m in args[1:]:
        mm = _MOD.match(str(m))
        if mm:
            v = float(mm.group(1)); u = mm.group(2)
            t += _dt.timedelta(**{u + "s": v})
        elif str(m).strip() == "start of day":
            t = t.replace(hour=0, minute=0, second=0, microsecond=0)
    return t.strftime("%Y-%m-%d %H:%M:%S")


_orig_connect = sqlite3.connect
def _connect(*a, **k):
    con = _orig_connect(*a, **k)
    con.create_function("datetime", -1, _sql_datetime)
    return con
sqlite3.connect = _connect

import aq.webdata as wd
wd.datetime = FrozenDT

sys.argv = ["webapp.py", "--db", os.environ.get("AQ_FIXTURE_DB") or (EN + r"\sensor_data.db"), "--nodes", EN + r"\nodes.json", "--port", "8512", "--quiet"]
runpy.run_path(HUB + r"\webapp.py", run_name="__main__")
