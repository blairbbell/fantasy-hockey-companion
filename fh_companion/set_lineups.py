"""set_lineups - rest-of-season daily lineup optimizer for your ESPN fantasy hockey team.
LINEUP MOVES ONLY (ROSTER / FUTURE_ROSTER LINEUP items). No adds/drops/claims/trades. IR untouched.
Modes:  plan [from] [to]   (DEFAULT - read-only, prints moves)
        run  [from] [to]   (WRITES lineup changes to ESPN)
        verify [spid,spid,...]     (default: latest..final)
Rules: players with injuryStatus OUT / INJURY_RESERVE / SUSPENSION (or injured=True) are never put in active slots;
       names in config `never_start` are always benched (unless on IR); names in `force_start` are allowed to start
       even when ESPN still tags them injured.
Usage: python3 -m fh_companion.set_lineups [plan|run|verify] ...
"""
from datetime import date, timedelta, datetime
import json, sys, time
from .config import CFG
from .espn_common import DATA, TEAM, STAT_SEASON, STAT_PROJ, STAT_LAST_YEAR, session, league, pro_schedule, post_tx

SLOTS = CFG["lineup_slots"]   # {slot id: count}; C=0 LW=1 RW=2 D=4 G=5 UTIL=6
BENCH, IR, BENCH_N = 7, 8, CFG["bench_slots"]
SLOTNAME = {0: "C", 1: "LW", 2: "RW", 4: "D", 5: "G", 6: "UTIL", 7: "BN", 8: "IR"}
NO_START = {"OUT", "INJURY_RESERVE", "SUSPENSION"}
NEVER_START = set(CFG["never_start"])
FORCE_START = set(CFG["force_start"])
BIG = 10**9
LOG = DATA / "set_lineups.log"
DESIRED_PATH = DATA / "lineup_desired.json"
SEASON_START = date.fromisoformat(CFG["season_start"])

