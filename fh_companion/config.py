"""Configuration loading.

Settings come from (later wins):
  1. built-in defaults below
  2. a JSON config file (FH_CONFIG, default ./config.json)
  3. environment variables (FH_LEAGUE_ID, FH_TEAM_ID, FH_SEASON, ...)

Nothing personal is hard-coded here. Copy config.example.json -> config.json and .env.example -> .env.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "league_id": 0,             # ESPN leagueId (from your league URL)
    "team_id": 0,               # your teamId inside the league
    "season": 2027,             # ESPN seasonId (the year the season ends)
    "season_start": "2026-09-29",  # calendar date of scoring period 1 (used only for labels)
    "data_dir": "data",         # pulls, reports and logs go here (git-ignored)
    "cookies_file": "espn_cookies.json",  # git-ignored; see README
    # Active lineup slot counts by ESPN slot id: 0=C 1=LW 2=RW 4=D 5=G 6=UTIL
    "lineup_slots": {"0": 2, "1": 2, "2": 2, "4": 4, "5": 2, "6": 1},
    "bench_slots": 6,
    "never_start": [],          # player full names to always bench (unless on IR)
    "force_start": [],          # player full names to start even if ESPN tags them injured
    # League scoring used for the goalie points recalculation in analyze.py
    "goalie_scoring": {"W": 4, "GA": -1, "SV": 0.2, "SO": 1, "OTL": 1},
}

ENV_MAP = {
    "FH_LEAGUE_ID": ("league_id", int),
    "FH_TEAM_ID": ("team_id", int),
    "FH_SEASON": ("season", int),
    "FH_SEASON_START": ("season_start", str),
    "FH_DATA_DIR": ("data_dir", str),
    "ESPN_COOKIES_FILE": ("cookies_file", str),
}


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); does not override real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load() -> dict:
    _load_dotenv(ROOT / ".env")
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg_path = Path(os.environ.get("FH_CONFIG", ROOT / "config.json"))
    if cfg_path.exists():
        cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
    for env, (key, typ) in ENV_MAP.items():
        if os.environ.get(env):
            cfg[key] = typ(os.environ[env])
    for key in ("data_dir", "cookies_file"):
        p = Path(cfg[key]).expanduser()
        cfg[key] = p if p.is_absolute() else ROOT / p
    cfg["lineup_slots"] = {int(k): int(v) for k, v in cfg["lineup_slots"].items()}
    return cfg


def require_ids(cfg: dict) -> None:
    if not cfg["league_id"] or not cfg["team_id"]:
        raise SystemExit("Set league_id and team_id in config.json (or FH_LEAGUE_ID / FH_TEAM_ID). See README.md.")


CFG = load()
