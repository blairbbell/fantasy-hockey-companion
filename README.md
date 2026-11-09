# Fantasy Hockey Companion

A small, local, browserless companion for **ESPN Fantasy Hockey** managers. It runs on any machine
with Python 3 (a Raspberry Pi works well) and:

- **Pulls** your league, roster, matchup, free agents/waivers and the NHL schedule (read-only).
- **Analyzes** roster and free-agent value under your league's scoring and writes `roster.csv`, `fa.csv`, `analysis.json`.
- **Optimizes daily lineups** for the rest of the season (Hungarian assignment over your lineup slots),
  never starting players tagged OUT / INJURY_RESERVE / SUSPENSION, and respecting games already locked.
- **Writes lineup moves only.** Every write goes through a guard that refuses anything other than a lineup-slot
  move between players already on your roster: no adds, drops, waiver claims, trades, or IR moves.
- Includes a **daily cron script** with locking, logs and a one-line status file, plus an offline **draft-day helper**.

> **Unofficial tool.** This project is not affiliated with, endorsed by, or supported by ESPN or The Walt Disney Company.
> It uses undocumented endpoints that can change or break at any time. You are responsible for complying with ESPN's
> Terms of Use and your league's rules. Use it only for a team you manage, and at your own risk.

## Quick start

Full per-OS instructions (Windows, macOS, Linux), scheduling and troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**.

```bash
git clone https://github.com/blairbbell/fantasy-hockey-companion.git
cd fantasy-hockey-companion
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp config.example.json config.json                     # Windows: Copy-Item config.example.json config.json
cp .env.example .env                                   # then fill in league/team ids and ESPN cookies
python -m tests.test_guard                             # offline self-test
python -m fh_companion.pull_espn && python -m fh_companion.analyze
python -m fh_companion.set_lineups                     # preview moves (no writes)
```

This is a command-line tool: there is no web UI, URL or port. Results are written to `data/`.

## Requirements

- Python 3.9+
- `requests` (`pip install -r requirements.txt`)
- Optional: `flock` and `timeout` (standard on Linux) for `scripts/daily_lineups.sh`; `python -m fh_companion.daily` works on every OS

## Setup

```bash
git clone <this repo> fantasy-hockey-companion && cd fantasy-hockey-companion
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.json config.json      # then edit it
cp .env.example .env                    # optional; env vars override config.json
```

`config.json`, `.env`, cookie files and everything under `data/` are git-ignored.

### Configuration

| Key | Meaning |
| --- | --- |
| `league_id` | Your ESPN `leagueId` (from the league URL) |
| `team_id` | Your team's id in that league (`teamId` in your team page URL) |
| `season` | ESPN `seasonId`, the year the season ends (2026-27 season = `2027`) |
| `season_start` | Date of scoring period 1, used only for date labels |
| `lineup_slots` | Active slot counts by ESPN slot id: `0`=C `1`=LW `2`=RW `4`=D `5`=G `6`=UTIL. Match your league settings. |
| `bench_slots` | Bench size |
| `never_start` | Player full names to always bench (unless on IR) |
| `force_start` | Player full names allowed to start even while ESPN still tags them injured |
| `goalie_scoring` | Your league's goalie points (used to recalculate goalie points in `analyze`) |
| `data_dir` / `cookies_file` | Where pulls/logs and the cookie file live (relative to the repo root) |

Environment overrides: `FH_LEAGUE_ID`, `FH_TEAM_ID`, `FH_SEASON`, `FH_SEASON_START`, `FH_DATA_DIR`,
`FH_CONFIG`, `ESPN_COOKIES_FILE`, `ESPN_S2`, `ESPN_SWID`.

### Authentication

ESPN private leagues need the two cookies from a logged-in browser session, `espn_s2` and `SWID`.

1. Log in at fantasy.espn.com in your browser.
2. Open DevTools → Application/Storage → Cookies → `espn.com`, and copy `espn_s2` and `SWID` (keep the braces on SWID).
3. Either put them in `.env` as `ESPN_S2` / `ESPN_SWID`, or copy `espn_cookies.example.json` to `espn_cookies.json`
   and fill it in (`chmod 600 espn_cookies.json`). `espn_s2_expires` (epoch seconds) is optional and enables an
   expiry warning.

These cookies give full access to your ESPN account. Never commit, paste or share them. They stop working when
you log out or change your password; the tools report "cookies expired" on HTTP 401/403.

## Usage

```bash
python3 -m fh_companion.pull_espn          # read-only pull -> data/pull_latest_raw.json
python3 -m fh_companion.analyze            # -> data/analysis.json, data/roster.csv, data/fa.csv
python3 -m fh_companion.set_lineups        # plan (read-only, prints the moves it would make)
python3 -m fh_companion.set_lineups run    # WRITES lineup changes to ESPN
python3 -m fh_companion.set_lineups verify # re-reads lineups and reports mismatches
python3 -m tests.test_guard                # proves the write guard blocks non-lineup payloads (no network)
```

Daily automation (any OS: `python -m fh_companion.daily [run]`; Linux shell version below):

```bash
scripts/daily_lineups.sh          # dry run (plan), no writes
scripts/daily_lineups.sh run      # live
# cron, 9:00 AM local:
# 0 9 * * * /path/to/fantasy-hockey-companion/scripts/daily_lineups.sh run
```

Logs go to `data/logs/daily_YYYYMMDD.log` (30 days kept). `data/logs/LAST_STATUS` holds a one-line status:
`OK`, `FAIL AUTH`, `FAIL GUARD` or `FAIL`.

Draft day (offline, no login): copy `examples/rankings.example.csv` to `rankings.csv`, fill in your rankings, then
run `python3 -m fh_companion.draft_helper` and use `take <name>`, `undo <name>`, `next [C|LW|RW|D|G]`, `board`, `quit`.

## How the lineup optimizer values players

Each player's value per game blends ESPN's rest-of-season projection and last season's points per game, shrunk
toward the current season's actual points per game as games accumulate. A player only gets value on days their NHL
team plays. Players whose game has already started are left where they are.

## License

MIT, see [LICENSE](LICENSE).
