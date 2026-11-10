"""Report tests: fake fixtures only, no network, no cookies.
Run: python3 -m tests.test_report   (or pytest)"""
import copy
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("FH_LEAGUE_ID", "1")
os.environ.setdefault("FH_TEAM_ID", "1")
from fh_companion import report as R
from fh_companion.config import CFG

FIX = Path(__file__).parent / "fixtures" / "report_snapshot.json"
NOW = datetime(2030, 1, 8, 9, 30, 0)
OK_LINE = ("2030-01-08 09:03:46 EST OK mode=run | HTTP 200 sp 43 | team 1: Sample Team | roster 6 | "
           "set: mode=run spids=43..194 ok=2 already=150 partial=0 planned=0 fail=0 | "
           "verify: mode=verify spids=43..194 ok=0 already=152 partial=0 planned=0 fail=0 | not-active: Sample Injured Six=INJURY_RESERVE")


def snap():
    return json.loads(FIX.read_text())


def cfg(tmp, line=None):
    c = dict(CFG)
    logs = Path(tmp) / "logs"
    logs.mkdir(exist_ok=True)
    if line is not None:
        (logs / "LAST_STATUS").write_text(line + "\n")
    (logs / "daily_20300108.log").write_text("===== start\n--- pull exit=0\n")
    c.update(status_file=logs / "LAST_STATUS", log_dir=logs, analysis_file=Path(tmp) / "none.json", adds_limit=None, stale_hours=26)
    return c


def test_status_ok():
    with tempfile.TemporaryDirectory() as t:
        s = R.read_status(*[cfg(t, OK_LINE)[k] for k in ("status_file", "log_dir")], now=NOW)
        assert s["state"] == "ok" and s["level"] == "good" and s["sp"] == 43
        assert s["set"]["days"] == 152 and s["set"]["fail"] == 0 and s["verify"]["fail"] == 0
        assert s["log_name"] == "daily_20300108.log"


def test_status_stale():
    with tempfile.TemporaryDirectory() as t:
        c = cfg(t, OK_LINE)
        s = R.read_status(c["status_file"], c["log_dir"], now=NOW + timedelta(hours=27))
        assert s["state"] == "stale" and s["level"] == "bad"
        html = R.render(R.build_model(snap(), c, now=NOW + timedelta(hours=27)))
        assert "STALE" in html and "card bad" in html


def test_status_missing():
    with tempfile.TemporaryDirectory() as t:
        c = cfg(t, None)
        s = R.read_status(c["status_file"], c["log_dir"], now=NOW)
        assert s["state"] == "missing" and s["level"] == "bad"
        assert "MISSING" in R.render(R.build_model(snap(), c, now=NOW))


def test_status_fail():
    with tempfile.TemporaryDirectory() as t:
        c = cfg(t, "2030-01-08 09:01:00 EST FAIL AUTH (pull): ESPN 401/403 - cookies expired")
        s = R.read_status(c["status_file"], c["log_dir"], now=NOW)
        assert s["state"] == "fail" and s["level"] == "bad"
        c2 = cfg(t, OK_LINE.replace("partial=0 planned=0 fail=0 | verify", "partial=0 planned=0 fail=2 | verify"))
        assert R.read_status(c2["status_file"], c2["log_dir"], now=NOW)["state"] == "fail"


def test_pending_adds_and_ir():
    with tempfile.TemporaryDirectory() as t:
        tx = R.transactions_ir(snap(), cfg(t, OK_LINE))
        assert len(tx["pending"]) == 1
        p = tx["pending"][0]
        assert p["add"] == ["Sample Waiver Claim"] and p["drop"] == ["Sample Wing Two"] and p["processes"]
        assert (tx["adds_limit"], tx["adds_used"], tx["adds_left"]) == (4, 1, 3)
        assert [r["name"] for r in tx["ir"]] == ["Sample Injured Six"] and tx["healthy_in_ir"] == []
        assert "class='alert'" not in R.render(R.build_model(snap(), cfg(t, OK_LINE), now=NOW))


def test_healthy_player_in_ir_warns():
    with tempfile.TemporaryDirectory() as t:
        s = snap()
        bad = copy.deepcopy(s["team"]["entries"][0])
        bad.update(playerId=9050, lineupSlotId=8, injuryStatus="NORMAL")
        bad["player"].update(id=9050, fullName="Sample Healthy In IR", injuryStatus="ACTIVE", injured=False)
        s["team"]["entries"].append(bad)
        dtd = copy.deepcopy(bad)
        dtd.update(playerId=9051)
        dtd["player"].update(id=9051, fullName="Sample Day To Day In IR", injuryStatus="DAY_TO_DAY")
        s["team"]["entries"].append(dtd)
        c = cfg(t, OK_LINE)
        tx = R.transactions_ir(s, c)
        assert {h["name"] for h in tx["healthy_in_ir"]} == {"Sample Healthy In IR", "Sample Day To Day In IR"}
        html = R.render(R.build_model(s, c, now=NOW))
        assert html.count("class='alert'") == 2 and "blocks every add" in html


def test_adds_limit_config_override_and_zero_left():
    with tempfile.TemporaryDirectory() as t:
        c = cfg(t, OK_LINE)
        c["adds_limit"] = 1
        tx = R.transactions_ir(snap(), c)
        assert tx["adds_left"] == 0 and tx["adds_limit_source"] == "config"


def test_recent_form():
    with tempfile.TemporaryDirectory() as t:
        rows = {r["name"]: r for r in R.recent_form(snap(), cfg(t, OK_LINE), {9001: "AAA"})}
        c1 = rows["Sample Center One"]
        assert (c1["ppg7"], c1["ppg15"], c1["proj_ppg"], c1["team"]) == (3.0, 2.7, 2.5, "AAA")
        assert c1["trend"] == 0.2
        g = rows["Sample Goalie Four"]   # 2 GS: 4*1 -5 +0.2*50 +0 +1 = 10 -> 5.0
        assert g["ppg7"] == 5.0 and g["gp7"] == 2
        assert rows["Sample Bench Five"]["ppg7"] is None


def test_render_has_all_sections_and_escapes():
    with tempfile.TemporaryDirectory() as t:
        s = snap()
        s["team"]["entries"][0]["player"]["fullName"] = "<script>x</script>"
        html = R.render(R.build_model(s, cfg(t, OK_LINE), now=NOW))
        for sid in ("id='status'", "id='transactions'", "id='form'"):
            assert sid in html
        assert "<script>" not in html and "&lt;script&gt;" in html


def test_read_only_no_write_methods():
    assert not any(hasattr(R.ReadOnlySession, m) for m in ("post", "put", "patch", "delete"))
    src = Path(R.__file__).read_text()
    assert "lm-api-writes" not in src and "post_tx" not in src and "espn_common" not in src
    assert '"GET"' in src and ".post(" not in src


def test_cli_fixture_writes_html():
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "index.html"
        assert R.main(["--fixture", str(FIX), "--out", str(out), "--json", str(Path(t) / "m.json")]) == 0
        assert "Pending moves" in out.read_text() and json.loads((Path(t) / "m.json").read_text())["tx"]["pending"]


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("FAIL ", name, type(e).__name__, e)
    print("REPORT TESTS:", "ALL PASS" if not fails else f"{fails} FAILED")
    return not fails


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
