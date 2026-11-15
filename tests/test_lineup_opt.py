"""Lineup optimizer tests: fake fixtures only, no network, no cookies.
Run: python3 -m tests.test_lineup_opt   (or pytest)"""
import json
import random
from pathlib import Path

from fh_companion import lineup_opt as lo

FIX = Path(__file__).parent / "fixtures" / "dual_elig_roster.json"
C, LW, RW, D, G, UTIL, BN = 0, 1, 2, 4, 5, 6, 7


def P(pid, slot, elig, name=None):
    extra = [BN] if G in elig else [UTIL, BN]
    return {"id": pid, "slot": slot, "elig": elig + extra, "name": name or f"Sample {pid}"}


def I(has=True, w=1.0, locked=False, forced=False):
    return {"has": has, "w": w, "locked": locked, "forced": forced}


def brute(movable, info, slots):
    """Exhaustive optimum of total started value (game players only)."""
    inst = [sl for sl in sorted(slots) for _ in range(slots[sl])]
    cands = [p for p in movable if info[p["id"]]["has"] and not info[p["id"]]["forced"]]
    best = [0.0]

    def rec(i, used, val):
        best[0] = max(best[0], val)
        if i == len(cands):
            return
        rec(i + 1, used, val)
        p = cands[i]
        for k, sl in enumerate(inst):
            if not used[k] and lo.can_play(p, sl):
                used[k] = True
                rec(i + 1, used, val + lo.weight(info[p["id"]]))
                used[k] = False
    rec(0, [False] * len(inst), 0.0)
    return round(best[0], 3)


def fixture():
    f = json.loads(FIX.read_text())
    mv = [{k: p[k] for k in ("id", "name", "slot", "elig")} for p in f["players"]]
    info = {p["id"]: I(has=p["has"], w=p["w"], forced=p.get("forced", False)) for p in f["players"]}
    slots = {int(k): v for k, v in f["slot_counts"].items()}
    return mv, info, slots, f["bench_n"], {int(k): v for k, v in f["expected"].items()}


def test_fixture_dual_eligibility_shift():
    mv, info, slots, bn, expected = fixture()
    d = lo.assign(mv, info, slots, bench_n=bn)
    assert d == expected
    chains = lo.shift_chains(mv, d, slotname={0: "C", 1: "LW", 2: "RW", 7: "BN"})
    assert chains and "Sample Bench CLW BN->LW" in chains[0] and "Sample Wing LR LW->RW" in chains[0]
    assert lo.find_improvement(mv, info, slots, d) is None


def test_audit_detects_missed_shift():
    mv, info, slots, _, _ = fixture()
    current = {p["id"]: p["slot"] for p in mv}
    chain = lo.find_improvement(mv, info, slots, current)
    assert chain is not None and chain[0][0] == 107


def small_case():
    mv = [P(1, C, [C]), P(2, LW, [LW, RW]), P(3, RW, [RW]), P(4, BN, [C, LW])]
    return mv, {1: I(w=3), 2: I(w=2.5), 3: I(has=False, w=4), 4: I(w=2)}, {C: 1, LW: 1, RW: 1}


def test_locked_player_never_moves():
    mv, inf, slots = small_case()
    inf[2] = I(w=2.5, locked=True)
    d = lo.assign(mv, inf, slots, bench_n=3)
    assert d[2] == LW and d[4] == BN


def test_forced_player_not_started():
    mv, inf, slots = small_case()
    inf[4] = I(w=99, forced=True)
    assert lo.assign(mv, inf, slots, bench_n=3)[4] == BN


def test_no_game_never_displaces_game_player():
    mv = [P(1, LW, [LW]), P(2, BN, [LW])]
    d = lo.assign(mv, {1: I(has=False, w=9), 2: I(w=0.0)}, {LW: 1}, bench_n=2)
    assert d == {1: BN, 2: LW}


def test_tie_keeps_incumbent():
    mv = [P(1, C, [C]), P(2, BN, [C])]
    assert lo.assign(mv, {1: I(w=2.0), 2: I(w=2.0)}, {C: 1}, bench_n=2) == {1: C, 2: BN}


def test_goalie_slot_rules():
    mv = [P(1, BN, [G]), P(2, BN, [C])]
    d = lo.assign(mv, {1: I(w=3), 2: I(w=1)}, {G: 1, C: 1}, bench_n=2)
    assert d == {1: G, 2: C}


def test_random_rosters_match_exhaustive_optimum():
    random.seed(7)
    eligs = [[C], [LW], [RW], [C, LW], [LW, RW], [C, RW], [C, LW, RW], [D]]
    slots = {C: 2, LW: 2, RW: 2, D: 2, UTIL: 1}
    for _ in range(300):
        n = random.randint(6, 12)
        mv = [P(i + 1, BN, random.choice(eligs)) for i in range(n)]
        inf = {i + 1: I(has=random.random() < 0.6, w=round(random.uniform(0, 5), 3)) for i in range(n)}
        d = lo.assign(mv, inf, slots, bench_n=n)
        assert lo.lineup_value(d, inf) == brute(mv, inf, slots)
        assert lo.find_improvement(mv, inf, slots, d) is None


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL  {name}: {e!r}")
    print("LINEUP OPT TESTS:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
