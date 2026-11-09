#!/bin/bash
# daily_lineups.sh - daily lineup reset for your ESPN fantasy hockey team.
# pull -> analyze -> set_lineups run -> set_lineups verify
# LINEUP MOVES ONLY: every ESPN write goes through espn_common.post_tx(), whose guard refuses
# anything other than LINEUP slot moves of current roster players (no FA/waiver/add/drop/IR).
# Usage: scripts/daily_lineups.sh run    (live: writes lineup changes)
#        scripts/daily_lineups.sh        (default: plan = dry run, no writes)
# Example cron (9:00 AM local):  0 9 * * * /path/to/fantasy-hockey-companion/scripts/daily_lineups.sh run
set -u
APP="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"; [ -x "$APP/.venv/bin/python" ] && PY="$APP/.venv/bin/python"
LOGDIR="${FH_LOG_DIR:-${FH_DATA_DIR:-$APP/data}/logs}"
MODE="${1:-plan}"; [ "$MODE" = "run" ] || MODE="plan"
mkdir -p "$LOGDIR"; cd "$APP" || exit 1
LOG="$LOGDIR/daily_$(date +%Y%m%d).log"; STATUS="$LOGDIR/LAST_STATUS"
export PYTHONUNBUFFERED=1
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
status() { echo "$(ts) $*" > "$STATUS"; echo "$(ts) STATUS: $*" >> "$LOG"; }

exec 9>"$LOGDIR/.daily.lock"
if ! flock -n 9; then echo "$(ts) SKIP: previous run still holds lock" >> "$LOG"; exit 0; fi

find "$LOGDIR" -maxdepth 1 -name 'daily_*.log' -mtime +30 -delete 2>/dev/null
echo "===== $(ts) daily_lineups.sh mode=$MODE =====" >> "$LOG"

step() {  # step <label> <cmd...>; output appended to $LOG and kept in $OUT
  local label="$1"; shift
  echo "--- $(ts) $label: $*" >> "$LOG"
  OUT=$(timeout 1800 "$@" 2>&1); local rc=$?
  printf '%s\n' "$OUT" >> "$LOG"
  echo "--- $(ts) $label exit=$rc" >> "$LOG"
  if printf '%s' "$OUT" | grep -qiE 'cookies expired|POST 40[13]'; then
    status "FAIL AUTH ($label): ESPN 401/403 - espn_s2/SWID cookies expired or invalid. Refresh them (README.md). Log: $LOG"; exit 2
  fi
  if printf '%s' "$OUT" | grep -q 'GUARD REFUSED'; then
    status "FAIL GUARD ($label): lineup-only guard refused a non-lineup payload; nothing was sent for it. Log: $LOG"; exit 3
  fi
  if [ $rc -ne 0 ]; then status "FAIL ($label) exit=$rc. Log: $LOG"; exit 1; fi
}
done_counts() { printf '%s\n' "$OUT" | grep '^DONE mode=' | tail -1 | sed 's/^DONE //'; }
check_done() {  # check_done <label>: fail/partial/exception must be 0
  local d; d=$(done_counts)
  [ -n "$d" ] || { status "FAIL ($1): no DONE summary line. Log: $LOG"; exit 1; }
  if printf '%s' "$d" | grep -qE 'fail=[1-9]|partial=[1-9]'; then status "FAIL ($1): $d. Log: $LOG"; exit 1; fi
}

step pull    "$PY" -m fh_companion.pull_espn
PULL=$(printf '%s\n' "$OUT" | grep -m1 '^HTTP' | sed 's/ | league:.*| scoringPeriod/ sp/')
step analyze "$PY" -m fh_companion.analyze
step "set_lineups $MODE" "$PY" -m fh_companion.set_lineups "$MODE"
[ "$MODE" = "run" ] && check_done "set_lineups run"
SET=$(done_counts)
step verify  "$PY" -m fh_companion.set_lineups verify
VER=$(done_counts)
if [ "$MODE" = "run" ]; then check_done verify; fi
INJ=$("$PY" - <<'PY' 2>/dev/null
import csv
from fh_companion.config import CFG
try:
    r=[x for x in csv.DictReader(open(CFG["data_dir"] / "roster.csv")) if (x.get("inj") or "ACTIVE") not in ("ACTIVE","")]
    print(",".join(f"{x.get('name')}={x.get('inj')}" for x in r))
except Exception: print("?")
PY
)
status "OK mode=$MODE | $PULL | set: $SET | verify: $VER | not-active: ${INJ:-none}"
exit 0
