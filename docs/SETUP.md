# Setup guide (Windows, macOS, Linux)

Fantasy Hockey Companion is a set of **command-line tools**. It has **no web UI, opens no network port, and runs
no local server**. It only makes outbound HTTPS requests to ESPN's fantasy API. The two parts are:

- **Companion (read-only):** `pull_espn` + `analyze` - fetches your league and writes reports to `data/`.
- **Manager (lineups):** `set_lineups` (plan / run / verify) and the daily runner `daily`, which apply
  lineup-only moves through a safety guard. `draft_helper` is an offline draft-day board.

All commands below are run from the repository root folder.

---

## 1. Prerequisites

You need **Python 3.9 or newer** and **Git**. Node.js is not needed.

### Windows 10/11

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
```

Or download Python from https://www.python.org/downloads/windows/ (tick **"Add python.exe to PATH"**) and Git
from https://git-scm.com/download/win. Close and reopen PowerShell, then check:

```powershell
py --version      # or: python --version
git --version
```

### macOS

Install Homebrew from https://brew.sh, then:

```bash
brew install python git
python3 --version
```

(Python is also available from https://www.python.org/downloads/macos/.)

### Linux

Debian / Ubuntu / Raspberry Pi OS:

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
```

Fedora / RHEL:

```bash
sudo dnf install -y python3 python3-pip git
```

Check with `python3 --version`.

---

## 2. Get the code

```bash
git clone https://github.com/blairbbell/fantasy-hockey-companion.git
cd fantasy-hockey-companion
```

## 3. Create a virtual environment and install dependencies

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Windows (Command Prompt): `.venv\Scripts\activate.bat`

After activation, use `python` (Windows) or `python3`/`python` (Linux/macOS) for the commands below.

## 4. Configure

Copy the examples:

| | Linux / macOS | Windows (PowerShell) |
| --- | --- | --- |
| League config | `cp config.example.json config.json` | `Copy-Item config.example.json config.json` |
| Environment (optional) | `cp .env.example .env` | `Copy-Item .env.example .env` |
| Cookie file (option B) | `cp espn_cookies.example.json espn_cookies.json` | `Copy-Item espn_cookies.example.json espn_cookies.json` |

`config.json`, `.env`, `espn_cookies.json` and `data/` are in `.gitignore`. Never commit them.

**Values you must fill in yourself:**

| Value | Where to find it | Put it in |
| --- | --- | --- |
| `league_id` | Your ESPN league URL: `...?leagueId=123456` | `config.json` or `FH_LEAGUE_ID` in `.env` |
| `team_id` | Your team page URL: `...&teamId=1` | `config.json` or `FH_TEAM_ID` |
| `season` | Year the season ends (2026-27 = `2027`) | `config.json` or `FH_SEASON` |
| `lineup_slots`, `bench_slots` | League → Settings → Roster | `config.json` |
| `goalie_scoring` | League → Settings → Scoring | `config.json` |
| `espn_s2`, `SWID` cookies | See below | `.env` (`ESPN_S2`, `ESPN_SWID`) **or** `espn_cookies.json` |

Optional: `never_start` / `force_start` (lists of player full names), `season_start`, `data_dir`.

