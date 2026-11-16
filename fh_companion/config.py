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
import sys
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
    # Read-only HTML report (python -m fh_companion.report). Empty paths = defaults under data_dir.
    "status_file": "",          # LAST_STATUS written by the daily run (default data_dir/logs/LAST_STATUS)
    "log_dir": "",              # where daily_YYYYMMDD.log files live (default data_dir/logs)
    "analysis_file": "",        # analysis.json from analyze (used only for NHL team abbreviations)
    "report_out": "",           # output page (default data_dir/report/index.html)
    "adds_limit": None,         # adds per matchup week; None = derive from league settings (fallback 4)
    "stale_hours": 26,          # daily status older than this is shown as stale
}

INT_KEYS = {"league_id", "team_id", "season", "bench_slots", "stale_hours"}
STR_KEYS = {
    "season_start", "data_dir", "cookies_file", "status_file",
    "log_dir", "analysis_file", "report_out",
}
LIST_KEYS = {"never_start", "force_start"}
DICT_KEYS = {"lineup_slots", "goalie_scoring"}

ENV_MAP = {
    "FH_LEAGUE_ID": ("league_id", int),
    "FH_TEAM_ID": ("team_id", int),
    "FH_SEASON": ("season", int),
    "FH_SEASON_START": ("season_start", str),
    "FH_DATA_DIR": ("data_dir", str),
    "ESPN_COOKIES_FILE": ("cookies_file", str),
    "FH_STATUS_FILE": ("status_file", str),
    "FH_LOG_DIR": ("log_dir", str),
    "FH_REPORT_OUT": ("report_out", str),
}


class ConfigError(SystemExit):
    """Raised (as SystemExit) when config.json or an env override cannot be used."""


def _load_dotenv(path: Path, environ: dict | None = None) -> None:
    """Minimal .env reader (KEY=VALUE lines); does not override real env vars."""
    env = os.environ if environ is None else environ
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _coerce(key, value, path: str):
    """Return value coerced to the type expected for key, or raise ConfigError."""
    if key in INT_KEYS:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ConfigError(f"{path}: {key} must be an integer, got {type(value).__name__}")
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{path}: {key} must be an integer, got {value!r}") from e
    if key == "adds_limit":
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ConfigError(f"{path}: adds_limit must be an integer or null")
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"{path}: adds_limit must be an integer or null, got {value!r}") from e
    if key in STR_KEYS:
        if not isinstance(value, str):
            raise ConfigError(f"{path}: {key} must be a string")
        return value
    if key in LIST_KEYS:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ConfigError(f"{path}: {key} must be a list of strings")
        return value
    if key in DICT_KEYS:
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: {key} must be an object")
        return value
    return value


def _apply_file(cfg: dict, raw, path: Path) -> None:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    unknown = sorted(set(raw) - set(DEFAULTS))
    if unknown:
        print(f"WARNING: unknown keys in {path} ignored: {unknown}", file=sys.stderr)
    for key, value in raw.items():
        if key not in DEFAULTS:
            continue
        cfg[key] = _coerce(key, value, str(path))


def load(root: Path | None = None, environ: dict | None = None) -> dict:
    """Load config. `root` defaults to the repo root; `environ` defaults to os.environ.

    When `environ` is passed, a .env file next to `root` is applied onto that mapping
    (without overriding keys already present) and FH_* lookups use it instead of os.environ.
    """
    root = ROOT if root is None else Path(root)
    env = os.environ if environ is None else environ
    _load_dotenv(root / ".env", env)
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg_path = Path(env.get("FH_CONFIG", root / "config.json"))
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in {cfg_path}: {e}") from e
        _apply_file(cfg, raw, cfg_path)
    for name, (key, typ) in ENV_MAP.items():
        if env.get(name):
            try:
                cfg[key] = typ(env[name])
            except (TypeError, ValueError) as e:
                raise ConfigError(f"Environment variable {name} must be a {typ.__name__}, got {env[name]!r}") from e
    for key in ("data_dir", "cookies_file"):
        p = Path(cfg[key]).expanduser()
        cfg[key] = p if p.is_absolute() else root / p
    for key, default in (("status_file", "logs/LAST_STATUS"), ("log_dir", "logs"),
                         ("analysis_file", "analysis.json"), ("report_out", "report/index.html")):
        p = Path(cfg.get(key) or default).expanduser()
        cfg[key] = p if p.is_absolute() else (cfg["data_dir"] / p if not cfg.get(key) else root / p)
    try:
        cfg["lineup_slots"] = {int(k): int(v) for k, v in cfg["lineup_slots"].items()}
    except (TypeError, ValueError) as e:
        raise ConfigError(f"lineup_slots must map slot ids to integer counts: {e}") from e
    return cfg


def require_ids(cfg: dict) -> None:
    if not cfg["league_id"] or not cfg["team_id"]:
        raise SystemExit("Set league_id and team_id in config.json (or FH_LEAGUE_ID / FH_TEAM_ID). See README.md.")


CFG = load()
