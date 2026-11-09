"""Guard test: uses a fake session that records any POST attempt; nothing reaches ESPN.
Run: python3 -m tests.test_guard   (works with placeholder config; no network, no cookies needed)"""
import os
os.environ.setdefault("FH_LEAGUE_ID", "1")
os.environ.setdefault("FH_TEAM_ID", "2")
from fh_companion import espn_common as ec

TEAM = ec.TEAM


class FakeSession:
    def __init__(self): self.calls = 0
    def post(self, *a, **k): self.calls += 1; raise AssertionError("POST WOULD HAVE BEEN SENT")


def main():
    roster = {1001: 0, 1002: 7, 1003: 8}   # C, BN, IR (fake player ids)
    base = {"isLeagueManager": False, "teamId": TEAM, "scoringPeriodId": 22, "executionType": "EXECUTE"}
    cases = {
     "FREEAGENT add/drop": {**base, "type": "FREEAGENT", "items": [{"playerId": 9999, "type": "ADD", "toTeamId": TEAM}, {"playerId": 1002, "type": "DROP", "fromTeamId": TEAM}]},
     "WAIVER claim": {**base, "type": "WAIVER", "items": [{"playerId": 9999, "type": "ADD", "toTeamId": TEAM}]},
     "ROSTER w/ DROP item": {**base, "type": "ROSTER", "items": [{"playerId": 1002, "type": "DROP", "fromLineupSlotId": 7, "toLineupSlotId": 7}]},
     "ROSTER w/ ADD item": {**base, "type": "ROSTER", "items": [{"playerId": 9999, "type": "ADD", "fromLineupSlotId": 7, "toLineupSlotId": 7}]},
     "LINEUP into IR": {**base, "type": "ROSTER", "items": [{"playerId": 1002, "type": "LINEUP", "fromLineupSlotId": 7, "toLineupSlotId": 8}]},
     "LINEUP out of IR": {**base, "type": "ROSTER", "items": [{"playerId": 1003, "type": "LINEUP", "fromLineupSlotId": 8, "toLineupSlotId": 7}]},
     "LINEUP non-roster player": {**base, "type": "ROSTER", "items": [{"playerId": 9999, "type": "LINEUP", "fromLineupSlotId": 7, "toLineupSlotId": 0}]},
     "LINEUP other team": {**base, "teamId": TEAM + 1, "type": "ROSTER", "items": [{"playerId": 1002, "type": "LINEUP", "fromLineupSlotId": 7, "toLineupSlotId": 0}]},
     "LINEUP no roster given": None,
    }
    fs = FakeSession(); fails = 0
    for name, pl in cases.items():
        try:
            if pl is None: ec.post_tx(fs, {**base, "type": "ROSTER", "items": [{"playerId": 1002, "type": "LINEUP", "fromLineupSlotId": 7, "toLineupSlotId": 0}]})
            else: ec.post_tx(fs, pl, roster)
            print(f"FAIL  {name}: not refused"); fails += 1
        except ec.GuardRefused as e: print(f"PASS  {name}: {e}")
    ok = {**base, "type": "FUTURE_ROSTER", "items": [{"playerId": 1002, "type": "LINEUP", "fromLineupSlotId": 7, "toLineupSlotId": 0}, {"playerId": 1001, "type": "LINEUP", "fromLineupSlotId": 0, "toLineupSlotId": 7}]}
    print("PASS  valid lineup swap accepted by guard" if ec.guard_lineup_payload(ok, roster) else "FAIL")
    print(f"POST attempts reaching network layer: {fs.calls}")
    passed = fails == 0 and fs.calls == 0
    print("GUARD TEST:", "ALL PASS" if passed else "FAILED")
    return passed


def test_guard():  # pytest entry point
    assert main()


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
