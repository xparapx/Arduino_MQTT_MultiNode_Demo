"""Both dashboard pages run in Streamlit bare mode against a fixture copy:
page 2 with an empty analysis table (guidance) and after real hourly / daily /
weekly analyst runs (every section renders without raising)."""

import runpy
import shutil
import sys
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import analyst  # noqa: E402


@pytest.fixture
def workdir(fixture_path, tmp_path, monkeypatch):
    """A cwd that looks like hub/ on the board: sensor_data.db + nodes.json."""
    shutil.copy(fixture_path, tmp_path / "sensor_data.db")
    shutil.copy(fixture_path.parent / "nodes.json", tmp_path / "nodes.json")
    monkeypatch.chdir(tmp_path)
    import streamlit as st

    st.cache_data.clear()          # DB path is relative, so cached (0, "") would leak
    st.cache_resource.clear()      # between the empty and the populated test
    return tmp_path


def _fragments(ns):
    return {k: v.__wrapped__ for k, v in ns.items()
            if k.startswith(("section_", "diagnosis")) and hasattr(v, "__wrapped__")}


def _run_page(path):
    """run_path in bare mode; st.stop() raises StopException there -- treat as a clean end."""
    try:
        return runpy.run_path(str(path), run_name="page"), False
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ == "StopException":
            return None, True
        raise


def test_page2_empty_state(workdir):
    ns, stopped = _run_page(HUB / "pages" / "2_diagnosis.py")
    assert stopped or ns is not None          # guidance shown, no exception


def test_page1_runs(workdir):
    ns, stopped = _run_page(HUB / "dashboard.py")
    assert not stopped
    frags = _fragments(ns)
    assert {"section_live_status", "section_stats", "section_node_detail",
            "section_export"} <= set(frags)
    for fn in frags.values():
        fn()                                   # every section renders


def test_page2_after_analysis(workdir, tmp_path):
    db = str(workdir / "sensor_data.db")
    as_of = analyst.parse_as_of(None)
    import sqlite3

    hi = sqlite3.connect(db).execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    base = ["--db", db, "--nodes", str(workdir / "nodes.json"), "--as-of", hi]
    assert analyst.main(["run", "--mode", "hourly", *base]) == 0          # uses hub/models gmm_v1
    assert analyst.main(["run", "--mode", "daily", *base]) == 0
    assert analyst.main(["run", "--mode", "weekly", *base,
                         "--models-dir", str(tmp_path / "models")]) == 0
    import streamlit as st

    st.cache_data.clear()
    ns, stopped = _run_page(HUB / "pages" / "2_diagnosis.py")
    assert not stopped and ns is not None
    from aq import analysis_view

    assert analysis_view.analysis_version()[0] > 0   # populated, not the cached empty state
    frags = _fragments(ns)
    assert "diagnosis" in frags
    frags["diagnosis"]()                       # sections A-I with real payloads
    assert as_of is not None