def log(m):
    print(m, flush=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(m + "\n")

def spid_date(s): return (SEASON_START + timedelta(days=s - 1)).isoformat()

def hungarian(a):
    n, m = len(a), len(a[0])
    u=[0]*(n+1); v=[0]*(m+1); p=[0]*(m+1); way=[0]*(m+1)
    for i in range(1, n+1):
        p[0]=i; j0=0; minv=[float('inf')]*(m+1); used=[False]*(m+1)
        while True:
            used[j0]=True; i0=p[j0]; delta=float('inf'); j1=0
            for j in range(1, m+1):
                if not used[j]:
                    cur=a[i0-1][j-1]-u[i0]-v[j]
                    if cur<minv[j]: minv[j]=cur; way[j]=j0
                    if minv[j]<delta: delta=minv[j]; j1=j
            for j in range(m+1):
                if used[j]: u[p[j]]+=delta; v[j]-=delta
                else: minv[j]-=delta
            j0=j1
            if p[j0]==0: break
        while True:
            j1=way[j0]; p[j0]=p[j1]; j0=j1
            if j0==0: break
    ans=[None]*n
    for j in range(1, m+1):
        if p[j]: ans[p[j]-1]=j-1
    return ans

def roster(s, spid):
    j = league(s, ["mRoster", "mStatus"], scoringPeriodId=spid, _=int(time.time()*1000))
    t = next(x for x in j["teams"] if x["id"] == TEAM)
    pl = []
    for e in t["roster"]["entries"]:
        p = e["playerPoolEntry"]["player"]
        pl.append({"id": e["playerId"], "slot": e["lineupSlotId"], "name": p["fullName"], "elig": p.get("eligibleSlots") or [],
                   "pro": p.get("proTeamId"), "inj": p.get("injuryStatus"), "injured": bool(p.get("injured")),
                   "stats": [{"id": x["id"], "applied": x.get("appliedTotal"), "st": x.get("stats")} for x in (p.get("stats") or [])
                             if x["id"] in (STAT_SEASON, STAT_PROJ, STAT_LAST_YEAR)]})
    return {"latest": j["status"]["latestScoringPeriod"], "final": j["status"]["finalScoringPeriod"], "players": pl}

def schedule(s):
    j = pro_schedule(s); out = {}
    for t in j["settings"]["proTeams"]:
        out[str(t["id"])] = {"abbrev": t["abbrev"], "games": {sp: [g["date"] for g in gs] for sp, gs in (t.get("proGamesByScoringPeriod") or {}).items()}}
    return out

def is_goalie(p): return 5 in p["elig"] and not any(s in p["elig"] for s in (0,1,2,4))
def unavailable(p): return p["inj"] in NO_START or p["injured"]

def value(p):
    S = {s["id"]: s for s in p["stats"]}; g = is_goalie(p)
    def gp_of(st):
        st = st or {}
        if g: return max(st.get("0", 0) or 0, (st.get("1",0) or 0)+(st.get("2",0) or 0)+(st.get("9",0) or 0), st.get("34",0) or 0)
        return st.get("34", 0) or 0
    def pg(sid):
        x = S.get(sid)
        if not x: return None, 0
        n = gp_of(x.get("st"))
        return ((x.get("applied") or 0)/n if n else None), n
    proj, _ = pg(STAT_PROJ); ly, _ = pg(STAT_LAST_YEAR); cur, n = pg(STAT_SEASON)
    parts = [x for x in (proj, ly) if x]
    base = sum(parts)/len(parts) if parts else (cur or 0)
    if n and cur is not None: base = (base*20 + cur*n)/(20+n)
    return round(base, 3), {"proj_pg": proj and round(proj,2), "ly_pg": ly and round(ly,2), "cur_pg": cur and round(cur,2), "gp": n}

def optimize(players, spid, sched, vals, now_ms, latest):
    movable = [p for p in players if p["slot"] != IR]
    inst = []
    for sl, c in SLOTS.items(): inst += [sl]*c
    inst += [BENCH]*max(BENCH_N, len(movable))      # bench unlimited
    info, rows = {}, []
    for p in movable:
        games = sched.get(str(p["pro"]), {}).get("games", {}).get(str(spid), [])
        has = bool(games)
        locked = spid == latest and any(d <= now_ms + 60000 for d in games)
        forced = (p["name"] in NEVER_START or unavailable(p)) and p["name"] not in FORCE_START
        w = vals.get(p["id"], 0.0) if has else 0.0
        info[p["id"]] = dict(has=has, locked=locked, forced=forced, w=w)
        row = []
        for sl in inst:
            stay = 1 if p["slot"] == sl else 0
            if locked and p["slot"] != sl: row.append(BIG); continue
            if sl == BENCH: row.append(-stay); continue
            if sl not in p["elig"] or (forced and not locked): row.append(BIG); continue
            if sl == 5 and not is_goalie(p): row.append(BIG); continue
            row.append(-(w*1000) - stay)
        rows.append(row)
    if len(rows) > len(inst): raise RuntimeError(f"rows {len(rows)} > slots {len(inst)}")
    asg = hungarian(rows); desired = {}
    for i, p in enumerate(movable):
        if rows[i][asg[i]] >= BIG: raise RuntimeError(f"infeasible for {p['name']} spid {spid}")
        desired[p["id"]] = inst[asg[i]]
    return desired, info

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode not in ("plan", "run", "verify"): sys.exit(__doc__)
    s = session()
    boot = roster(s, 0); latest, final = boot["latest"], boot["final"]
    sched = schedule(s)
    players0 = roster(s, latest)["players"]
    vals, vinfo = {}, {}
    for p in players0: vals[p["id"]], vinfo[p["name"]] = value(p)
    names = {p["id"]: p["name"] for p in players0}
    if mode == "run": LOG.write_text("", encoding="utf-8")
    if mode in ("plan", "run"):
        log(f"{datetime.now().isoformat(timespec='seconds')} mode={mode} latest={latest} final={final}")
        for p in sorted(players0, key=lambda x: -vals[x["id"]]):
            flag = " NO-START" if ((unavailable(p) or p["name"] in NEVER_START) and p["name"] not in FORCE_START) and p["slot"] != IR else ""
            log(f"  {SLOTNAME[p['slot']]:4s} {p['name']:22s} {sched.get(str(p['pro']),{}).get('abbrev')} inj={p['inj']} value={vals[p['id']]}{flag}")
    if mode == "verify":
        spids = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else list(range(latest, final+1))
    else:
        lo = int(sys.argv[2]) if len(sys.argv) > 2 else latest
        hi = int(sys.argv[3]) if len(sys.argv) > 3 else final
        spids = list(range(lo, hi+1))
    desired_store = json.loads(DESIRED_PATH.read_text()) if DESIRED_PATH.exists() else {}
    report = {"ok": [], "already": [], "partial": [], "planned": [], "fail": []}
    for spid in spids:
        try:
            now_ms = time.time()*1000
            tx = "ROSTER" if spid == latest else "FUTURE_ROSTER"
            res = None; sit = []; diff = []
            for attempt in range(4):
                pl = roster(s, spid)["players"]
                desired, info = optimize(pl, spid, sched, vals, now_ms, latest)
                diff = [p for p in pl if p["slot"] != IR and desired[p["id"]] != p["slot"] and not info[p["id"]]["locked"]]
                if attempt == 0:
                    desired_store[str(spid)] = {str(k): v for k, v in desired.items()}
                    sit = [names.get(p["id"], p["name"]) for p in pl if p["slot"] != IR and info[p["id"]]["has"] and desired[p["id"]] == BENCH]
                if not diff:
                    res = "already" if attempt == 0 else "ok"; break
                if mode in ("plan", "verify"):
                    if mode == "plan":
                        log(f"  [{spid}] moves: " + "; ".join(f"{p['name']} {SLOTNAME[p['slot']]}->{SLOTNAME[desired[p['id']]]}" for p in diff))
                    res = "planned" if mode == "plan" else "mismatch"; break
                items = sorted([{"playerId": p["id"], "type": "LINEUP", "fromLineupSlotId": p["slot"], "toLineupSlotId": desired[p["id"]]} for p in diff],
                               key=lambda it: 0 if it["toLineupSlotId"] == BENCH else 1)
                payload = {"isLeagueManager": False, "teamId": TEAM, "type": tx, "scoringPeriodId": spid, "executionType": "EXECUTE", "items": items}
                r = post_tx(s, payload, {p["id"]: p["slot"] for p in pl})
                if r["status"] not in (200, 201):
                    log(f"  [{spid}] attempt {attempt} POST {r['status']} n={len(items)} {r['body'][:200]}")
                    if attempt >= 1:
                        for it in items:
                            rr = post_tx(s, {**payload, "items": [it]}, {p["id"]: p["slot"] for p in pl})
                            if rr["status"] not in (200, 201):
                                log(f"    single {names.get(it['playerId'])} {rr['status']} {rr['body'][:160]}")
                time.sleep(0.25)
            else:
                res = "partial"
            entry = {"spid": spid, "date": spid_date(spid), "status": res, "tx": tx, "sit_with_game": sit, "n_moves": len(diff) if res in ("planned","mismatch") else 0}
            if mode == "verify":
                pl = roster(s, spid)["players"]
                entry["lineup"] = {SLOTNAME[sl]: [p["name"] + ("" if sched.get(str(p['pro']),{}).get('games',{}).get(str(spid)) else "*") for p in pl if p["slot"] == sl] for sl in (0,1,2,4,6,5,7,8)}
            key = {"already": "already", "ok": "ok", "partial": "partial", "planned": "planned"}.get(res, "fail")
            report[key].append(entry)
            if mode != "plan" or res != "already":
                log(f"[{spid} {spid_date(spid)}] {res} sit={sit}")
        except SystemExit:
            raise
        except Exception as e:
            log(f"[{spid}] EXCEPTION {e}")
            report["fail"].append({"spid": spid, "date": spid_date(spid), "status": "exception", "err": str(e)})
    if mode == "run": DESIRED_PATH.write_text(json.dumps(desired_store))
    (DATA / f"lineup_{mode}_report.json").write_text(json.dumps(report, indent=1))
    log(f"DONE mode={mode} spids={spids[0]}..{spids[-1]} " + " ".join(f"{k}={len(v)}" for k, v in report.items()))

if __name__ == "__main__":
    main()
