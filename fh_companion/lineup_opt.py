"""lineup_opt.py - pure (no network) daily lineup slot assignment.

Objective: start the set of players with the highest total projected value for the day, using every player's
full ESPN eligibleSlots, so a multi-position bench player gets in whenever shifting starters between slots makes
room (e.g. bench C/LW with a game -> LW slot; the LW/RW who held it -> RW slot; RW starter with no game -> bench).

Method: max-weight bipartite assignment (Hungarian) players x slot instances, then an independent
exchange audit (`find_improvement`) that searches every shift chain bench -> slot -> slot ... -> bench; because a
player's value does not depend on which slot he fills, "no improving chain exists" proves the lineup is optimal.
If the audit ever finds a chain it is applied (belt and braces) and reported.

Cost ordering (strict): 1) total value of started players with games, 2) fewest moves from the current lineup.
Players with no game that day are worth 0 and never displace a player with a game (game players are floored at
GAME_FLOOR > 0). Locked players (game started) never move; "forced" players (unavailable / never-start) can only
sit unless locked in place. IR slot entries are never passed in.
"""
BENCH = 7
GOALIE_SLOT = 5
BIG = 10**12
SCALE = 100000        # value (3 dp) * SCALE dominates the per-player stay bonus of 1
GAME_FLOOR = 0.01     # a player with a game always beats a player without one


def hungarian(a):
    """Min-cost assignment for an n x m cost matrix (n <= m). Returns column index per row."""
    n, m = len(a), len(a[0])
    u = [0]*(n+1); v = [0]*(m+1); p = [0]*(m+1); way = [0]*(m+1)
    for i in range(1, n+1):
        p[0] = i; j0 = 0; minv = [float('inf')]*(m+1); used = [False]*(m+1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = float('inf'); j1 = 0
            for j in range(1, m+1):
                if not used[j]:
                    cur = a[i0-1][j-1]-u[i0]-v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(m+1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    ans = [None]*n
    for j in range(1, m+1):
        if p[j]: ans[p[j]-1] = j-1
    return ans


def is_goalie(p):
    return GOALIE_SLOT in p["elig"] and not any(s in p["elig"] for s in (0, 1, 2, 3, 4))


def can_play(p, sl):
    if sl == BENCH: return True
    if sl not in p["elig"]: return False
    if sl == GOALIE_SLOT and not is_goalie(p): return False
    return True


def weight(inf):
    return max(inf["w"], GAME_FLOOR) if inf["has"] else 0.0


def assign(movable, info, slot_counts, bench_n=6):
    """movable: [{id, slot, elig, name}] (no IR entries); info[id] = {has, locked, forced, w}.
    slot_counts: {active slot id: count}. Returns {player id: slot id}."""
    movable = sorted(movable, key=lambda p: p["id"])            # deterministic
    inst = []
    for sl in sorted(slot_counts):
        if sl not in (BENCH, 8) and slot_counts[sl] > 0: inst += [sl]*slot_counts[sl]
    inst += [BENCH]*max(bench_n, len(movable))
    rows = []
    for p in movable:
        f = info[p["id"]]; w = weight(f); row = []
        for sl in inst:
            stay = 1 if p["slot"] == sl else 0
            if f["locked"] and p["slot"] != sl: row.append(BIG); continue
            if sl == BENCH: row.append(-stay); continue
            if not can_play(p, sl) or (f["forced"] and not f["locked"]): row.append(BIG); continue
            row.append(-round(w*SCALE) - stay)
        rows.append(row)
    asg = hungarian(rows); desired = {}
    for i, p in enumerate(movable):
        if rows[i][asg[i]] >= BIG: raise RuntimeError(f"infeasible for {p['name']}")
        desired[p["id"]] = inst[asg[i]]
    # independent audit: apply any improving shift chain the assignment missed (should never trigger)
    for _ in range(len(movable)):
        chain = find_improvement(movable, info, slot_counts, desired)
        if not chain: break
        for pid, _frm, to in chain: desired[pid] = to
    return desired


def lineup_value(desired, info):
    return round(sum(weight(info[pid]) for pid, sl in desired.items() if sl != BENCH and info[pid]["has"]), 3)


def find_improvement(movable, info, slot_counts, desired):
    """Search shift chains that raise total value: a benched starter-candidate B enters slot s1; its holder
    moves to s2 ... the last displaced player goes to the bench (or the chain ends in an empty slot).
    Returns [(pid, from_slot, to_slot), ...] for the best chain found, or None if the lineup is optimal."""
    byid = {p["id"]: p for p in movable}
    free = dict((sl, c) for sl, c in slot_counts.items() if sl not in (BENCH, 8))
    holders = {}
    for pid, sl in desired.items():
        if sl != BENCH:
            free[sl] = free.get(sl, 0) - 1; holders.setdefault(sl, []).append(pid)
    def movable_ok(pid):
        f = info[pid]; return not f["locked"]
    best = [0.0, None]
    def dfs(pid, frm, path, seen, w_in):
        p = byid[pid]
        for sl in sorted(slot_counts):
            if sl in (BENCH, 8) or sl == frm or not can_play(p, sl): continue
            if info[pid]["forced"]: continue
            step = path + [(pid, frm, sl)]
            if free.get(sl, 0) > 0:                                  # empty slot ends the chain
                if w_in > best[0] + 1e-9: best[0], best[1] = w_in, step
                continue
            for h in holders.get(sl, []):
                if h in seen or not movable_ok(h): continue
                # option A: holder goes to bench
                gain = w_in - weight(info[h])
                if gain > best[0] + 1e-9: best[0], best[1] = gain, step + [(h, sl, BENCH)]
                # option B: holder shifts to another slot (chain continues)
                if len(seen) < 8: dfs(h, sl, step, seen | {h}, w_in)
    for p in movable:
        pid = p["id"]
        if desired[pid] == BENCH and info[pid]["has"] and movable_ok(pid) and not info[pid]["forced"]:
            dfs(pid, BENCH, [], {pid}, weight(info[pid]))
    return best[1]


def shift_chains(movable, desired, names=None, slotname=None):
    """Human-readable dual-eligibility shifts: bench players who start only because a starter changed slots."""
    names = names or {p["id"]: p["name"] for p in movable}
    cur = {p["id"]: p["slot"] for p in movable}
    sn = slotname or {}
    nm = lambda sl: sn.get(sl, str(sl))
    out = []
    shifted = [pid for pid in desired if cur[pid] not in (BENCH, desired[pid]) and desired[pid] != BENCH]
    entered = [pid for pid in desired if cur[pid] == BENCH and desired[pid] != BENCH]
    if shifted and entered:
        out.append("dual-eligibility shift: " + ", ".join(f"{names[i]} BN->{nm(desired[i])}" for i in entered)
                   + " made possible by " + ", ".join(f"{names[i]} {nm(cur[i])}->{nm(desired[i])}" for i in shifted))
    return out
