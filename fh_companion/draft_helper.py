#!/usr/bin/env python3
"""Offline draft-day helper. No ESPN login - you mark picks taken as the draft goes.
Usage: python3 -m fh_companion.draft_helper [rankings.csv]"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from .config import CFG
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "rankings.csv"
TAKEN_PATH = CFG["data_dir"] / "taken.txt"

def load_board():
    with CSV_PATH.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))

def load_taken():
    if not TAKEN_PATH.exists():
        return set()
    return {line.strip().lower() for line in TAKEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}

def save_taken(taken):
    TAKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAKEN_PATH.write_text("\n".join(sorted(taken)) + ("\n" if taken else ""), encoding="utf-8")

def available(board, taken):
    return [r for r in board if r["player"].strip().lower() not in taken]

def print_next(avail, n=15, pos=None):
    shown = 0
    for r in avail:
        positions = r["pos"].upper()
        if pos:
            want = pos.upper()
            if want == "G" and "G" not in positions:
                continue
            if want != "G" and want not in positions:
                continue
        print(f"  {r['rank']:>3}. {r['player']:<28} {r['pos']:<8} {r.get('notes','')}")
        shown += 1
        if shown >= n:
            break
    if shown == 0:
        print("  (none)")

def main():
    board = load_board()
    taken = load_taken()
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
            match = None
            for r in board:
                if name.lower() in r["player"].lower():
                    match = r["player"]
                    break
            if not match:
                print(f"No match for {name!r}")
                continue
            taken.add(match.lower())
            save_taken(taken)
            print(f"Taken: {match}  ({len(taken)} total)")
            print("Next best available:")
            print_next(available(board, taken), 10)
            continue
        if low.startswith("undo "):
            name = cmd[5:].strip().lower()
            before = len(taken)
            taken = {t for t in taken if name not in t}
            save_taken(taken)
            print(f"Cleared {before - len(taken)} name(s)")
            continue
        if low == "board" or low.startswith("next"):
            parts = low.split()
            pos = parts[1].upper() if len(parts) > 1 else None
            print("Next best available" + (f" ({pos})" if pos else "") + ":")
            print_next(available(board, taken), 15, pos)
            continue
        print("Unknown command. Use: take <name> | undo <name> | next [pos] | board | quit")

if __name__ == "__main__":
    main()
