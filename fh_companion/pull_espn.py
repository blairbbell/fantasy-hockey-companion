"""Read-only pull of your league: mTeam/mRoster/mSettings/mStatus/mMatchup(+Score), free agents
(kona_player_info) and NHL schedules. Writes data/pull_latest_raw.json (+ dated copy). No writes to ESPN.
Usage: python3 -m fh_companion.pull_espn [--keep-history]"""
import json
import shutil
import sys
from datetime import datetime

from .espn_common import DATA, TEAM, LEAGUE_URL, STAT_SEASON, STAT_L7, STAT_PROJ, session, get, league, pro_schedule


def main():
    s = session()
    out = {}
    L = league(s, ["mTeam", "mRoster", "mSettings", "mStatus", "mMatchup", "mMatchupScore"])
    out["league"] = {"ok": True, "status": 200, "j": L}
    pulls = {
        "byOwn": {"sortPercOwned": {"sortPriority": 1, "sortAsc": False}},
        "bySeason": {"sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": STAT_SEASON}},
        "byL7": {"sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": STAT_L7}},
        "byProj": {"sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": STAT_PROJ}},
    }
    out["fa"] = {}
    for k, srt in pulls.items():
        f = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "filterSlotIds": {"value": [0, 1, 2, 4, 5, 6]}, "limit": 200, **srt}}
        out["fa"][k] = {"ok": True, "status": 200, "j": get(s, LEAGUE_URL, params={"view": "kona_player_info"}, filt=f)}
    f = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "filterSlotIds": {"value": [5]}, "limit": 60, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    out["fa"]["goalies"] = {"ok": True, "status": 200, "j": get(s, LEAGUE_URL, params={"view": "kona_player_info"}, filt=f)}
    out["pro"] = pro_schedule(s)
    p = DATA / "pull_latest_raw.json"
    p.write_text(json.dumps(out))
    if "--keep-history" in sys.argv:
        shutil.copy(p, DATA / f"pull_{datetime.now():%Y%m%d_%H%M}_raw.json")
    me = next(t for t in L["teams"] if t["id"] == TEAM)
    name = me.get("name") or f"{me.get('location', '')} {me.get('nickname', '')}".strip()
    print(f"HTTP 200 | league: {L['settings']['name']} | scoringPeriod {L.get('scoringPeriodId')} | team {TEAM}: {name} | roster {len(me['roster']['entries'])}")
    print("FA pulls:", {k: len(v["j"].get("players", [])) for k, v in out["fa"].items()})
    print("saved", p)


if __name__ == "__main__":
    main()
