"""Analyze data/pull_latest_raw.json under your league's scoring.
FPTS shown are ESPN applied totals (already league-scored). Goalie points are also recalculated
from `goalie_scoring` in config.json. Outputs data/analysis.json, data/roster.csv, data/fa.csv.
Usage: python3 -m fh_companion.analyze [raw.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import CFG
from .espn_common import DATA, TEAM, STAT_SEASON, STAT_L7, STAT_PROJ, STAT_LAST_YEAR

GS = CFG["goalie_scoring"]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Score a local pull (roster + free agents) and write analysis.json, roster.csv and fa.csv.",
    )
    ap.add_argument("raw", nargs="?", help="pull JSON from fh_companion.pull_espn (default: data/pull_latest_raw.json)")
    ap.add_argument("--out-dir", help="directory for analysis.json / roster.csv / fa.csv (default: config data_dir)")
    return ap.parse_args(argv)


def load_pull(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"No pull file at {path}. Run python -m fh_companion.pull_espn first.")
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {path}: {e}") from e
    except OSError as e:
        raise SystemExit(f"Could not read {path}: {e}") from e
    if not isinstance(data, dict) or "league" not in data or "pro" not in data:
        raise SystemExit(f"{path} is not a pull file (expected 'league' and 'pro' keys).")
    return data


def analyze(d: dict, out_dir: Path, team_id=None, goalie_scoring=None) -> dict:
    """Build roster/FA records from a pull dict and write the three output files. Returns the analysis payload."""
    team_id = TEAM if team_id is None else team_id
    gs = goalie_scoring if goalie_scoring is not None else GS
    try:
        L = d["league"]["j"]
        SP = L["scoringPeriodId"]
        pro = {t["id"]: t for t in d["pro"]["settings"]["proTeams"]}
        mp = L["settings"]["scheduleSettings"]["matchupPeriods"]
        wk = mp[str(L["status"]["currentMatchupPeriod"])]
    except (KeyError, TypeError) as e:
        raise SystemExit(f"Pull file is missing an expected field: {e}") from e
    SLOT = {0: "C", 1: "LW", 2: "RW", 3: "F", 4: "D", 5: "G", 6: "UTIL", 7: "BN", 8: "IR"}

    def games(tid, cond):
        t = pro.get(tid)
        return sum(len(v) for k, v in t["proGamesByScoringPeriod"].items() if cond(int(k))) if t else 0

    def pos(el):
        return "/".join(n for i, n in [(0, "C"), (1, "LW"), (2, "RW"), (4, "D"), (5, "G")] if i in el)

    def league_goalie(st):  # stat ids 1=W 4=GA 6=SV 7=SO 9=OTL
        return (gs["W"] * st.get("1", 0) + gs["GA"] * st.get("4", 0) + gs["SV"] * st.get("6", 0)
                + gs["SO"] * st.get("7", 0) + gs["OTL"] * st.get("9", 0))

    def rec(ppe, slot=None, owner=None):
        p = ppe["player"]
        S = {s["id"]: s for s in p.get("stats", [])}
        se = S.get(STAT_SEASON, {})
        st = se.get("stats", {}) or {}
        l7 = S.get(STAT_L7, {})
        pj = S.get(STAT_PROJ, {})
        pjs = pj.get("stats", {}) or {}
        ly = S.get(STAT_LAST_YEAR, {})
        lys = ly.get("stats", {}) or {}
        el = p.get("eligibleSlots", [])
        isG = 5 in el and not any(s in el for s in (0, 1, 2, 4))
        gp = (st.get("0", st.get("34", 0)) if isG else st.get("34", 0)) or 0
        r = dict(id=p["id"], name=p["fullName"], pos=pos(el), team=pro.get(p.get("proTeamId"), {}).get("abbrev"),
                 status=ppe.get("status"), own=round((p.get("ownership") or {}).get("percentOwned", 0), 1),
                 inj=p.get("injuryStatus"), slot=SLOT.get(slot) if slot is not None else None,
                 gp=gp, fpts=round(se.get("appliedTotal", 0) or 0, 2), l7=round(l7.get("appliedTotal", 0) or 0, 2),
                 proj=round(pj.get("appliedTotal", 0) or 0, 1), proj_gp=pjs.get("34") or pjs.get("0"),
                 ly=round(ly.get("appliedTotal", 0) or 0, 1), ly_gp=lys.get("34") or lys.get("0"),
                 teamGP=games(p.get("proTeamId"), lambda k: k < SP),
                 wkLeft=games(p.get("proTeamId"), lambda k: SP <= k <= max(wk)),
                 next7=games(p.get("proTeamId"), lambda k: SP <= k < SP + 7), isG=isG)
        r["fpg"] = round(r["fpts"] / gp, 2) if gp else None
        r["proj_pg"] = round(r["proj"] / r["proj_gp"], 2) if r["proj_gp"] else None
        r["ly_pg"] = round(r["ly"] / r["ly_gp"], 2) if r["ly_gp"] else None
        if isG:
            r.update(GS=st.get("0"), W=st.get("1"), L=st.get("2"), GA=st.get("4"), SV=st.get("6"), SO=st.get("7"),
                     OTL=st.get("9"), SVpct=st.get("11"), GAA=st.get("10"), calc_pts=round(league_goalie(st), 2))
        else:
            r.update(G=st.get("13"), A=st.get("14"), PTS=st.get("16"), PPP=st.get("38"),
                     SOG=st.get("29"), HIT=st.get("31"), BLK=st.get("32"),
                     TOI=round((st.get("27") or 0) / 60, 1) if gp else None)
            for k in ("SOG", "HIT", "BLK"):
                r[k + "pg"] = round((r[k] or 0) / gp, 1) if gp else None
        r["onTeam"] = owner if owner is not None else ppe.get("onTeamId")
        return r

    try:
        my = next(t for t in L["teams"] if t["id"] == team_id)
    except StopIteration:
        raise SystemExit(f"Team id {team_id} was not found in the pull file. Check team_id in config.json.") from None
    roster = [rec(e["playerPoolEntry"], e["lineupSlotId"], team_id) for e in my["roster"]["entries"]]
    fa = {}
    for _k, v in (d.get("fa") or {}).items():
        for ppe in v.get("j", {}).get("players", []):
            r = rec(ppe)
            fa.setdefault(r["id"], r)
    fa = list(fa.values())
    payload = {"scoringPeriod": SP, "week": wk, "roster": roster, "fa": fa,
               "scoringItems": L["settings"]["scoringSettings"]["scoringItems"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "analysis.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    keys = ["name", "pos", "team", "slot", "status", "own", "inj", "gp", "teamGP", "fpts", "fpg", "l7",
            "proj", "proj_gp", "proj_pg", "ly_pg", "TOI", "G", "A", "PTS", "PPP", "SOG", "HIT", "BLK",
            "SOGpg", "HITpg", "BLKpg", "GS", "W", "L", "OTL", "GA", "SV", "SVpct", "SO", "calc_pts",
            "wkLeft", "next7"]
    with (out_dir / "roster.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(roster)
    with (out_dir / "fa.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(fa, key=lambda r: -r["proj"]))
    return payload


def main(argv=None) -> int:
    args = parse_args(argv)
    raw_path = Path(args.raw) if args.raw else Path(DATA) / "pull_latest_raw.json"
    out_dir = Path(args.out_dir) if args.out_dir else Path(DATA)
    d = load_pull(raw_path)
    payload = analyze(d, out_dir)
    roster, fa, SP, wk = payload["roster"], payload["fa"], payload["scoringPeriod"], payload["week"]
    print(f"SP {SP} week {wk} roster {len(roster)} FA {len(fa)} -> analysis.json roster.csv fa.csv")
    for r in sorted(roster, key=lambda r: -(r["fpg"] or 0)):
        print(f"  {r['slot']:4} {r['name']:22} {r['team']:4} {r['pos']:8} inj={r['inj']} gp={r['gp']} fpts={r['fpts']} fpg={r['fpg']} ros_pg={r['proj_pg']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
