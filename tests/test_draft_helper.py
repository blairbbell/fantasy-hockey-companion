"""Draft helper tests: fake rankings only, no network, no cookies.
Run: python3 -m tests.test_draft_helper   (or pytest)."""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from fh_companion import draft_helper as DH

BOARD = """rank,player,pos,notes
1,Example Player One,C,ace
2,Example Player Two,LW/RW,
3,Example Player Three,D,
4,Example Goalie,G,
"""


def _setup(tmp: Path):
    csv_path = tmp / "rankings.csv"
    csv_path.write_text(BOARD, encoding="utf-8")
    taken = tmp / "taken.txt"
    return csv_path, taken


def _run(tmp: Path, *flags, rankings=True):
    csv_path, taken = _setup(tmp)
    argv = [str(csv_path)] if rankings else []
    argv += list(flags) + ["--taken-file", str(taken)]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = DH.main(argv)
    return code, out.getvalue(), err.getvalue(), taken, csv_path


def test_board_and_next_filter():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        tmp = Path(t)
        code, out, err, _, _ = _run(tmp, "--board")
        assert code == 0 and err == ""
        assert "Example Player One" in out and "Example Goalie" in out
        code, out, err, _, _ = _run(tmp, "--next", "G")
        assert code == 0 and "Example Goalie" in out
        assert "Example Player One" not in out
        code, out, err, _, _ = _run(tmp, "--next", "LW")
        assert "Example Player Two" in out
        assert "Example Player One" not in out and "Example Goalie" not in out


def test_take_then_undo_same_file():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        tmp = Path(t)
        csv_path, taken = _setup(tmp)
        def go(*flags):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = DH.main([str(csv_path), "--taken-file", str(taken), *flags])
            return code, out.getvalue(), err.getvalue()
        code, out, err = go("--take", "Goalie")
        assert code == 0 and "Taken: Example Goalie" in out
        assert DH.load_taken(taken) == {"example goalie"}
        code, out, err = go("--board")
        assert "Example Goalie" not in out and "Example Player One" in out
        code, out, err = go("--undo", "goalie")
        assert code == 0 and "Cleared 1 name(s)" in out
        assert DH.load_taken(taken) == set()


def test_take_unknown_is_error():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        code, out, err, _, _ = _run(Path(t), "--take", "Nobody Here")
        assert code == 1
        assert "No match" in err


def test_missing_rankings():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        missing = Path(t) / "nope.csv"
        taken = Path(t) / "taken.txt"
        try:
            DH.main([str(missing), "--board", "--taken-file", str(taken)])
        except SystemExit as e:
            assert "No rankings file" in str(e)
        else:
            raise AssertionError("expected SystemExit")


def test_helpers_available_and_match():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        csv_path, _ = _setup(Path(t))
        board = DH.load_board(csv_path)
        assert DH.match_player(board, "player one") == "Example Player One"
        assert DH.match_player(board, "zzz") is None
        avail = DH.available(board, {"example player one"})
        assert [r["player"] for r in avail] == [
            "Example Player Two", "Example Player Three", "Example Goalie",
        ]


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print("DRAFT HELPER TESTS:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
    return fails == 0


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
