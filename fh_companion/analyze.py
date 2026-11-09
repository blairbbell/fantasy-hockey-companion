"""Analyze data/pull_latest_raw.json under your league's scoring.
FPTS shown are ESPN applied totals (already league-scored). Goalie points are also recalculated
from `goalie_scoring` in config.json. Outputs data/analysis.json, data/roster.csv, data/fa.csv.
Usage: python3 -m fh_companion.analyze [raw.json]"""
import json, csv, sys
from .config import CFG
from .espn_common import DATA, TEAM, STAT_SEASON, STAT_L7, STAT_PROJ, STAT_LAST_YEAR

GS = CFG["goalie_scoring"]


def main():
    RAW = sys.argv[1] if len(sys.argv) > 1 else str(DATA / "pull_latest_raw.json")
    d = json.load(open(RAW))
    L = d["league"]["j"]; SP = L["scoringPeriodId"]
    pro = {t["id"]: t for t in d["pro"]["settings"]["proTeams"]}
    mp = L["settings"]["scheduleSettings"]["matchupPeriods"]
    wk = mp[str(L["status"]["currentMatchupPeriod"])]
    SLOT = {0: "C", 1: "LW", 2: "RW", 3: "F", 4: "D", 5: "G", 6: "UTIL", 7: "BN", 8: "IR"}
    def games(tid, cond):
        t = pro.get(tid)
        return sum(len(v) for k, v in t["proGamesByScoringPeriod"].items() if cond(int(k))) if t else 0
    def pos(el): return "/".join(n for i, n in [(0, "C"), (1, "LW"), (2, "RW"), (4, "D"), (5, "G")] if i in el)
    def league_goalie(st):  # stat ids 1=W 4=GA 6=SV 7=SO 9=OTL
        return (GS["W"]*st.get("1", 0) + GS["GA"]*st.get("4", 0) + GS["SV"]*st.get("6", 0)
                + GS["SO"]*st.get("7", 0) + GS["OTL"]*st.get("9", 0))
    def rec(ppe, slot=None, owner=None):
        p = ppe["player"]; S = {s["id"]: s for s in p.get("stats", [])}
        se = S.get(STAT_SEASON, {}); st = se.get("stats", {}) or {}
        l7 = S.get(STAT_L7, {}); pj = S.get(STAT_PROJ, {}); pjs = pj.get("stats", {}) or {}
        ly = S.get(STAT_LAST_YEAR, {}); lys = ly.get("stats", {}) or {}
        el = p.get("eligibleSlots", [])
        isG = 5 in el and not any(s in el for s in (0, 1, 2, 4))
        gp = (st.get("0", st.get("34", 0)) if isG else st.get("34", 0)) or 0
        r = dict(id=p["id"], name=p["fullName"], pos=pos(el), team=pro.get(p.get("proTeamId"), {}).get("abbrev"),
                 status=ppe.get("status"), own=round((p.get("ownership") or {}).get("percentOwned", 0), 1),
                 inj=p.get("injuryStatus"), slot=SLOT.get(slot) if slot is not None else None,
                 gp=gp, fpts=round(se.get("appliedTotal", 0) or 0, 2), l7=round(l7.get("appliedTotal", 0) or 0, 2),
                 proj=round(pj.get("appliedTotal", 0) or 0, 1), proj_gp=pjs.get("34") or pjs.get("0"),
                 ly=round(ly.get("appliedTotal", 0) or 0, 1), ly_gp=lys.get("34") or lys.get("0"),
                 teamGP=games(p.get("proTeamId"), lambda k: k < SP), wkLeft=games(p.get("proTeamId"), lambda k: SP <= k <= max(wk)),
                 next7=games(p.get("proTeamId"), lambda k: SP <= k < SP + 7), isG=isG)
        r["fpg"] = round(r["fpts"]/gp, 2) if gp else None
        r["proj_pg"] = round(r["proj"]/r["proj_gp"], 2) if r["proj_gp"] else None
        r["ly_pg"] = round(r["ly"]/r["ly_gp"], 2) if r["ly_gp"] else None
        if isG:
            r.update(GS=st.get("0"), W=st.get("1"), L=st.get("2"), GA=st.get("4"), SV=st.get("6"), SO=st.get("7"), OTL=st.get("9"),
                     SVpct=st.get("11"), GAA=st.get("10"), calc_pts=round(league_goalie(st), 2))
        else:
            r.update(G=st.get("13"), A=st.get("14"), PTS=st.get("16"), PPP=st.get("38"), SOG=st.get("29"), HIT=st.get("31"), BLK=st.get("32"),
                     TOI=round((st.get("27") or 0)/60, 1) if gp else None)  # stat 27 appears to be avg TOI seconds -> minutes
            for k in ("SOG", "HIT", "BLK"):
                r[k+"pg"] = round((r[k] or 0)/gp, 1) if gp else None
        r["onTeam"] = owner if owner is not None else ppe.get("onTeamId")
        return r
    my = next(t for t in L["teams"] if t["id"] == TEAM)
    roster = [rec(e["playerPoolEntry"], e["lineupSlotId"], TEAM) for e in my["roster"]["entries"]]
    fa = {}
    for k, v in d["fa"].items():
        for ppe in v["j"].get("players", []):
            r = rec(ppe); fa.setdefault(r["id"], r)
    fa = list(fa.values())
    json.dump({"scoringPeriod": SP, "week": wk, "roster": roster, "fa": fa,
               "scoringItems": L["settings"]["scoringSettings"]["scoringItems"]}, open(DATA / "analysis.json", "w"), indent=1)
    keys = ["name","pos","team","slot","status","own","inj","gp","teamGP","fpts","fpg","l7","proj","proj_gp","proj_pg","ly_pg","TOI","G","A","PTS","PPP","SOG","HIT","BLK","SOGpg","HITpg","BLKpg","GS","W","L","OTL","GA","SV","SVpct","SO","calc_pts","wkLeft","next7"]
    with open(DATA / "roster.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore"); w.writeheader(); [w.writerow(r) for r in roster]
    with open(DATA / "fa.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys, extrasaction="ignore"); w.writeheader(); [w.writerow(r) for r in sorted(fa, key=lambda r: -r["proj"])]
    print(f"SP {SP} week {wk} roster {len(roster)} FA {len(fa)} -> analysis.json roster.csv fa.csv")
    for r in sorted(roster, key=lambda r: -(r["fpg"] or 0)):
        print(f"  {r['slot']:4} {r['name']:22} {r['team']:4} {r['pos']:8} inj={r['inj']} gp={r['gp']} fpts={r['fpts']} fpg={r['fpg']} ros_pg={r['proj_pg']}")


if __name__ == "__main__":
    main()