**Getting the ESPN cookies:** log in at https://fantasy.espn.com in a desktop browser, open DevTools
(F12 / Cmd+Opt+I) → **Application** (Chrome/Edge) or **Storage** (Firefox) → **Cookies** → `https://www.espn.com`,
and copy the values of `espn_s2` and `SWID` (keep SWID's curly braces). These cookies are as powerful as your
password: keep them only in `.env` or `espn_cookies.json`, and on Linux/macOS run `chmod 600 .env espn_cookies.json`.

## 5. Run

| Task | Command |
| --- | --- |
| Test the write guard (no network, no cookies) | `python -m tests.test_guard` |
| Pull league data (read-only) | `python -m fh_companion.pull_espn` |
| Analyze roster and free agents | `python -m fh_companion.analyze` |
| Preview lineup moves (no writes) | `python -m fh_companion.set_lineups` |
| Apply lineup moves on ESPN | `python -m fh_companion.set_lineups run` |
| Check lineups after a run | `python -m fh_companion.set_lineups verify` |
| Whole daily pipeline, dry run | `python -m fh_companion.daily` |
| Whole daily pipeline, live | `python -m fh_companion.daily run` |
| Draft-day board (offline) | `python -m fh_companion.draft_helper rankings.csv` |
| Read-only HTML report page | `python -m fh_companion.report` |
| Test the report (fake data, no network) | `python -m tests.test_report` |

Output goes to `data/`: `analysis.json`, `roster.csv`, `fa.csv`, `lineup_*_report.json`, `set_lineups.log`,
and `data/logs/daily_YYYYMMDD.log` + `data/logs/LAST_STATUS` for the daily runner.

There is **no URL or port** to open; results are files and terminal output. Open the CSVs in any spreadsheet app,
and open `data/report/index.html` (from `fh_companion.report`) in any browser.

## 6. Schedule it daily (optional)

**Linux / macOS (cron):** `crontab -e`, then add (9:00 AM local):

```
0 9 * * * cd /path/to/fantasy-hockey-companion && .venv/bin/python -m fh_companion.daily run
```

On Linux you can also use `scripts/daily_lineups.sh run` (needs `flock`, which macOS does not ship).

**macOS (launchd)** works too, but cron is simplest. If cron cannot read the folder, give `cron` Full Disk Access
in System Settings → Privacy & Security, or keep the project outside Documents/Desktop.

**Windows (Task Scheduler):**

```powershell
$dir = "C:\path\to\fantasy-hockey-companion"
$action = New-ScheduledTaskAction -Execute "$dir\.venv\Scripts\python.exe" -Argument "-m fh_companion.daily run" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 9am
Register-ScheduledTask -TaskName "FantasyHockeyLineups" -Action $action -Trigger $trigger
```

Start with the dry-run (`daily` without `run`) for a few days and read the log before going live.

---

## Troubleshooting

**PowerShell: "running scripts is disabled on this system" when activating the venv**
Allow local scripts for your user only, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Or skip activation and call the venv Python directly: `.\.venv\Scripts\python.exe -m fh_companion.pull_espn`.

**`python` opens the Microsoft Store or is not found (Windows)**
Use `py` instead, or turn off the `python.exe` alias in Settings → Apps → Advanced app settings → App execution aliases.

**`error: externally-managed-environment` (Linux/macOS pip)**
You are installing outside a venv. Create and activate `.venv` (step 3) first.

**`No module named venv` / `ensurepip is not available` (Debian/Ubuntu)**
`sudo apt install python3-venv`.

**`No module named fh_companion`**
Run commands from the repository root (the folder containing `fh_companion/`), and use `python -m ...`, not
`python fh_companion/xyz.py`.

**"Set league_id and team_id in config.json"**
You have not created `config.json` or left the ids at 0. See step 4.

**"No ESPN cookies" / "cookies expired or invalid" / HTTP 401 or 403**
Re-copy `espn_s2` and `SWID` from a logged-in browser. They stop working if you log out of ESPN or change your
password. Make sure SWID still has its `{...}` braces.

**Firewall prompts**
The tools only make outbound HTTPS requests and do not listen on any port, so you should not see an
"allow incoming connections" prompt. If a corporate firewall or proxy blocks `lm-api-reads.fantasy.espn.com` /
`lm-api-writes.fantasy.espn.com`, set `HTTPS_PROXY` or run from another network.

**Port already in use**
Not applicable: nothing listens on a port. If you see this, it comes from a different program.

**`GUARD REFUSED` in the log**
The safety guard blocked a non-lineup write; nothing was sent. This is expected protection, not an ESPN error.

**Daily log shows `SKIP: previous run still holds lock` (shell script)**
A previous run is still going or crashed; delete `data/logs/.daily.lock` if no run is active.

**Times or "game locked" look wrong**
The tools use your computer's local time zone. Check the system clock and time zone.
