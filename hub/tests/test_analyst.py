"""analyst.py end to end on the fixture, dry-run only: every payload validates,
regime names are the four plan names, gap_pairs > 0 and a QC-failed node exist,
and nothing is written to the DB."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import analyst  # noqa: E402
from aq import db, regime, schemas  # noqa: E402


@pytest.fixture(scope="module")
def as_of(fixture_path):
    conn = db.connect_ro(fixture_path)
    hi = conn.execute("SELECT MAX(ts) FROM readings").fetchone()[0]
    conn.close()
    return hi


def _run(mode, fixture_path, as_of, capsys, extra=()):
    rc = analyst.main(["run", "--mode", mode, "--db", str(fixture_path),
                       "--nodes", str(fixture_path.parent / "nodes.json"),
                       "--as-of", as_of, "--dry-run", *extra])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    for r in rows:
        schemas.validate(r["kind"], r["payload"])
        assert set(r) == {"run_at", "kind", "scope", "win_start", "win_end", "model_ver", "payload"}
    return rows


def test_hourly_dry_run(fixture_path, as_of, capsys):
    rows = _run("hourly", fixture_path, as_of, capsys)
    kinds = {r["kind"] for r in rows}
    assert {"qc", "regime_now", "action", "summary"} <= kinds
    regimes = {r["payload"]["regime"] for r in rows if r["kind"] == "regime_now"}
    assert regimes <= set(regime.REGIMES) | {"hold"} and regimes & set(regime.REGIMES)
    actions = [r for r in rows if r["kind"] == "action"]
    assert {a["payload"]["device"] for a in actions} == {"fan", "purifier"}
    assert all(a["payload"]["state"] in (0, 1) for a in actions)
    lines = [r for r in rows if r["kind"] == "summary"][0]["payload"]["lines"]
    assert 1 <= len(lines) <= 5


def test_daily_dry_run_has_gaps_and_qc_failures(fixture_path, as_of, capsys):
    rows = _run("daily", fixture_path, as_of, capsys)
    trans = [r for r in rows if r["kind"] == "transition"]
    assert trans and any(t["payload"]["gap_pairs"] > 0 for t in trans)
    assert all(set(t["payload"]["matrix"]) == set(regime.REGIMES) for t in trans)
    qcs = [r for r in rows if r["kind"] == "qc"]
    assert any(not q["payload"]["passed"] for q in qcs)
    bands = [r for r in rows if r["kind"] == "band"]
    assert bands and all(s["regime"] in regime.REGIMES or s["regime"] is None
                         for b in bands for s in b["payload"]["slots"])
    occ = [r for r in rows if r["kind"] == "occ_co2"]
    assert len(occ) == 1


def test_weekly_dry_run(fixture_path, as_of, capsys, tmp_path):
    rows = _run("weekly", fixture_path, as_of, capsys, extra=["--models-dir", str(tmp_path)])
    assert len(rows) == 1 and rows[0]["kind"] == "model_event"
    p = rows[0]["payload"]
    assert p["decision"] == "promote" and p["reason"] == "first model"      # no current yet
    assert p["stored"] is False and not list(tmp_path.glob("gmm_v*"))       # dry-run stores nothing


def test_weekly_store_promote_then_keep(fixture_copy, as_of, capsys, tmp_path):
    """Real weekly run on a copy: v1 stored + promoted; a second run keeps."""
    from aq import governance
    base = ["run", "--mode", "weekly", "--db", str(fixture_copy), "--as-of", as_of,
            "--models-dir", str(tmp_path)]
    assert analyst.main(base) == 0
    capsys.readouterr()
    assert governance.list_versions(tmp_path) == ["gmm_v1"]
    assert governance.resolve_current(tmp_path) == "gmm_v1"
    assert analyst.main(base) == 0                       # same data -> candidate v2 kept
    capsys.readouterr()
    assert governance.list_versions(tmp_path) == ["gmm_v1", "gmm_v2"]
    assert governance.resolve_current(tmp_path) == "gmm_v1"
    conn = sqlite3.connect(fixture_copy)
    events = conn.execute("SELECT payload FROM analysis WHERE kind='model_event' ORDER BY id")
    decisions = [json.loads(r[0])["decision"] for r in events]
    conn.close()
    assert decisions == ["promote", "keep"]
    # hourly now uses the promoted model, not the ad-hoc fit
    rows = _run("hourly", fixture_copy, as_of, capsys, extra=["--models-dir", str(tmp_path)])
    assert {r["model_ver"] for r in rows if r["kind"] == "regime_now"} == {"gmm_v1"}


def test_model_subcommand(fixture_copy, as_of, capsys, tmp_path):
    base = ["--db", str(fixture_copy), "--as-of", as_of, "--models-dir", str(tmp_path)]
    assert analyst.main(["fit", "--window", "28", *base]) == 0            # v1, auto-promoted
    assert analyst.main(["fit", "--window", "28", *base]) == 0            # v2, not promoted
    capsys.readouterr()
    assert analyst.main(["model", "list", *base]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["current"] == "gmm_v1"
    assert [v["version"] for v in listing["versions"]] == ["gmm_v1", "gmm_v2"]
    assert analyst.main(["model", "promote", "--to", "gmm_v2", *base]) == 0
    assert analyst.main(["model", "rollback", "--to", "gmm_v1", *base]) == 0
    assert analyst.main(["model", "rollback", "--to", "gmm_v9", *base]) == 2
    capsys.readouterr()
    conn = sqlite3.connect(fixture_copy)
    kinds = [json.loads(r[0])["decision"] for r in conn.execute(
        "SELECT payload FROM analysis WHERE kind='model_event' ORDER BY id")]
    conn.close()
    assert kinds == ["promote", "rollback"]


def test_dry_run_writes_nothing(fixture_copy, as_of, capsys):
    before = fixture_copy.read_bytes()
    _run("hourly", fixture_copy, as_of, capsys)
    assert fixture_copy.read_bytes() == before
    tables = {r[0] for r in sqlite3.connect(fixture_copy).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "analysis" not in tables


def test_fit_dry_run_meta(fixture_path, as_of, capsys, tmp_path):
    rc = analyst.main(["fit", "--window", "28", "--db", str(fixture_path), "--as-of", as_of,
                       "--dry-run", "--models-dir", str(tmp_path)])
    assert rc == 0
    meta = json.loads(capsys.readouterr().out)
    assert {c["regime"] for c in meta["components"]} == set(regime.REGIMES)
    assert meta["version"] == "gmm_v1" and meta["rows"] > 0      # next free version name


def test_show_on_empty_db(tmp_path, empty_db, capsys):
    rc = analyst.main(["show", "--kind", "summary", "--db", str(empty_db)])
    assert rc == 0 and json.loads(capsys.readouterr().out) == []


def test_write_path_on_a_copy(fixture_copy, as_of, capsys):
    """Real write (on a copy): analysis + actuator_state land, readings untouched."""
    with sqlite3.connect(fixture_copy) as c0:
        n_read = c0.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    rc = analyst.main(["run", "--mode", "hourly", "--db", str(fixture_copy),
                       "--nodes", str(HUB / "fixtures" / "nodes.json"), "--as-of", as_of])
    assert rc == 0
    conn = sqlite3.connect(fixture_copy)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == n_read
    assert conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM actuator_state").fetchone()[0] > 0
    conn.close()
