"""Phase 8 web front end: aq.webdata on the fixture (before and after analyst
runs) and webapp.py end-to-end on an ephemeral port (JSON, static, CSV,
reset guard)."""

import json
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import analyst  # noqa: E402
import webapp  # noqa: E402
from aq import webdata  # noqa: E402


@pytest.fixture(scope="module")
def site(fixture_path, tmp_path_factory):
    """Fixture copy with real hourly + daily analysis rows, served by webapp."""
    d = tmp_path_factory.mktemp("site")
    shutil.copy(fixture_path, d / "sensor_data.db")
    shutil.copy(fixture_path.parent / "nodes.json", d / "nodes.json")
    hi = sqlite3.connect(d / "sensor_data.db").execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    base = ["--db", str(d / "sensor_data.db"), "--nodes", str(d / "nodes.json"), "--as-of", hi]
    assert analyst.main(["run", "--mode", "hourly", *base]) == 0
    assert analyst.main(["run", "--mode", "daily", *base]) == 0
    data = webdata.WebData(d / "sensor_data.db", d / "nodes.json", HUB / "models")
    srv, url = webapp.serve_in_thread(data)
    yield {"dir": d, "data": data, "url": url}
    srv.shutdown()


def _rows(path):
    return sqlite3.connect(path).execute("SELECT COUNT(*) FROM readings").fetchone()[0]


def get(url, raw=False):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return (r, body) if raw else json.loads(body)


def test_constants_match_ui_common():
    """webdata duplicates the page-1 tables to stay streamlit-free; keep them equal."""
    from aq import ui_common

    assert {k: v[:2] + v[3:] for k, v in ui_common.METRICS.items()} == \
        {k: (v[0], v[1], v[2], v[3]) for k, v in webdata.METRICS.items()}
    assert ui_common.GAUGE_KEYS == webdata.GAUGE_KEYS
    assert ui_common.NODE_PALETTE == webdata.NODE_PALETTE
    assert ui_common.STATS_DAYS == webdata.STATS_DAYS


def test_webdata_empty_db(tmp_path):
    w = webdata.WebData(tmp_path / "none.db", tmp_path / "nodes.json", tmp_path)
    assert w.live()["nodes"] == [] and w.stats()["box"] == {}
    assert w.status()["readings_rows"] == 0 and w.analysis()["empty"]
    assert w.series("x")["times"] == [] and w.time_bounds()["lo"] is None


def test_live_and_stats(site):
    w = site["data"]
    live = w.live()
    assert len(live["nodes"]) == 8 and live["nodes"][0]["label"] == "CLASS_01"
    n = live["nodes"][1]
    assert [r["key"] for r in n["radar"]] == webdata.GAUGE_KEYS
    assert all(0 <= r["r"] <= 1 for r in n["radar"])
    assert len({x["color"] for x in live["nodes"]}) == 8            # stable per-node colours
    st = w.stats()
    assert set(st["box"]) == set(webdata.GAUGE_KEYS)
    co2 = st["box"]["co2"]
    assert co2["q1"] <= co2["median"] <= co2["q3"]
    assert len(co2["outliers"]) <= webdata.BOX_MAX_OUTLIERS
    assert st["by_node"]["co2"] == sorted(st["by_node"]["co2"], key=lambda r: -r["mean"])
    assert w.stats() is st                                          # memoised on the bucket


def test_series_records_occupancy(site):
    w = site["data"]
    node = w.env_nodes()[0]
    s = w.series(node)
    assert 0 < len(s["times"]) <= webdata.SERIES_BUCKETS
    assert set(s["series"]) == set(webdata.GAUGE_KEYS)
    assert len(s["records"]) == webdata.RECORDS_N
    assert s["records"][0]["recv_time"] >= s["records"][-1]["recv_time"]
    occ = s["occupancy"]
    assert occ["available"] and occ["label"] == s["label"] and len(occ["hist"]) <= webdata.OCC_HIST
    assert all(len(c) == 2 for c in occ["cents"])
    assert len(occ["nodes"]) == 5                                   # ON/OFF chip per vision node
    assert all({"node", "room", "on", "age_min", "last_kst"} <= set(v) for v in occ["nodes"])
    assert any(v["node"] == occ["vision_node"] for v in occ["nodes"])
    assert w.series("nope")["times"] == []


def test_status(site):
    st = site["data"].status()
    assert st["env_total"] == 8 and st["vis_total"] == 5 and st["readings_rows"] > 0
    assert st["hourly_kst"] and st["daily_kst"] and st["weekly_kst"] is None
    assert st["model"] == "gmm_v1"


