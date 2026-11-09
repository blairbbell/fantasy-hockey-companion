"""Shared ESPN fantasy hockey API helpers (requests + espn_s2/SWID cookies).

Auth uses the two cookies ESPN sets for a logged-in browser session: `espn_s2` and `SWID`.
They are read from environment variables (ESPN_S2 / ESPN_SWID) or from a git-ignored JSON file.
Values are never printed or logged.
"""
from __future__ import annotations
import json
import os
import sys
import time

import requests

from .config import CFG, require_ids

LEAGUE, SEASON, TEAM = CFG["league_id"], CFG["season"], CFG["team_id"]
DATA = CFG["data_dir"]
READS = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/{SEASON}"
LEAGUE_URL = f"{READS}/segments/0/leagues/{LEAGUE}"
WRITES = (f"https://lm-api-writes.fantasy.espn.com/apis/v3/games/fhl/seasons/{SEASON}"
          f"/segments/0/leagues/{LEAGUE}/transactions/")
EXPIRED_MSG = ("ESPN returned {code}: cookies expired or invalid. Re-copy espn_s2 and SWID from a logged-in "
               "browser (see README.md, 'Authentication').")

# ESPN stat-split ids: "00YYYY" = season totals, "01YYYY" = last 7 days, "10YYYY" = projections
STAT_SEASON = f"00{SEASON}"
STAT_L7 = f"01{SEASON}"
STAT_PROJ = f"10{SEASON}"
STAT_LAST_YEAR = f"00{SEASON - 1}"


class CookiesExpired(SystemExit):
    pass


def _cookies() -> dict:
    s2, swid = os.environ.get("ESPN_S2"), os.environ.get("ESPN_SWID")
    if s2 and swid:
        return {"espn_s2": s2, "SWID": swid, "espn_s2_expires": None}
    p = CFG["cookies_file"]
    if not p.exists():
        sys.exit(f"No ESPN cookies: set ESPN_S2/ESPN_SWID or create {p.name} (see README.md)")
    return json.loads(p.read_text(encoding="utf-8"))


def session() -> requests.Session:
    require_ids(CFG)
    DATA.mkdir(parents=True, exist_ok=True)
    c = _cookies()
    s = requests.Session()
    s.cookies.set("espn_s2", c["espn_s2"], domain=".espn.com")
    s.cookies.set("SWID", c["SWID"], domain=".espn.com")
    s.headers.update({"User-Agent": "Mozilla/5.0 fantasy-hockey-companion", "Accept": "application/json"})
    exp = c.get("espn_s2_expires")
    if exp and exp > 0 and exp - time.time() < 7 * 86400:
        print(f"WARNING: espn_s2 expires {time.strftime('%Y-%m-%d', time.localtime(exp))}; refresh soon.", file=sys.stderr)
    return s


def get(s, url, params=None, filt=None):
    h = {"x-fantasy-filter": json.dumps(filt)} if filt else {}
    r = s.get(url, params=params, headers=h, timeout=60)
    if r.status_code in (401, 403):
        print(EXPIRED_MSG.format(code=r.status_code), file=sys.stderr)
        raise CookiesExpired(2)
    r.raise_for_status()
    return r.json()


def league(s, views, **params):
    return get(s, LEAGUE_URL, params=[("view", v) for v in views] + list(params.items()))


def pro_schedule(s):
    return get(s, READS, params={"view": "proTeamSchedules_wl"})


# ---- LINEUP-ONLY GUARD -------------------------------------------------------------------
# Every write to ESPN goes through post_tx(), and post_tx() refuses anything that is not a pure
# lineup-slot move between players already on your roster. No adds/drops/FA/waiver/trade/IR.
ALLOWED_TX_TYPES = {"ROSTER", "FUTURE_ROSTER"}           # ESPN lineup-change transaction types
ACTIVE_OR_BENCH = {0, 1, 2, 3, 4, 5, 6, 7}              # C LW RW F D G UTIL BN  (8 = IR is forbidden)
ALLOWED_PAYLOAD_KEYS = {"isLeagueManager", "teamId", "type", "scoringPeriodId", "executionType", "items"}
ALLOWED_ITEM_KEYS = {"playerId", "type", "fromLineupSlotId", "toLineupSlotId"}


class GuardRefused(Exception):
    pass


def guard_lineup_payload(payload, roster_slots, team_id=None):
    """Raise GuardRefused unless payload is a lineup-only move. roster_slots = {playerId: currentSlotId}
    for your team at the payload's scoring period (freshly read). Nothing is sent if this raises."""
    team_id = TEAM if team_id is None else team_id

    def no(why):
        raise GuardRefused(f"GUARD REFUSED: {why}")

    if not isinstance(payload, dict): no("payload not a dict")
    extra = set(payload) - ALLOWED_PAYLOAD_KEYS
    if extra: no(f"unexpected payload keys {sorted(extra)}")
    if payload.get("type") not in ALLOWED_TX_TYPES: no(f"transaction type {payload.get('type')!r} is not a lineup move")
    if payload.get("teamId") != team_id: no(f"teamId {payload.get('teamId')!r} != {team_id}")
    if payload.get("isLeagueManager") not in (False, None): no("isLeagueManager must be False")
    if payload.get("executionType") != "EXECUTE": no("executionType must be EXECUTE")
    if not isinstance(payload.get("scoringPeriodId"), int): no("scoringPeriodId missing")
    if not isinstance(roster_slots, dict) or not roster_slots: no("no current roster supplied")
    items = payload.get("items")
    if not isinstance(items, list) or not items: no("no items")
    for it in items:
        if not isinstance(it, dict): no("item not a dict")
        extra = set(it) - ALLOWED_ITEM_KEYS
        if extra: no(f"unexpected item keys {sorted(extra)}")
        if it.get("type") != "LINEUP": no(f"item type {it.get('type')!r} is not LINEUP")
        pid, fr, to = it.get("playerId"), it.get("fromLineupSlotId"), it.get("toLineupSlotId")
        if pid not in roster_slots: no(f"player {pid} is not on the current roster")
        if fr not in ACTIVE_OR_BENCH or to not in ACTIVE_OR_BENCH: no(f"player {pid} slot {fr}->{to} touches IR/invalid slot")
        if roster_slots[pid] not in ACTIVE_OR_BENCH: no(f"player {pid} is currently in IR/invalid slot {roster_slots[pid]}")
        if roster_slots[pid] != fr: no(f"player {pid} fromLineupSlotId {fr} != current slot {roster_slots[pid]}")
        if fr == to: no(f"player {pid} no-op move")
    return True


def post_tx(s, payload, roster_slots=None):
    guard_lineup_payload(payload, roster_slots)          # raises GuardRefused -> nothing sent
    r = s.post(WRITES, json=payload, timeout=60, headers={"content-type": "application/json"})
    if r.status_code in (401, 403):
        print(EXPIRED_MSG.format(code=r.status_code), file=sys.stderr)
    return {"status": r.status_code, "body": r.text[:600]}
