#!/usr/bin/env python3
"""Offline draft-day helper. No ESPN login - you mark picks taken as the draft goes.
Usage:
  python3 -m fh_companion.draft_helper [rankings.csv]          # interactive
  python3 -m fh_companion.draft_helper [rankings.csv] --take "Name"
  python3 -m fh_companion.draft_helper --undo "Name"
  python3 -m fh_companion.draft_helper --next [C|LW|RW|D|G]
  python3 -m fh_companion.draft_helper --board
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .config import CFG, ROOT


def csv_path(rankings: str | None = None) -> Path:
    return Path(rankings) if rankings else ROOT / "rankings.csv"


def taken_path(data_dir: Path | None = None) -> Path:
    return Path(data_dir if data_dir is not None else CFG["data_dir"]) / "taken.txt"


def load_board(path: Path):
    if not path.exists():
        raise SystemExit(
            f"No rankings file at {path}. Copy examples/rankings.example.csv to rankings.csv and fill it in."
        )
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_taken(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def save_taken(path: Path, taken: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(taken)) + ("\n" if taken else ""), encoding="utf-8")


def available(board, taken):
    return [r for r in board if r["player"].strip().lower() not in taken]


def match_player(board, name: str):
    """Return the board's canonical player name for a case-insensitive substring, or None."""
    want = name.lower()
    for r in board:
        if want in r["player"].lower():
            return r["player"]
    return None


def print_next(avail, n=15, pos=None, out=None):
    dest = out or sys.stdout
    shown = 0
    for r in avail:
        positions = r["pos"].upper()
        if pos:
            want = pos.upper()
            if want == "G" and "G" not in positions:
                continue
            if want != "G" and want not in positions:
                continue
        print(f"  {r['rank']:>3}. {r['player']:<28} {r['pos']:<8} {r.get('notes', '')}", file=dest)
        shown += 1
        if shown >= n:
            break
    if shown == 0:
        print("  (none)", file=dest)
    return shown


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Offline draft-day helper (no ESPN login). Interactive unless an action flag is given.",
    )
    ap.add_argument("rankings", nargs="?", help="rankings CSV (default: ./rankings.csv)")
    ap.add_argument("--take", metavar="NAME", help="mark a player taken (substring match) and print the next names")
    ap.add_argument("--undo", metavar="NAME", help="clear a previously taken name (substring match)")
    ap.add_argument("--next", nargs="?", const="", metavar="POS",
                    help="print the next available players, optionally filtered by C, LW, RW, D, or G")
    ap.add_argument("--board", action="store_true", help="same as --next with no position filter")
    ap.add_argument("--count", type=int, default=15, metavar="N", help="how many names to print (default 15)")
    ap.add_argument("--taken-file", help="taken-names file (default: <data_dir>/taken.txt)")
    return ap.parse_args(argv)


def _paths(args):
    board_path = csv_path(args.rankings)
    tpath = Path(args.taken_file) if args.taken_file else taken_path()
    return board_path, tpath


def run_actions(args, board, taken, tpath) -> int:
    """Apply non-interactive flags. Returns the process exit code."""
    if args.take:
        match = match_player(board, args.take)
        if not match:
            print(f"No match for {args.take!r}", file=sys.stderr)
            return 1
        taken.add(match.lower())
        save_taken(tpath, taken)
        print(f"Taken: {match}  ({len(taken)} total)")
        print("Next best available:")
        print_next(available(board, taken), 10)
        return 0
    if args.undo:
        name = args.undo.strip().lower()
        before = len(taken)
        taken = {t for t in taken if name not in t}
        save_taken(tpath, taken)
        print(f"Cleared {before - len(taken)} name(s)")
        return 0
    pos = None
    if args.next is not None:
        pos = args.next.upper() or None
    print("Next best available" + (f" ({pos})" if pos else "") + ":")
    print_next(available(board, taken), args.count, pos)
    return 0


def interactive(board, taken, tpath) -> int:
    print("Fantasy hockey draft helper")
    print("Commands: take <name> | undo <name> | next [C|LW|RW|D|G] | board | quit")
    print(f"Loaded {len(board)} ranked players. Taken so far: {len(taken)}")
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not cmd:
            continue
        low = cmd.lower()
        if low in ("q", "quit", "exit"):
            break
        if low.startswith("take "):
            name = cmd[5:].strip()
            match = match_player(board, name)
            if not match:
                print(f"No match for {name!r}")
                continue
            taken.add(match.lower())
            save_taken(tpath, taken)
            print(f"Taken: {match}  ({len(taken)} total)")
            print("Next best available:")
            print_next(available(board, taken), 10)
            continue
        if low.startswith("undo "):
            name = cmd[5:].strip().lower()
            before = len(taken)
            taken = {t for t in taken if name not in t}
            save_taken(tpath, taken)
            print(f"Cleared {before - len(taken)} name(s)")
            continue
        if low == "board" or low.startswith("next"):
            parts = low.split()
            pos = parts[1].upper() if len(parts) > 1 else None
            print("Next best available" + (f" ({pos})" if pos else "") + ":")
            print_next(available(board, taken), 15, pos)
            continue
        print("Unknown command. Use: take <name> | undo <name> | next [pos] | board | quit")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    board_path, tpath = _paths(args)
    board = load_board(board_path)
    taken = load_taken(tpath)
    if args.take or args.undo or args.next is not None or args.board:
        return run_actions(args, board, taken, tpath)
    return interactive(board, taken, tpath)


if __name__ == "__main__":
    raise SystemExit(main())
