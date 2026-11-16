"""Package entry: python -m fh_companion <command> [args...]

Lists built-in commands, prints --version, and dispatches to the matching module.
Existing invocations such as `python -m fh_companion.set_lineups` are unchanged.
"""
from __future__ import annotations

import runpy
import sys

from . import __version__

COMMANDS = {
    "pull_espn": "Read-only pull of league, roster, free agents and the NHL schedule",
    "analyze": "Score roster and free agents; write analysis.json, roster.csv, fa.csv",
    "set_lineups": "Plan or apply rest-of-season lineup moves (lineup slots only)",
    "daily": "Cross-platform daily runner: pull -> analyze -> set_lineups -> verify",
    "report": "Write the read-only HTML status report",
    "draft_helper": "Offline draft-day board (no ESPN login)",
}

USAGE = """Usage: python -m fh_companion [--version] [--help] <command> [args...]

Commands:
{cmds}

Each command is the same as `python -m fh_companion.<command> [args...]`.
For command-specific help, run: python -m fh_companion <command> --help
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        cmds = "\n".join(f"  {name:<16} {desc}" for name, desc in COMMANDS.items())
        print(USAGE.format(cmds=cmds).rstrip())
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(f"fantasy-hockey-companion {__version__}")
        return 0
    cmd = argv[0]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd!r}. Try python -m fh_companion --help", file=sys.stderr)
        return 2
    sys.argv = [f"fh_companion.{cmd}", *argv[1:]]
    runpy.run_module(f"fh_companion.{cmd}", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
