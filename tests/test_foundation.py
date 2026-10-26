from dataclasses import replace
from datetime import date, datetime, timezone
import importlib
import json
from pathlib import Path
import select
import sqlite3
import stat
import subprocess
import sys

import pytest

from noesis.cli import main
from noesis.config import Config, initialize
from noesis.db import Database, SCHEMA_VERSION, upsert_events, update_event_meta
from noesis.migrations import v001, v002
from noesis.models import Event, Session
from noesis import queries
from noesis.collectors import claude_code
from noesis.collectors.collect import collect
from noesis.collectors.common import read_file
from noesis.runtime import AlreadyRunning, collection_lock, run_logger
from noesis.timeutils import day_range


def event(identity="test", **kw):
    return Event(**(dict(source="codex", source_id=identity, kind="user_msg", ts="2026-10-22T00:00:00Z",
                        content="旧数据仍可检索", session_id="test", meta={"cwd": "/demo"}) | kw))


def synthetic_config(tmp_path):
    config = initialize(tmp_path / "data")
    config.values['sources']['git']=False
    config.values['sources']['browser_history']=False
    for name, key in (("claude_code", "root"), ("codex", "sessions_root")):
        root = tmp_path / name
        root.mkdir()
        config.values[name][key] = str(root)
    config.values["codex"]["history_file"] = str(tmp_path / "history.jsonl")
    return config


def user(index):
    return {"type": "user", "uuid": str(index), "sessionId": "test",
            "timestamp": "2026-10-22T00:00:00Z", "cwd": "/demo",
            "message": {"role": "user", "content": f"消息 {index}"}}


