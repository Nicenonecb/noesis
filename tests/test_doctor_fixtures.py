from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from noesis.cli import main
from noesis.config import initialize
from noesis.doctor import Check, diagnose, inspect_history

FIXTURES = Path(__file__).parent / "fixtures"


def test_history_copy_includes_live_wal_and_leaves_source_unchanged(tmp_path):
    path = tmp_path / "History"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.executescript((FIXTURES / "chrome.sql").read_text())
        db.commit()
        wal = Path(str(path) + "-wal")
        assert wal.exists() and wal.stat().st_size > 0
        before = (path.read_bytes(), wal.read_bytes())
        inspect_history(path, ("urls", "visits"))
        assert (path.read_bytes(), wal.read_bytes()) == before
        assert db.execute("SELECT count(*) FROM visits").fetchone()[0] == 4
    finally:
        db.close()


def test_missing_or_invalid_history_does_not_create_source(tmp_path):
    missing = tmp_path / "History"
    with pytest.raises(FileNotFoundError):
        inspect_history(missing, ("urls", "visits"))
    assert not missing.exists()
    missing.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        inspect_history(missing, ("urls", "visits"))


def test_synthetic_browser_epochs(tmp_path):
    expected = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)
    for name, table, epoch, units in [
        ("chrome.sql", "visits", 1601, "microseconds"),
        ("arc_unverified.sql", "visits", 1601, "microseconds"),
        ("safari_unverified.sql", "history_visits", 2001, "seconds"),
    ]:
        with sqlite3.connect(tmp_path / name) as db:
            db.executescript((FIXTURES / name).read_text())
            value = db.execute(f"SELECT visit_time FROM {table} LIMIT 1").fetchone()[0]
            assert datetime(epoch, 1, 1, tzinfo=timezone.utc) + timedelta(**{units: value}) == expected


def test_jsonl_fixtures_are_parseable_except_deliberate_bad_tail():
    for path in FIXTURES.glob("*.jsonl"):
        if path.name == "malformed_tail.jsonl":
            assert not path.read_bytes().endswith(b"\n")
            continue
        assert all(isinstance(json.loads(line), dict) for line in path.read_text().splitlines())


def test_doctor_exit_codes_and_secret_safe_output(tmp_path, monkeypatch, capsys):
    root = initialize(tmp_path / "data").root
    monkeypatch.setattr("noesis.cli.diagnose", lambda config: [Check("Safari", "fail", "PermissionError"), Check("test", "manual", "token=fake")])
    assert main(["doctor", "--data-dir", str(root)]) == 0
    assert main(["doctor", "--data-dir", str(root), "--strict"]) == 1
    output = capsys.readouterr().out
    assert "token=fake" not in output
    assert "[REDACTED:" in output
    assert "❌" in output and "⚠️" in output


def test_diagnose_sources_and_denied_safari_with_synthetic_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    paths = {
        ".claude/projects/synthetic/session.jsonl": "claude_code.jsonl",
        ".codex/sessions/2026/10/22/rollout-synthetic.jsonl": "codex_current.jsonl",
        ".codex/history.jsonl": "codex_history.jsonl",
    }
    for target, fixture in paths.items():
        path = home / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((FIXTURES / fixture).read_bytes())
    chrome = home / "Library/Application Support/Google/Chrome/Default/History"
    chrome.parent.mkdir(parents=True)
    with sqlite3.connect(chrome) as db:
        db.executescript((FIXTURES / "chrome.sql").read_text())
    safari = home / "Library/Safari/History.db"
    safari.parent.mkdir(parents=True)
    safari.write_bytes(b"synthetic permission test")
    original = inspect_history

    def inspect(path, tables):
        if path == safari:
            raise PermissionError("synthetic denial")
        original(path, tables)

    monkeypatch.setattr("noesis.doctor.inspect_history", inspect)
    monkeypatch.setattr("noesis.doctor._installed", lambda bundle: bundle in {"Google Chrome.app", "Safari.app"})
    monkeypatch.setattr("noesis.doctor.shutil.which", lambda name: None)
    checks = diagnose(initialize(home / "data"))
    by_name = {check.name: check for check in checks}
    assert by_name["Claude Code"].status == "ok"
    assert by_name["Codex sessions"].status == "ok"
    assert by_name["Codex history"].status == "ok"
    assert by_name["chrome/Default"].status == "ok"
    assert by_name["arc"].status == "skip"
    assert by_name["safari"].status == "fail"
    assert "完全磁盘访问权限" in by_name["safari"].fix
    assert by_name["辅助功能（M4）"].status == "manual"


def test_disabled_sources_are_not_probed(tmp_path, monkeypatch):
    config = initialize(tmp_path / "data")
    config.values["sources"] = {name: False for name in config.values["sources"]}

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled sources must not be probed")

    monkeypatch.setattr("noesis.doctor._source_check", forbidden)
    monkeypatch.setattr("noesis.doctor.inspect_history", forbidden)
    monkeypatch.setattr("noesis.doctor.subprocess.run", forbidden)
    checks = diagnose(config)
    assert not any(check.status == "fail" for check in checks)
