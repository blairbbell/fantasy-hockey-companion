"""Cross-platform daily runner (Windows/macOS/Linux): pull -> analyze -> set_lineups <mode> -> verify.
Equivalent to scripts/daily_lineups.sh, for use with Task Scheduler, launchd or cron.
Usage: python -m fh_companion.daily [plan|run]     (default: plan = no writes)
Writes data/logs/daily_YYYYMMDD.log and a one-line data/logs/LAST_STATUS. Exit 0 OK, 1 FAIL, 2 AUTH, 3 GUARD."""
import re
import subprocess
import sys
import time
from datetime import datetime

from .config import CFG, ROOT

LOGDIR = CFG["data_dir"] / "logs"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] == "run" else "plan"
    LOGDIR.mkdir(parents=True, exist_ok=True)
    for old in LOGDIR.glob("daily_*.log"):
        if time.time() - old.stat().st_mtime > 30 * 86400:
            old.unlink()
    log = LOGDIR / f"daily_{datetime.now():%Y%m%d}.log"
    status_file = LOGDIR / "LAST_STATUS"
    ts = lambda: datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def write(msg):
        with log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def status(msg, code):
        status_file.write_text(f"{ts()} {msg}\n", encoding="utf-8")
        write(f"{ts()} STATUS: {msg}")
        print(msg)
        sys.exit(code)

    def step(label, *args):
        write(f"--- {ts()} {label}: {' '.join(args)}")
        try:
            p = subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True, timeout=1800)
            out, rc = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            out, rc = "timeout", 124
        write(out.rstrip())
        write(f"--- {ts()} {label} exit={rc}")
        if re.search(r"cookies expired|POST 40[13]", out, re.I):
            status(f"FAIL AUTH ({label}): ESPN 401/403 - espn_s2/SWID cookies expired or invalid (see README). Log: {log}", 2)
        if "GUARD REFUSED" in out:
            status(f"FAIL GUARD ({label}): lineup-only guard refused a payload; nothing was sent for it. Log: {log}", 3)
        if rc != 0:
            status(f"FAIL ({label}) exit={rc}. Log: {log}", 1)
        return out

    def done(out, label, strict):
        m = [l[5:] for l in out.splitlines() if l.startswith("DONE mode=")]
        if strict and (not m or re.search(r"fail=[1-9]|partial=[1-9]", m[-1])):
            status(f"FAIL ({label}): {m[-1] if m else 'no DONE summary line'}. Log: {log}", 1)
        return m[-1] if m else ""

    write(f"===== {ts()} fh_companion.daily mode={mode} =====")
    pull = next((l for l in step("pull", "fh_companion.pull_espn").splitlines() if l.startswith("HTTP")), "")
    step("analyze", "fh_companion.analyze")
    s = done(step(f"set_lineups {mode}", "fh_companion.set_lineups", mode), "set_lineups", mode == "run")
    v = done(step("verify", "fh_companion.set_lineups", "verify"), "verify", mode == "run")
    status(f"OK mode={mode} | {pull} | set: {s} | verify: {v}", 0)


if __name__ == "__main__":
    main()