def test_upgrade_m0_preserves_ids_cursors_and_indexes_old_content(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        v001.apply(conn)
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO events(id,source,kind,ts,session_id,content,raw_ref,created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (event().id, "codex", "user_msg", event().ts, "test", event().content, "/demo:1", event().ts))
        conn.execute("INSERT INTO cursors VALUES ('codex','hashed-path','{\"offset\":42}')")
    for _ in range(2):
        with Database(path) as db:
            assert db.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            assert db.connection.execute("SELECT value FROM cursors").fetchone()[0] == '{"offset":42}'
            found = queries.search(db.connection, "可检索")
            assert len(found) == 1 and found[0].event.id == event().id
            assert not db.insert_event(event())
            sessions = queries.get_sessions(db.connection, start=datetime(2026, 10, 22, tzinfo=timezone.utc),
                                            end=datetime(2026, 10, 23, tzinfo=timezone.utc))
            assert len(sessions) == 1 and sessions[0].n_user == 1


def test_failed_migration_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "rollback.sqlite"
    with sqlite3.connect(path) as conn:
        v001.apply(conn)
        conn.execute("PRAGMA user_version=1")
    monkeypatch.setattr(v002, "STATEMENTS", v002.STATEMENTS + ("INVALID SQL",))
    with pytest.raises(sqlite3.Error):
        Database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "source_id" not in [row[1] for row in conn.execute("PRAGMA table_info(events)")]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='sessions'").fetchone() is None


def test_fulltext_insert_update_delete_and_rollback():
    with Database(":memory:") as db:
        assert upsert_events(db.connection, [event(), event()]) == (1, 1)
        db.connection.commit()
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.insert_event(event("rollback", content="回滚文本"))
                raise RuntimeError()
        assert queries.search(db.connection, "回滚文本") == []
        assert queries.search(db.connection, "可检索")
        db.connection.execute("UPDATE events SET content='更新内容' WHERE id=?", (event().id,))
        assert queries.search(db.connection, "可检索") == []
        assert queries.search(db.connection, "更新内容")
        db.delete_events([event().id])
        assert queries.search(db.connection, "更新内容") == []


def test_metadata_patch_keeps_concurrent_fields_and_redacts(tmp_path):
    path = initialize(tmp_path / "data").db_path
    with Database(path) as db:
        db.insert_event(event(meta={"ocr_status": "pending", "note": "", "nested": {"a": 1, "b": 2}}))
    with Database(path) as a, Database(path) as b:
        with a.transaction():
            update_event_meta(a.connection, event().id, {"note": "sk-" + "X" * 24})
        with b.transaction():
            b.update_event_meta(event().id, {"ocr_status": "done", "nested": {"a": None}})
        result = queries.get_session_events(a.connection, "test")[0]
        assert result.meta == {"ocr_status": "done", "note": "[REDACTED:API_KEY]", "nested": {"b": 2}}


def test_sessions_upsert_is_idempotent_and_redacted():
    with Database(":memory:") as db:
        value = Session("codex", "session", event().ts, event().ts, title="sk-" + "X" * 24, n_user=1)
        db.upsert_session(value)
        db.upsert_session(replace(value, n_user=2))
        start, end = day_range(date(2026, 10, 22), "UTC")
        result = queries.get_sessions(db.connection, start=start, end=end)
        assert len(result) == 1 and result[0].n_user == 2
        assert result[0].title == "[REDACTED:API_KEY]"


def test_checkpoint_failure_keeps_first_500_and_resumes(tmp_path, monkeypatch):
    config = synthetic_config(tmp_path)
    path = config.source_path("claude_code", "root") / "session.jsonl"
    path.write_text("".join(json.dumps(user(i)) + "\n" for i in range(1002)))
    original = Database.insert_event
    def fail(self, item):
        original(self, item)
        if item.source_id == "test:500":
            raise RuntimeError("simulated failure after writing record 501")
    monkeypatch.setattr(Database, "insert_event", fail)
    with Database(config.db_path) as db:
        with pytest.raises(RuntimeError):
            read_file(db, path, "claude_code", claude_code.parser(config.values["claude_code"]))
        assert db.get_cursor("claude_code", str(path.resolve()))["line"] == 500
        assert len(queries.get_session_events(db.connection, "test")) == 500
    monkeypatch.setattr(Database, "insert_event", original)
    result = collect(config, "claude_code")["claude_code"]
    assert result["inserted"] == 502
    assert not collect(config, "claude_code")["claude_code"].get("inserted")
    with Database(config.db_path) as db:
        assert db.get_cursor("claude_code", str(path.resolve()))["line"] == 1002
        assert len(queries.get_session_events(db.connection, "test")) == 1002


def test_partial_run_and_source_failure_do_not_stop_other_sources(tmp_path, monkeypatch):
    config = synthetic_config(tmp_path)
    path = config.source_path("claude_code", "root") / "session.jsonl"
    path.write_text("bad json\n" + json.dumps(user(1)) + "\n")
    result = collect(config)
    assert result["claude_code"]["status"] == "partial"
    with Database(config.db_path) as db:
        cc = queries.stats(db.connection).sources[0]
        assert cc.last_run["warnings"] == 1 and cc.last_run["inserted"] == 1
    module = importlib.import_module("noesis.collectors.collect")
    original = module._collect_source
    def fail(ctx, name, *args, **kwargs):
        if name == "claude_code":
            raise RuntimeError("do not persist this secret")
        return original(ctx, name, *args, **kwargs)
    monkeypatch.setattr(module, "_collect_source", fail)
    result = collect(config)
    assert result["claude_code"]["status"] == "failed" and result["codex"]["status"] == "ok"
    with Database(config.db_path) as db:
        row = queries.stats(db.connection).sources[0].last_run
        assert row["error"] == "RuntimeError"
    assert "do not persist this secret" not in next((config.root / "logs").glob("*.log")).read_text()


def test_sqlite_failure_reports_committed_batches(tmp_path, monkeypatch):
    config = synthetic_config(tmp_path)
    path = config.source_path("claude_code", "root") / "session.jsonl"
    path.write_text("".join(json.dumps(user(i)) + "\n" for i in range(502)))
    original = Database.insert_event
    def fail(self, item):
        if item.source_id == "test:500":
            raise sqlite3.OperationalError("simulated failure")
        return original(self, item)
    monkeypatch.setattr(Database, "insert_event", fail)
    report = collect(config, "claude_code")["claude_code"]
    assert report["inserted"] == 500 and report["status"] == "partial"
    with Database(config.db_path) as db:
        assert queries.stats(db.connection).sources[0].last_run["inserted"] == 500


def test_lock_release_and_private_redacted_logs(tmp_path):
    config = synthetic_config(tmp_path)
    with pytest.raises(RuntimeError):
        with collection_lock(config.root):
            with pytest.raises(AlreadyRunning):
                with collection_lock(config.root):
                    pass
            raise RuntimeError()
    with collection_lock(config.root):
        pass
    with run_logger(config) as logger:
        logger.warning("token=secret\nforged log line")
    log = next((config.root / "logs").glob("*.log"))
    assert "secret" not in log.read_text() and len(log.read_text().splitlines()) == 1
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE((config.root / "run/collect.lock").stat().st_mode) == 0o600


def test_two_collect_processes_second_exits_zero(tmp_path):
    config = synthetic_config(tmp_path)
    code = '''
import importlib, sys
from noesis.config import load_config
module = importlib.import_module("noesis.collectors.collect")
def hold(*args, **kwargs):
    print("READY", flush=True)
    sys.stdin.readline()
    from collections import Counter
    return Counter(), []
module._collect_source = hold
module.collect(load_config(sys.argv[1]), "claude_code")
'''
    first = subprocess.Popen([sys.executable, "-c", code, str(config.root)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([first.stdout], [], [], 10)[0]
        assert first.stdout.readline().strip() == "READY"
        second = subprocess.run([sys.executable, "-m", "noesis", "collect", "--data-dir", str(config.root)],
                                capture_output=True, text=True, timeout=10)
        assert second.returncode == 0 and "本次跳过" in second.stdout
        stdout, stderr = first.communicate("continue\n", timeout=10)
        assert first.returncode == 0, stderr
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()
    with Database(config.db_path) as db:
        assert db.connection.execute("SELECT count(*) FROM ingest_runs").fetchone()[0] == 1


def test_search_stats_cli_and_truncation_marker(tmp_path, capsys):
    from noesis.collectors.common import make_event
    config = synthetic_config(tmp_path)
    item = make_event("codex", "one", "assistant", event().ts, "示例内容abcdef", "test", "/demo", Path("/demo"), 1, 4)
    assert item.content == "示例内容…[truncated 6 chars]" and item.meta["truncated"]
    with Database(config.db_path) as db:
        db.insert_event(item)
    assert main(["search", "示例", "--data-dir", str(config.root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["snippet"] == "[示例]内容…[truncated 6 chars]"
    assert main(["stats", "--data-dir", str(config.root)]) == 0
    sources = json.loads(capsys.readouterr().out)["sources"]
    assert next(s for s in sources if s["source"] == "codex")["total"] == 1


def test_successful_unchanged_file_plus_failed_file_is_partial(tmp_path, monkeypatch):
    config = synthetic_config(tmp_path)
    root = config.source_path("claude_code", "root")
    good = root / "good.jsonl"
    good.write_text(json.dumps(user(1)) + "\n")
    collect(config, "claude_code")
    bad = root / "bad.jsonl"
    bad.write_text(json.dumps(user(2)) + "\n")
    original = Path.open
    def denied(path, *args, **kwargs):
        if path == bad:
            raise PermissionError()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    result = collect(config, "claude_code")["claude_code"]
    assert result["status"] == "partial" and result["completed_files"] == 1


def test_doctor_reports_unsupported_sqlite(tmp_path, monkeypatch):
    from noesis.doctor import diagnose
    config = synthetic_config(tmp_path)
    config.values["sources"] = {source: False for source in config.values["sources"]}
    monkeypatch.setattr("noesis.doctor.sqlite3.sqlite_version_info", (3, 33, 0))
    check = next(check for check in diagnose(config) if check.name == "SQLite / FTS5")
    assert check.status == "fail" and "FTS5" in check.fix
