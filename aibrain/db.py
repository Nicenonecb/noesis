"""SQLite schema and transactional writes with a mandatory redaction boundary."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .models import Event, SOURCE_KINDS, utc_timestamp
from .redact import redact, redact_value

SCHEMA_VERSION = 1
SCHEMA = '''
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('claude_code','codex','browser_history','capture','git')),
    kind TEXT NOT NULL CHECK(kind IN ('user_msg','assistant_msg','visit','capture','commit')),
    ts TEXT NOT NULL,
    session_id TEXT,
    project TEXT,
    title TEXT,
    content TEXT NOT NULL,
    url TEXT,
    meta TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(meta)),
    raw_ref TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'normal' CHECK(importance IN ('normal','high')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_source_ts ON events(source, ts);
CREATE INDEX IF NOT EXISTS idx_events_project_ts ON events(project, ts);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE TABLE IF NOT EXISTS cursors (
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(source, key)
);
'''


class Database:
    def __init__(self, path: Path):
        self.path = path
        # Reserve a newly created file privately before SQLite opens it.
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        self.connection = sqlite3.connect(path, timeout=10)
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("数据库版本比当前程序新，拒绝修改。")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.executescript(SCHEMA)
            self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.connection.commit()
        except BaseException:
            self.connection.close()
            raise
        self.connection.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()

    def insert_event(self, event: Event) -> bool:
        fields = [event.session_id, event.project, event.title, event.content, event.url, event.raw_ref]
        session_id, project, title, content, url, raw_ref = [
            redact(value) if value is not None else None for value in fields
        ]
        cursor = self.connection.execute(
            '''INSERT INTO events
               (id, source, kind, ts, session_id, project, title, content, url, meta,
                raw_ref, importance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO NOTHING''',
            (event.id, event.source, event.kind, event.ts, session_id, project, title, content,
             url, json.dumps(redact_value(event.meta), ensure_ascii=False, allow_nan=False),
             raw_ref, event.importance, utc_timestamp(datetime.now(timezone.utc))),
        )
        return cursor.rowcount == 1

    def get_cursor(self, source: str, key: str):
        if source not in SOURCE_KINDS:
            raise ValueError("不支持的 cursor 来源。")
        row = self.connection.execute(
            "SELECT value FROM cursors WHERE source=? AND key=?", (source, self._cursor_key(key))
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set_cursor(self, source: str, key: str, value) -> None:
        if source not in SOURCE_KINDS:
            raise ValueError("不支持的 cursor 来源。")
        self.connection.execute(
            '''INSERT INTO cursors(source, key, value) VALUES (?, ?, ?)
               ON CONFLICT(source, key) DO UPDATE SET value=excluded.value''',
            (source, self._cursor_key(key), json.dumps(redact_value(value), ensure_ascii=False, allow_nan=False)),
        )

    @staticmethod
    def _cursor_key(key: str) -> str:
        # Masking secret-bearing paths can merge distinct keys. Hash the original
        # key instead: stable identity, no plaintext path, no redaction collision.
        return hashlib.sha256(key.encode("utf-8")).hexdigest()
