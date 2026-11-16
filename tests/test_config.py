"""Config loader tests: defaults, files, env, .env, validation. No network, no cookies.
Run: python3 -m tests.test_config   (or pytest)."""
from __future__ import annotations

import json
from pathlib import Path

from fh_companion import config as C


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_files():
    cfg = C.load(root=Path("/tmp/fh-config-empty-nonexistent"), environ={})
    assert cfg["league_id"] == 0 and cfg["team_id"] == 0
    assert cfg["season"] == 2027
    assert cfg["lineup_slots"][0] == 2 and cfg["lineup_slots"][5] == 2
    assert cfg["adds_limit"] is None
    assert cfg["data_dir"].name == "data"
    assert cfg["cookies_file"].name == "espn_cookies.json"


def test_file_overrides_defaults(tmp_path: Path | None = None):
    from tempfile import TemporaryDirectory
    ctx = TemporaryDirectory() if tmp_path is None else None
    root = Path(tmp_path or ctx.name)
    try:
        _write(root / "config.json", json.dumps({
            "league_id": 99, "team_id": 3, "season": 2028,
            "data_dir": "custom-data", "bench_slots": 7, "adds_limit": 5,
        }))
        cfg = C.load(root=root, environ={})
        assert cfg["league_id"] == 99 and cfg["team_id"] == 3 and cfg["season"] == 2028
        assert cfg["bench_slots"] == 7 and cfg["adds_limit"] == 5
        assert cfg["data_dir"] == root / "custom-data"
        assert cfg["status_file"] == root / "custom-data" / "logs" / "LAST_STATUS"
    finally:
        if ctx:
            ctx.cleanup()


def test_env_overrides_file():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root = Path(t)
        _write(root / "config.json", json.dumps({"league_id": 11, "team_id": 2, "season": 2027}))
        env = {"FH_LEAGUE_ID": "42", "FH_TEAM_ID": "8", "FH_SEASON": "2029"}
        cfg = C.load(root=root, environ=env)
        assert cfg["league_id"] == 42 and cfg["team_id"] == 8 and cfg["season"] == 2029


def test_dotenv_does_not_override_real_env():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root = Path(t)
        _write(root / ".env", "FH_LEAGUE_ID=7\nFH_TEAM_ID=4\n")
        env = {"FH_TEAM_ID": "9"}
        cfg = C.load(root=root, environ=env)
        assert cfg["league_id"] == 7  # from .env
        assert cfg["team_id"] == 9    # already in environ wins
        assert env["FH_LEAGUE_ID"] == "7" and env["FH_TEAM_ID"] == "9"


def test_fh_config_path():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root = Path(t)
        other = _write(root / "other.json", json.dumps({"league_id": 15, "team_id": 1}))
        cfg = C.load(root=root, environ={"FH_CONFIG": str(other)})
        assert cfg["league_id"] == 15 and cfg["team_id"] == 1


def test_invalid_json():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root = Path(t)
        _write(root / "config.json", "{not json")
        try:
            C.load(root=root, environ={})
        except C.ConfigError as e:
            assert "Invalid JSON" in str(e)
        else:
            raise AssertionError("expected ConfigError")


def test_bad_type_and_unknown_key_warning():
    from tempfile import TemporaryDirectory
    import io
    from contextlib import redirect_stderr
    with TemporaryDirectory() as t:
        root = Path(t)
        _write(root / "config.json", json.dumps({"league_id": "nope"}))
        try:
            C.load(root=root, environ={})
        except C.ConfigError as e:
            assert "league_id" in str(e)
        else:
            raise AssertionError("expected ConfigError")
        _write(root / "config.json", json.dumps({"league_id": 1, "team_id": 1, "not_a_real_key": 1}))
        err = io.StringIO()
        with redirect_stderr(err):
            cfg = C.load(root=root, environ={})
        assert "not_a_real_key" in err.getvalue()
        assert "not_a_real_key" not in cfg
        assert cfg["league_id"] == 1


def test_bad_env_type():
    try:
        C.load(root=Path("/tmp/fh-config-empty-nonexistent"), environ={"FH_LEAGUE_ID": "abc"})
    except C.ConfigError as e:
        assert "FH_LEAGUE_ID" in str(e)
    else:
        raise AssertionError("expected ConfigError")


def test_require_ids():
    cfg = {"league_id": 0, "team_id": 1}
    try:
        C.require_ids(cfg)
    except SystemExit as e:
        assert "league_id" in str(e)
    else:
        raise AssertionError("expected SystemExit")
    C.require_ids({"league_id": 5, "team_id": 1})  # does not raise


def test_absolute_paths_kept():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root = Path(t)
        abs_data = Path(t) / "absdata"
        _write(root / "config.json", json.dumps({
            "data_dir": str(abs_data),
            "cookies_file": "/tmp/fh-cookies-example.json",
            "report_out": "/tmp/fh-report-example.html",
        }))
        cfg = C.load(root=root, environ={})
        assert cfg["data_dir"] == abs_data
        assert cfg["cookies_file"] == Path("/tmp/fh-cookies-example.json")
        assert cfg["report_out"] == Path("/tmp/fh-report-example.html")
        assert cfg["status_file"] == abs_data / "logs" / "LAST_STATUS"


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
    print("CONFIG TESTS:", "ALL PASS" if fails == 0 else f"{fails} FAILED")
    return fails == 0


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
