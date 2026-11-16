"""Analyze tests: fake pull fixture only, no network, no cookies.
Run: python3 -m tests.test_analyze   (or pytest)."""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

os.environ.setdefault("FH_LEAGUE_ID", "1")
os.environ.setdefault("FH_TEAM_ID", "1")
from fh_companion import analyze as A

FIX = Path(__file__).parent / "fixtures" / "analyze_pull.json"


def test_analyze_writes_outputs():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        out = Path(t)
        payload = A.analyze(json.loads(FIX.read_text()), out, team_id=1)
        assert payload["scoringPeriod"] == 40
        assert {r["name"] for r in payload["roster"]} == {"Sample Center", "Sample Goalie"}
        skater = next(r for r in payload["roster"] if r["name"] == "Sample Center")
        goalie = next(r for r in payload["roster"] if r["name"] == "Sample Goalie")
        fa = next(r for r in payload["fa"] if r["name"] == "Sample Free Agent")
        assert skater["slot"] == "C" and skater["pos"] == "C" and skater["team"] == "SAM"
        assert skater["gp"] == 10 and skater["fpts"] == 30 and skater["fpg"] == 3.0
        assert skater["G"] == 3 and skater["A"] == 4
        assert goalie["pos"] == "G" and goalie["calc_pts"] is not None
        # W4 + GA*-1 + SV*0.2 + SO1 + OTL1 = 4*2 + -1*8 + 0.2*80 + 1 + 1 = 8 - 8 + 16 + 1 + 1 = 18
        assert goalie["calc_pts"] == 18.0
        assert fa["proj"] == 90 and fa["slot"] is None
        # already-played game on 39 plus upcoming 40,41 for team 1
        assert skater["teamGP"] == 1 and skater["next7"] == 2
        for name in ("analysis.json", "roster.csv", "fa.csv"):
            assert (out / name).exists()
        rows = (out / "roster.csv").read_text().splitlines()
        assert rows[0].startswith("name,pos,team,slot")
        assert any("Sample Center" in r for r in rows)


def test_load_pull_errors():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        missing = Path(t) / "nope.json"
        try:
            A.load_pull(missing)
        except SystemExit as e:
            assert "No pull file" in str(e)
        else:
            raise AssertionError("expected SystemExit")
        bad = Path(t) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        try:
            A.load_pull(bad)
        except SystemExit as e:
            assert "Invalid JSON" in str(e)
        else:
            raise AssertionError("expected SystemExit")
        empty = Path(t) / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        try:
            A.load_pull(empty)
        except SystemExit as e:
            assert "not a pull file" in str(e)
        else:
            raise AssertionError("expected SystemExit")


def test_unknown_team():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        try:
            A.analyze(json.loads(FIX.read_text()), Path(t), team_id=99)
        except SystemExit as e:
            assert "99" in str(e) and "not found" in str(e)
        else:
            raise AssertionError("expected SystemExit")


def test_cli_out_dir():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        out = Path(t)
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = A.main([str(FIX), "--out-dir", str(out)])
        assert code == 0 and err.getvalue() == ""
        assert "roster 2 FA 1" in buf.getvalue()
        assert "Sample Center" in buf.getvalue()
        assert (out / "analysis.json").exists()


def test_cli_help():
    buf, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(err):
            A.main(["--help"])
    except SystemExit as e:
        assert e.code == 0
        assert "out-dir" in buf.getvalue()
    else:
        raise AssertionError("expected SystemExit 0 from --help")


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except BaseException as e:  # includes SystemExit
                if isinstance(e, SystemExit) and e.code == 0:
                    raise
                fails += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print("ANALYZE TESTS:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
    return fails == 0


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
