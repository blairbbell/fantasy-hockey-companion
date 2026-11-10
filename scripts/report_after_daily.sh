#!/bin/bash
# report_after_daily.sh - regenerate the read-only HTML report after the daily lineup run.
# Runs separately from daily_lineups.sh: waits (default up to 40 min) for today's LAST_STATUS, then renders
# data/report/index.html (or config report_out). Low priority (nice/ionice), single instance (flock), hard timeout.
# fh_companion.report only issues GET requests to ESPN's read API; it never writes to your team.
# Usage: scripts/report_after_daily.sh [wait-minutes]
# Example cron (20 min after a 9:00 daily run):  20 9 * * * /path/to/fantasy-hockey-companion/scripts/report_after_daily.sh
set -u
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE"; [ -d "$APP/fh_companion" ] || APP="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"; [ -x "$APP/.venv/bin/python" ] && PY="$APP/.venv/bin/python"
cd "$APP" || exit 1
LOG="${FH_REPORT_LOG:-$APP/data/report.log}"; mkdir -p "$(dirname "$LOG")"
exec 8>"$(dirname "$LOG")/.report.lock"
flock -n 8 || { echo "$(date '+%F %T %Z') SKIP: report already running" >> "$LOG"; exit 0; }
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 200000 ]; then tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
NICE=(nice -n 19); command -v ionice >/dev/null && NICE+=(ionice -c3)
{
  echo "===== $(date '+%F %T %Z') report_after_daily.sh"
  timeout 3000 "${NICE[@]}" "$PY" -m fh_companion.report --wait-for-today "${1:-40}"
  echo "exit=$?"
} >> "$LOG" 2>&1
