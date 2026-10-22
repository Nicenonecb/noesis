from datetime import datetime, timezone
import hashlib
import json
import sqlite3

import pytest

from aibrain.config import initialize
from aibrain.db import Database
from aibrain.models import Event, utc_timestamp


def event(**kwargs):
    return Event(**({"source": "codex", "source_id": "synthetic-id", "kind": "user_msg", "ts": "2026-10-22T09:00:00+08:00"} | kwargs))


def test_schema_idempotence_and_atomic_cursor(tmp_path):
    config = initialize(tmp_path / "data")
    item = event(content="合成消息")
    with Database(config.db_path) as db:
        assert db.insert_event(item)
        assert not db.insert_event(item)
        db.set_cursor("codex", "synthetic-file", {"offset": 42, "line": 2})
        assert db.get_cursor("codex", "missing") is None
    initialize(config.root)
    with Database(config.db_path) as db:
        assert db.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
        assert db.get_cursor("codex", "synthetic-file") == {"offset": 42, "line": 2}
        row = db.connection.execute("SELECT * FROM events").fetchone()
        assert row["id"] == hashlib.sha1(b"codex|synthetic-id").hexdigest()
        assert row["ts"] == "2026-10-22T01:00:00.000000Z"
        assert row["created_at"].endswith("Z")
        indices = {r[1] for r in db.connection.execute("PRAGMA index_list(events)")}
        assert {"idx_events_source_ts", "idx_events_project_ts", "idx_events_session_id"} <= indices
    with pytest.raises(RuntimeError):
        with Database(config.db_path) as db:
            db.insert_event(event(source_id="rollback"))
            db.set_cursor("codex", "synthetic-file", {"offset": 100})
            raise RuntimeError("simulated collector failure")
    with Database(config.db_path) as db:
        assert db.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
        assert db.get_cursor("codex", "synthetic-file")["offset"] == 42


def test_all_persisted_free_text_is_redacted(tmp_path):
    secret = "sk-" + "Z" * 24
    config = initialize(tmp_path / "data")
    item = event(content=secret, title=secret, project=secret, session_id=secret,
                 url="https://example.invalid/?token=fake", raw_ref=secret,
                 meta={"nested": [secret], "password": "fake"})
    with Database(config.db_path) as db:
        db.insert_event(item)
        db.set_cursor("codex", "file", {"offset": 12, "note": secret})
        dump = "\n".join(db.connection.iterdump())
        assert secret not in dump
        assert "token=fake" not in dump
        assert "[REDACTED:" in dump
        meta = json.loads(db.connection.execute("SELECT meta FROM events").fetchone()[0])
        assert meta["password"] == "[REDACTED:SECRET]"


def test_rejects_future_database_without_downgrading(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError):
        Database(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_event_validation_and_capture_importance():
    assert event(source="capture", kind="capture").importance == "high"
    assert event(source_id="same").id != event(source="claude_code", source_id="same").id
    for invalid in [{"source": "unknown"}, {"kind": "visit"}, {"ts": "2026-10-22T01:00:00"}, {"source_id": ""}, {"meta": []}]:
        with pytest.raises(ValueError):
            event(**invalid)
    assert utc_timestamp(datetime(2026, 10, 22, tzinfo=timezone.utc)).endswith("Z")


def test_fractional_seconds_sort_chronologically():
    values = ["2026-10-22T01:00:00.000001Z", "2026-10-22T01:00:00Z", "2026-10-22T01:00:01Z"]
    normalized = [utc_timestamp(value) for value in values]
    assert sorted(normalized) == [normalized[1], normalized[0], normalized[2]]


def test_cursor_paths_with_different_secrets_do_not_collide(tmp_path):
    config = initialize(tmp_path / "data")
    first = "/synthetic/sk-" + "A" * 24
    second = "/synthetic/sk-" + "B" * 24
    with Database(config.db_path) as db:
        db.set_cursor("codex", first, {"offset": 1})
        db.set_cursor("codex", second, {"offset": 2})
        assert db.get_cursor("codex", first) == {"offset": 1}
        assert db.get_cursor("codex", second) == {"offset": 2}
        assert first not in "\n".join(db.connection.iterdump())
