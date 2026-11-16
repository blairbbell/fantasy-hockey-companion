"""Package entry tests: python -m fh_companion --help / --version / unknown command.
Run: python3 -m tests.test_main   (or pytest). No network, no cookies."""
from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from fh_companion import __version__
from fh_companion.cli import COMMANDS, main as cli_main


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


def test_help_lists_every_command():
    for argv in ([], ["--help"], ["-h"], ["help"]):
        code, out, err = _run(argv)
        assert code == 0 and err == ""
        assert "Usage:" in out
        for name in COMMANDS:
            assert name in out


def test_version():
    for argv in (["--version"], ["-V"], ["version"]):
        code, out, err = _run(argv)
        assert code == 0 and err == ""
        assert __version__ in out
        assert "fantasy-hockey-companion" in out


def test_unknown_command():
    code, out, err = _run(["not-a-command"])
    assert code == 2
    assert "Unknown command" in err
    assert "not-a-command" in err


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
    print("MAIN TESTS:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
    return fails == 0


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
