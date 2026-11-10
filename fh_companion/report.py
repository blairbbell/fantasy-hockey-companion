"""report - read-only, self-contained HTML status page for your ESPN fantasy hockey team.

Sections:
  1. Daily run status   - from LAST_STATUS (+ the latest daily_YYYYMMDD.log). Red when FAIL, missing or stale.
  2. Transactions & IR  - pending waiver claims, adds used/left this matchup week, IR players, and a warning
                          when a healthy player sits in an IR slot (ESPN then blocks every add).
  3. Recent form        - last-7 / last-15 day points per game next to ESPN's projection per game.

READ-ONLY: this module never imports the write helpers and uses an HTTP session that refuses anything but GET.
Usage:
  python -m fh_companion.report                         # live read-only pull -> report_out (config)
  python -m fh_companion.report --fixture f.json        # offline render from a saved/fake snapshot
  python -m fh_companion.report --wait-for-today 30     # wait up to 30 min for today's LAST_STATUS first
  options: --out PATH   --save-snapshot PATH   --json PATH
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import CFG

SLOTNAME = {0: "C", 1: "LW", 2: "RW", 3: "F", 4: "D", 5: "G", 6: "UTIL", 7: "BN", 8: "IR"}
SLOT_ORDER = [0, 1, 2, 3, 4, 6, 5, 7, 8]
IR_SLOT = 8
IR_ELIGIBLE = {"OUT", "INJURY_RESERVE", "SUSPENSION"}   # anything else in an IR slot blocks adds


def _inj(e):
    """Player injury status. The roster entry's own injuryStatus is often a placeholder ("NORMAL"), so the
    player record wins; missing/NORMAL means healthy (ACTIVE)."""
    for v in (e.get("player", {}).get("injuryStatus"), e.get("injuryStatus")):
        if v and v != "NORMAL":
            return v
    return "ACTIVE"
DEFAULT_ADDS_LIMIT = 4


# ---------------------------------------------------------------- read-only HTTP ----------
class ReadOnlySession:
    """Wraps requests.Session; only GET is possible. There is no post/put/delete method at all."""

    def __init__(self, cookies: dict):
        import requests  # imported lazily so fixture mode and tests need no network stack
        self._s = requests.Session()
        self._s.cookies.set("espn_s2", cookies["espn_s2"], domain=".espn.com")
        self._s.cookies.set("SWID", cookies["SWID"], domain=".espn.com")
        self._s.headers.update({"User-Agent": "Mozilla/5.0 fantasy-hockey-companion-report",
                                "Accept": "application/json"})

    def get_json(self, url: str, params=None, filt=None):
        if not url.startswith("https://lm-api-reads.fantasy.espn.com/"):
            raise ValueError("report only reads from lm-api-reads")
        h = {"x-fantasy-filter": json.dumps(filt)} if filt else {}
        r = self._s.request("GET", url, params=params, headers=h, timeout=60)
        if r.status_code in (401, 403):
            raise SystemExit(f"ESPN returned {r.status_code}: cookies expired or invalid (see README).")
        r.raise_for_status()
        return r.json()


def _cookies(cfg) -> dict:
    s2, swid = os.environ.get("ESPN_S2"), os.environ.get("ESPN_SWID")
    if s2 and swid:
        return {"espn_s2": s2, "SWID": swid}
    p = Path(cfg["cookies_file"])
    if not p.exists():
        raise SystemExit(f"No ESPN cookies: set ESPN_S2/ESPN_SWID or create {p.name} (see README.md)")
    return json.loads(p.read_text(encoding="utf-8"))


def fetch_snapshot(cfg) -> dict:
    """Three or four read-only GETs. Returns a compact snapshot (no cookies, no member/owner data)."""
    if not cfg["league_id"] or not cfg["team_id"]:
        raise SystemExit("Set league_id and team_id in config.json (see README.md).")
    reads = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/{cfg['season']}"
    lurl = f"{reads}/segments/0/leagues/{cfg['league_id']}"
    s = ReadOnlySession(_cookies(cfg))
    L = s.get_json(lurl, params=[("view", v) for v in ("mStatus", "mSettings", "mRoster", "mTeam")])
    sp = L.get("scoringPeriodId") or L["status"].get("latestScoringPeriod")
    tx = s.get_json(lurl, params={"view": "mTransactions2", "scoringPeriodId": sp},
                    filt={"transactions": {"filterType": {"value": ["FREEAGENT", "WAIVER", "WAIVER_ERROR"]}}})
    team = next(t for t in L["teams"] if t["id"] == cfg["team_id"])
    mine = [t for t in tx.get("transactions", []) if t.get("teamId") == cfg["team_id"]]
    want = {i.get("playerId") for t in mine for i in t.get("items", [])}
    have = {e["playerId"] for e in team["roster"]["entries"]}
    players = {}
    missing = sorted(p for p in want - have if p)
    if missing:
        try:  # names/waiver times for players not on your roster (e.g. the player a claim would add)
            j = s.get_json(lurl, params={"view": "kona_player_info"}, filt={"players": {"filterIds": {"value": missing}}})
        except Exception as e:  # noqa: BLE001 - optional detail; the page still renders without it
            print(f"note: player lookup failed ({type(e).__name__}); showing ids", file=sys.stderr)
            j = {}
        for ppe in j.get("players", []):
            p = ppe.get("player", {})
            players[str(p.get("id"))] = {"name": p.get("fullName"), "status": ppe.get("status"),
                                         "waiverProcessDate": ppe.get("waiverProcessDate"),
                                         "injuryStatus": p.get("injuryStatus")}
    st = L.get("settings", {})
    cur = L["status"].get("currentMatchupPeriod")
    entries = []
    for e in team["roster"]["entries"]:
        p = e["playerPoolEntry"]["player"]
        entries.append({"playerId": e["playerId"], "lineupSlotId": e["lineupSlotId"],
                        "injuryStatus": e.get("injuryStatus") or p.get("injuryStatus"),
                        "player": {k: p.get(k) for k in ("id", "fullName", "eligibleSlots", "proTeamId",
                                                          "injured", "injuryStatus", "stats")}})
    return {
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "season": cfg["season"],
        "scoringPeriodId": sp,
        "currentMatchupPeriod": cur,
        "matchupPeriods": st.get("scheduleSettings", {}).get("matchupPeriods", {}),
        "acquisitionSettings": st.get("acquisitionSettings", {}),
        "team": {"id": team["id"], "name": team.get("name") or "",
                 "transactionCounter": team.get("transactionCounter", {}),
                 "waiverRank": team.get("waiverRank"), "entries": entries},
        "transactions": mine,
        "players": players,
    }


# ---------------------------------------------------------------- section 1: status -------
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?: (\S+))?\s+(.*)$")


def read_status(status_file, log_dir, now=None, stale_hours=26) -> dict:
    now = now or datetime.now()
    status_file, log_dir = Path(status_file), Path(log_dir)
    out = {"file": str(status_file), "state": "missing", "level": "bad", "line": None, "time": None,
           "age_h": None, "result": None, "sp": None, "set": None, "verify": None, "not_active": None,
           "log_name": None, "log_tail": []}
    logs = sorted(log_dir.glob("daily_*.log")) if log_dir.is_dir() else []
    if logs:
        out["log_name"] = logs[-1].name
        try:
            out["log_tail"] = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        except OSError:
            pass
    if not status_file.exists():
        out["reason"] = "LAST_STATUS not found - the daily run has not written a status yet."
        return out
    line = status_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    line = line[-1] if line else ""
    out["line"] = line
    m = _TS.match(line)
    if not m:
        out.update(state="unparsed", reason="LAST_STATUS could not be parsed.")
        return out
    t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    rest = m.group(3)
    out["time"] = f"{m.group(1)} {m.group(2) or ''}".strip()
    out["age_h"] = round((now - t).total_seconds() / 3600, 1)
    out["result"] = rest.split("|")[0].strip()
    ok = rest.startswith("OK")
    if (mm := re.search(r"\bsp (\d+)", rest)):
        out["sp"] = int(mm.group(1))
    for part in rest.split("|"):
        part = part.strip()
        if part.startswith("set:"):
            out["set"] = _counts(part[4:])
        elif part.startswith("verify:"):
            out["verify"] = _counts(part[7:])
        elif part.startswith("not-active:"):
            out["not_active"] = part[11:].strip()
    fails = sum((c or {}).get("fail", 0) + (c or {}).get("partial", 0) for c in (out["set"], out["verify"]))
    if not ok:
        out.update(state="fail", level="bad", reason="The last daily run reported a failure.")
    elif out["age_h"] > stale_hours:
        out.update(state="stale", level="bad", reason=f"Last run is {out['age_h']} h old (limit {stale_hours} h) - the daily job may not have run.")
    elif fails:
        out.update(state="fail", level="bad", reason=f"{fails} lineup day(s) failed or partial.")
    else:
        out.update(state="ok", level="good", reason="Last daily run succeeded.")
    return out


def _counts(s):
    d = {k: int(v) for k, v in re.findall(r"\b(ok|already|partial|planned|fail)=(\d+)", s)}
    if (m := re.search(r"spids=(\d+)\.\.(\d+)", s)):
        d["from"], d["to"] = int(m.group(1)), int(m.group(2))
    d["days"] = d.get("ok", 0) + d.get("already", 0)
    return d or None


# ---------------------------------------------------------------- section 2: tx / IR -----
def _when(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000).astimezone().strftime("%a %b %d, %I:%M %p %Z").replace(" 0", " ")


def transactions_ir(snap, cfg) -> dict:
    team = snap["team"]
    names = {e["playerId"]: e["player"].get("fullName") for e in team["entries"]}
    names.update({int(k): v.get("name") for k, v in snap.get("players", {}).items()})
    pending = []
    for t in snap.get("transactions", []):
        if not (t.get("status") == "PENDING" or t.get("isPending")):
            continue
        items = t.get("items", [])
        adds = [i["playerId"] for i in items if i.get("type") == "ADD"]
        drops = [i["playerId"] for i in items if i.get("type") == "DROP"]
        proc = next((snap["players"].get(str(p), {}).get("waiverProcessDate") for p in adds
                     if snap.get("players", {}).get(str(p), {}).get("waiverProcessDate")), None)
        pending.append({"type": t.get("type"), "add": [names.get(p, f"#{p}") for p in adds],
                        "drop": [names.get(p, f"#{p}") for p in drops],
                        "proposed": _when(t.get("proposedDate")), "processes": _when(t.get("processDate") or proc)})
    acq = snap.get("acquisitionSettings", {})
    cur = snap.get("currentMatchupPeriod")
    limit, src = cfg.get("adds_limit"), "config"
    if limit is None:
        per = acq.get("matchupAcquisitionLimit")
        days = len(snap.get("matchupPeriods", {}).get(str(cur), []) or [])
        if per and per > 0 and acq.get("matchupLimitPerScoringPeriod") and days:
            # ESPN stores the weekly limit per scoring period; the week's limit is that times the week's length
            limit, src = round(per * days), "league settings"
        elif per and per >= 1:
            limit, src = int(per), "league settings"
        else:
            limit, src = DEFAULT_ADDS_LIMIT, "default"
    used = int((team.get("transactionCounter", {}).get("matchupAcquisitionTotals") or {}).get(str(cur), 0))
    ir, healthy = [], []
    for e in team["entries"]:
        if e["lineupSlotId"] != IR_SLOT:
            continue
        inj = _inj(e)
        row = {"name": e["player"].get("fullName"), "inj": inj, "eligible": inj in IR_ELIGIBLE}
        ir.append(row)
        if not row["eligible"]:
            healthy.append(row)
    return {"pending": pending, "adds_used": used, "adds_limit": limit, "adds_limit_source": src,
            "adds_left": max(limit - used, 0), "matchup": cur, "ir": ir, "healthy_in_ir": healthy,
            "waiver_rank": team.get("waiverRank")}


# ---------------------------------------------------------------- section 3: form ---------
def _goalie_pts(st, gs):
    return (gs["W"] * st.get("1", 0) + gs["GA"] * st.get("4", 0) + gs["SV"] * st.get("6", 0)
            + gs["SO"] * st.get("7", 0) + gs["OTL"] * st.get("9", 0))


def recent_form(snap, cfg, abbrevs=None) -> list:
    """Same conventions as analyze.py: skater points = ESPN appliedTotal (league-scored); goalie points are
    recalculated from config goalie_scoring; GP = stat 34 (skaters) or stat 0 (goalies)."""
    yr, gs, abbrevs = snap["season"], cfg["goalie_scoring"], abbrevs or {}
    rows = []
    for e in snap["team"]["entries"]:
        p = e["player"]
        el = p.get("eligibleSlots") or []
        isG = 5 in el and not any(s in el for s in (0, 1, 2, 4))
        S = {s.get("id"): s for s in p.get("stats") or []}

        def ppg(split):
            s = S.get(f"{split}{yr}")
            if not s:
                return None, None
            st = s.get("stats") or {}
            gp = (st.get("0", st.get("34", 0)) if isG else st.get("34", 0)) or 0
            pts = _goalie_pts(st, gs) if isG and st else (s.get("appliedTotal") or 0)
            return int(gp), (round(pts / gp, 2) if gp else None)

        g7, p7 = ppg("01")
        g15, p15 = ppg("02")
        gse, pse = ppg("00")
        _, pj = ppg("10")
        trend = round(p15 - pj, 2) if p15 is not None and pj is not None else None
        rows.append({"slot": SLOTNAME.get(e["lineupSlotId"], str(e["lineupSlotId"])), "slot_id": e["lineupSlotId"],
                     "name": p.get("fullName"), "pos": "/".join(n for i, n in [(0, "C"), (1, "LW"), (2, "RW"), (4, "D"), (5, "G")] if i in el),
                     "team": abbrevs.get(p.get("id")) or "", "inj": _inj(e),
                     "gp7": g7, "ppg7": p7, "gp15": g15, "ppg15": p15, "season_ppg": pse, "proj_ppg": pj, "trend": trend})
    rows.sort(key=lambda r: (SLOT_ORDER.index(r["slot_id"]) if r["slot_id"] in SLOT_ORDER else 99, -(r["proj_ppg"] or 0)))
    return rows


def team_abbrevs(analysis_file) -> dict:
    try:
        d = json.loads(Path(analysis_file).read_text(encoding="utf-8"))
        return {r["id"]: r.get("team") for r in d.get("roster", []) + d.get("fa", []) if r.get("team")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# ---------------------------------------------------------------- HTML --------------------
CSS = """body{font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6f9;color:#1d2430}
main{max-width:980px;margin:0 auto;padding:18px}h1{font-size:22px;margin:0 0 4px}.sub{color:#5b6576;margin-bottom:16px}
section{background:#fff;border-radius:10px;box-shadow:0 1px 3px #0002;padding:14px 18px;margin-bottom:16px}
h2{font-size:17px;margin:0 0 10px}.card{border-left:6px solid;padding:10px 14px;border-radius:6px}
.good{border-color:#1f9d55;background:#e9f8ef}.bad{border-color:#d0342c;background:#fdecea}.warn{border-color:#e69b00;background:#fff6e0}
.big{font-size:20px;font-weight:700}.alert{background:#d0342c;color:#fff;padding:12px 14px;border-radius:8px;font-weight:600;margin-bottom:10px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:5px 7px;border-bottom:1px solid #e5e8ee;text-align:left}
th{background:#f0f2f6;font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.up{color:#1f7a3f;font-weight:600}.dn{color:#b42318;font-weight:600}
.muted{color:#6b7280}.pill{display:inline-block;padding:1px 8px;border-radius:10px;background:#eef1f5;font-size:12px}
.pill.inj{background:#fde2e1;color:#8a1c14}details pre{white-space:pre-wrap;font-size:12px;background:#f6f7f9;padding:8px;border-radius:6px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;margin-top:8px}"""


def _e(x):
    return html.escape("" if x is None else str(x))


def _num(x):
    return "&ndash;" if x is None else f"{x:.2f}"


def render(model) -> str:
    s, t, form = model["status"], model["tx"], model["form"]
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Fantasy hockey report</title><style>{CSS}</style></head><body><main>",
           f"<h1>Fantasy hockey report</h1><div class='sub'>{_e(model.get('team_label'))} &middot; generated {_e(model['generated'])}"
           f" &middot; read-only snapshot</div>"]
    # 1. status
    label = {"ok": "OK", "fail": "FAIL", "stale": "STALE", "missing": "MISSING", "unparsed": "UNKNOWN"}[s["state"]]
    out.append(f"<section id='status'><h2>Daily lineup run</h2><div class='card {s['level']}'><div class='big'>{label}</div>"
               f"<div>{_e(s.get('reason'))}</div><div class='kv'>")
    kv = [("Last run", s["time"]), ("Age", f"{s['age_h']} h" if s["age_h"] is not None else None), ("Result", s["result"]),
          ("Scoring period", s["sp"])]
    if s["set"]:
        c = s["set"]
        kv.append(("Days set", f"{c.get('days', 0)} (periods {c.get('from', '?')}&ndash;{c.get('to', '?')}): "
                               f"changed {c.get('ok', 0)}, already right {c.get('already', 0)}"))
        kv.append(("Fails", f"set {c.get('fail', 0)} fail / {c.get('partial', 0)} partial"
                            + (f"; verify {s['verify'].get('fail', 0)} fail / {s['verify'].get('partial', 0)} partial" if s["verify"] else "")))
    if s["not_active"]:
        kv.append(("Not active", s["not_active"]))
    for k, v in kv:
        if v is not None:
            out.append(f"<div class='muted'>{_e(k)}</div><div>{v if k == 'Days set' else _e(v)}</div>")
    out.append("</div></div>")
    if s["log_tail"]:
        out.append(f"<details><summary>Latest log: {_e(s['log_name'])} (last {len(s['log_tail'])} lines)</summary><pre>"
                   + _e("\n".join(s["log_tail"])) + "</pre></details>")
    out.append("</section>")
    # 2. transactions / IR
    out.append("<section id='transactions'><h2>Pending moves &amp; IR</h2>")
    for h in t["healthy_in_ir"]:
        out.append(f"<div class='alert'>&#9888; {_e(h['name'])} is in an IR slot but is {_e(h['inj'])} (not IR-eligible). "
                   "ESPN blocks every add and waiver claim until this is fixed, and the daily job cannot make IR moves "
                   "&mdash; move this player out of IR by hand.</div>")
    lvl = "bad" if t["adds_left"] == 0 else "good"
    out.append(f"<div class='card {lvl}'><span class='big'>{t['adds_left']} of {t['adds_limit']}</span> adds left this matchup week "
               f"<span class='muted'>(week {_e(t['matchup'])}; {t['adds_used']} used; limit from {_e(t['adds_limit_source'])}"
               + (f"; waiver priority {_e(t['waiver_rank'])}" if t.get("waiver_rank") else "") + ")</span></div>")
    out.append("<h3>Pending claims</h3>")
    if t["pending"]:
        out.append("<table><tr><th>Type</th><th>Add</th><th>Drop</th><th>Submitted</th><th>Processes</th></tr>")
        for p in t["pending"]:
            out.append(f"<tr><td>{_e(p['type'])}</td><td>{_e(', '.join(p['add']))}</td><td>{_e(', '.join(p['drop'])) or '&ndash;'}</td>"
                       f"<td>{_e(p['proposed'])}</td><td>{_e(p['processes'] or 'at next waiver run')}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p class='muted'>No pending waiver claims or add/drops.</p>")
    out.append("<h3>Injured reserve</h3>")
    if t["ir"]:
        out.append("<table><tr><th>Player</th><th>Status</th><th>IR-eligible</th></tr>")
        for r in t["ir"]:
            out.append(f"<tr><td>{_e(r['name'])}</td><td><span class='pill{' inj' if r['eligible'] else ''}'>{_e(r['inj'])}</span></td>"
                       f"<td>{'yes' if r['eligible'] else '<b class=dn>NO</b>'}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p class='muted'>IR slots are empty.</p>")
    out.append("</section>")
    # 3. form
    out.append("<section id='form'><h2>Recent form vs ESPN projection</h2><p class='muted'>Points per game under league scoring. "
               "Trend = last-15 PPG minus ESPN projected PPG.</p><table><tr><th>Slot</th><th>Player</th><th>Pos</th><th>Team</th>"
               "<th class=n>L7 GP</th><th class=n>L7 PPG</th><th class=n>L15 GP</th><th class=n>L15 PPG</th><th class=n>Season PPG</th>"
               "<th class=n>ESPN proj PPG</th><th class=n>Trend</th></tr>")
    for r in form:
        tr = r["trend"]
        cls = "" if tr is None or abs(tr) < 0.25 else (" up" if tr > 0 else " dn")
        inj = "" if r["inj"] == "ACTIVE" else f" <span class='pill inj'>{_e(r['inj'])}</span>"
        out.append(f"<tr><td>{_e(r['slot'])}</td><td>{_e(r['name'])}{inj}</td><td>{_e(r['pos'])}</td><td>{_e(r['team'])}</td>"
                   f"<td class=n>{_e(r['gp7'] if r['gp7'] is not None else '')}</td><td class=n>{_num(r['ppg7'])}</td>"
                   f"<td class=n>{_e(r['gp15'] if r['gp15'] is not None else '')}</td><td class=n>{_num(r['ppg15'])}</td>"
                   f"<td class=n>{_num(r['season_ppg'])}</td><td class=n>{_num(r['proj_ppg'])}</td>"
                   f"<td class='n{cls}'>{'&ndash;' if tr is None else f'{tr:+.2f}'}</td></tr>")
    out.append("</table></section><p class='muted'>Unofficial tool, not affiliated with ESPN. This page makes no changes to your team.</p>"
               "</main></body></html>")
    return "\n".join(out)


def build_model(snap, cfg, now=None) -> dict:
    now = now or datetime.now()
    return {"generated": now.astimezone().strftime("%Y-%m-%d %I:%M %p %Z"),
            "team_label": snap["team"].get("name") or f"Team {snap['team']['id']}",
            "status": read_status(cfg["status_file"], cfg["log_dir"], now=now, stale_hours=cfg.get("stale_hours", 26)),
            "tx": transactions_ir(snap, cfg),
            "form": recent_form(snap, cfg, team_abbrevs(cfg["analysis_file"]) or {int(k): v for k, v in snap.get("abbrevs", {}).items()})}


def wait_for_today(status_file, minutes):
    """Wait (max `minutes`) until LAST_STATUS has been written today, so the page reflects today's run."""
    deadline = time.time() + minutes * 60
    today = datetime.now().date()
    while time.time() < deadline:
        p = Path(status_file)
        if p.exists() and datetime.fromtimestamp(p.stat().st_mtime).date() == today:
            return True
        time.sleep(30)
    return False


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a read-only HTML report (no ESPN writes).")
    ap.add_argument("--fixture", help="render from a snapshot JSON instead of pulling from ESPN")
    ap.add_argument("--out", help="output HTML path (default: config report_out)")
    ap.add_argument("--json", help="also write the rendered model as JSON here")
    ap.add_argument("--save-snapshot", help="save the pulled snapshot JSON here (private data, keep git-ignored)")
    ap.add_argument("--wait-for-today", type=float, default=0, metavar="MIN",
                    help="wait up to MIN minutes for today's LAST_STATUS before rendering")
    a = ap.parse_args(argv)
    cfg = CFG
    if a.wait_for_today:
        if not wait_for_today(cfg["status_file"], a.wait_for_today):
            print("note: today's LAST_STATUS not found in time; rendering anyway (will show stale)", file=sys.stderr)
    snap = json.loads(Path(a.fixture).read_text(encoding="utf-8")) if a.fixture else fetch_snapshot(cfg)
    if a.save_snapshot:
        _atomic_write(Path(a.save_snapshot), json.dumps(snap))
    model = build_model(snap, cfg)
    out = Path(a.out) if a.out else Path(cfg["report_out"])
    _atomic_write(out, render(model))
    if a.json:
        _atomic_write(Path(a.json), json.dumps(model, indent=1))
    print(f"report: status={model['status']['state']} pending={len(model['tx']['pending'])} "
          f"adds_left={model['tx']['adds_left']}/{model['tx']['adds_limit']} ir={len(model['tx']['ir'])} "
          f"healthy_in_ir={len(model['tx']['healthy_in_ir'])} roster={len(model['form'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