def test_analysis_bundle(site):
    a = site["data"].analysis()
    assert not a["empty"] and a["model"]["ver"] == "gmm_v1" and a["model"]["meta"]["components"]
    assert len(a["rooms"]) == 8
    assert {r["action"]["kind"] for r in a["rooms"]} <= {"fan", "purifier", "both", "none", "hold"}
    unjudged = [r for r in a["rooms"] if not r["judged"]]
    assert all(r["action"]["word"] == "판정 보류" for r in unjudged)
    assert a["band"] and set(a["band"]["share"]) <= {*a["regimes"], "missing"}
    assert a["transition"]["valid_pairs"] > 0 and len(a["transition"]["rows"]) == 4
    assert a["occ_co2"]["by_room"] and any(r["stopped"] for r in a["occ_co2"]["by_room"])
    assert a["explore"]["pooled"]["bins"] == len(a["explore"]["pooled"]["hist"])
    assert a["summary"]["lines"]
    assert len(a["qc"]) == 8 and all(len(q["days"]) <= 8 for q in a["qc"])   # one row per node
    assert any(q["failed_days"] for q in a["qc"])
    # E: 24 h band trace per room, anchored at the hourly action run
    n_slots = webdata.BAND24_HOURS * 60 // webdata.BAND24_BUCKET_MIN
    for r in a["rooms"]:
        b = r["band24"]
        assert b["end_kst"] and b["hours"] == webdata.BAND24_HOURS
        assert len(b["co2"]) == len(b["voc"]) and len(b["co2"]) in (0, n_slots)
        assert all(0 <= h0 <= h1 <= webdata.BAND24_HOURS
                   for segs in [*b["on"].values(), b["unjudged"]] for h0, h1 in segs)
        if r["judged"]:
            assert sum(v is not None for v in b["co2"]) > 0
        else:
            assert b["unjudged"] or not b["co2"]          # QC-excluded run -> hatched hours
    assert any(sum(v is not None for v in r["band24"]["co2"]) > 200 for r in a["rooms"])
    json.dumps(a, allow_nan=False)                                   # no NaN anywhere


def test_http_endpoints(site):
    url = site["url"]
    for ep in ("status", "live", "stats", "bounds", "analysis"):
        body = get(f"{url}/api/{ep}")
        assert isinstance(body, dict) and "error" not in body
    node = site["data"].env_nodes()[0]
    assert get(f"{url}/api/series?node={node}")["node"] == node
    r, body = get(f"{url}/", raw=True)
    assert r.status == 200 and b"page1.js" in body
    r, body = get(f"{url}/diagnosis", raw=True)
    assert b"page2.js" in body
    r, body = get(f"{url}/static/app.css", raw=True)
    assert "text/css" in r.headers["Content-Type"] and b"--panel" in body
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{url}/static/../webapp.py", raw=True)
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{url}/api/series")
    assert e.value.code == 400


def test_http_gzip(site):
    req = urllib.request.Request(f"{site['url']}/api/analysis", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.headers.get("Content-Encoding") == "gzip"
        import gzip

        assert json.loads(gzip.decompress(r.read()))["version"] > 0


def test_http_export_and_reset_guard(site):
    url = site["url"]
    r, body = get(f"{url}/api/export?kind=range&start=2026-08-28T00:00&end=2026-08-29T23:59",
                  raw=True)
    assert r.headers["Content-Disposition"].startswith("attachment")
    assert int(r.headers["X-Rows"]) > 0
    assert body.startswith(b"\xef\xbb\xbfrecv_time_kst")
    r, body = get(f"{url}/api/export?kind=occupancy", raw=True)
    assert int(r.headers["X-Rows"]) > 0 and b"room" in body[:200]
    with pytest.raises(urllib.error.HTTPError) as e:
        get(f"{url}/api/export?kind=range&start=2026-08-29T00:00&end=2026-08-28T00:00")
    assert e.value.code == 400
    # reset without the confirm phrase must not touch the table
    before = _rows(site["dir"] / "sensor_data.db")
    req = urllib.request.Request(f"{url}/api/reset", data=b'{"confirm": "no"}', method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=30)
    assert e.value.code == 400
    after = _rows(site["dir"] / "sensor_data.db")
    assert before == after > 0


def test_public_instance_is_monitoring_only(site):
    """--public: export and reset answer 403, status says so, everything else works."""
    srv, url = webapp.serve_in_thread(site["data"], public=True)
    try:
        assert get(f"{url}/api/status")["public"] is True
        assert get(f"{url}/api/analysis")["version"] > 0
        for path in ("/api/export?kind=all",
                     "/api/export?kind=range&start=2026-08-28T00:00&end=2026-08-29T00:00"):
            with pytest.raises(urllib.error.HTTPError) as e:
                get(f"{url}{path}", raw=True)
            assert e.value.code == 403
        before = _rows(site["dir"] / "sensor_data.db")
        req = urllib.request.Request(f"{url}/api/reset", data=b'{"confirm": "DELETE"}',
                                     method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=30)
        assert e.value.code == 403 and _rows(site["dir"] / "sensor_data.db") == before
    finally:
        srv.shutdown()
    assert get(f"{site['url']}/api/status")["public"] is False        # admin instance untouched
