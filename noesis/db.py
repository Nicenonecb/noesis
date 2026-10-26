"""Transactional writes with mandatory redaction; reads live in queries.py."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .migrations import SCHEMA_VERSION, migrate
from .models import Event, Session, SOURCE_KINDS, utc_timestamp
from .redact import redact, redact_value


def _json(value):
    return json.dumps(redact_value(value), ensure_ascii=False, allow_nan=False)


def insert_event(conn, event: Event) -> bool:
    fields = [event.session_id, event.project, event.title, event.content, event.url, event.raw_ref]
    session_id, project, title, content, url, raw_ref = [
        redact(value) if value is not None else None for value in fields
    ]
    cursor = conn.execute(
        '''INSERT INTO events
           (id, source, kind, ts, session_id, project, title, content, url, meta,
            raw_ref, importance, created_at, source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO NOTHING''',
        (event.id, event.source, event.kind, event.ts, session_id, project, title, content,
         url, _json(event.meta), raw_ref, event.importance,
         utc_timestamp(datetime.now(timezone.utc)), redact(event.source_id)),
    )
    return cursor.rowcount == 1


def upsert_events(conn, events):
    inserted = skipped = 0
    for event in events:
        if insert_event(conn, event):
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def update_event_meta(conn, event_id: str, patch: dict):
    if not isinstance(patch, dict):
        raise ValueError("metadata patch 必须是字典。")
    conn.execute("UPDATE events SET meta=json_patch(meta, ?) WHERE id=?", (_json(patch), event_id))


def upsert_session(conn, session: Session):
    fields = asdict(session)
    clean = {key: redact(value) if isinstance(value, str) else value for key, value in fields.items()}
    conn.execute(
        '''INSERT INTO sessions
           (id,source,session_id,started_at,ended_at,project,cwd,title,n_user,n_assistant,raw_path)
           VALUES (:id,:source,:session_id,:started_at,:ended_at,:project,:cwd,:title,:n_user,:n_assistant,:raw_path)
           ON CONFLICT(id) DO UPDATE SET
           started_at=excluded.started_at, ended_at=excluded.ended_at, project=excluded.project,
           cwd=excluded.cwd, title=excluded.title, n_user=excluded.n_user,
           n_assistant=excluded.n_assistant, raw_path=excluded.raw_path''',
        clean | {"id": session.id},
    )


def _cursor_key(source, key):
    if source not in SOURCE_KINDS:
        raise ValueError("不支持的 cursor 来源。")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def get_cursor(conn, source, key):
    row = conn.execute("SELECT value FROM cursors WHERE source=? AND key=?",
                       (source, _cursor_key(source, key))).fetchone()
    return json.loads(row[0]) if row else None


def set_cursor(conn, source, key, value):
    conn.execute(
        '''INSERT INTO cursors(source,key,value) VALUES (?,?,?)
           ON CONFLICT(source,key) DO UPDATE SET value=excluded.value''',
        (source, _cursor_key(source, key), _json(value)),
    )


class Database:
    def __init__(self, path: Path | str):
        self.path = path
        if str(path) != ":memory:":
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            os.close(fd)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("数据库版本比当前程序新，拒绝修改。")
            self.connection.execute("PRAGMA journal_mode=WAL")
            with self.transaction():
                migrate(self.connection)
                if version < 2:
                    self.refresh_sessions()
        except BaseException:
            self.connection.close()
            raise

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

    @contextmanager
    def transaction(self):
        """One event/cursor checkpoint; failures roll back this entire batch."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            yield

    def insert_event(self, event):
        return insert_event(self.connection, event)

    def upsert_events(self, events):
        inserted = skipped = 0
        for event in events:
            if self.insert_event(event):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def update_event_meta(self, event_id, patch):
        update_event_meta(self.connection, event_id, patch)

    def upsert_session(self, session):
        upsert_session(self.connection, session)

    def get_cursor(self, source, key):
        return get_cursor(self.connection, source, key)

    def set_cursor(self, source, key, value):
        set_cursor(self.connection, source, key, value)

    def delete_events(self, identities):
        self.connection.executemany("DELETE FROM events WHERE id=?", ((item,) for item in identities))

    def refresh_sessions(self, source=None):
        from .queries import session_summaries
        for session in session_summaries(self.connection, source=source):
            self.upsert_session(session)

    def start_run(self, source):
        identity = uuid4().hex
        # An interrupted run remains failed with no finish time, never a false ok.
        with self.transaction():
            self.connection.execute(
                "INSERT INTO ingest_runs(id,source,started_at,status,error) VALUES (?,?,?,'failed','interrupted')",
                (identity, source, utc_timestamp(datetime.now(timezone.utc))),
            )
        return identity

    def finish_run(self, identity, *, status, inserted, skipped, warnings, error=None):
        with self.transaction():
            self.connection.execute(
                '''UPDATE ingest_runs SET finished_at=?,status=?,inserted=?,skipped=?,warnings=?,error=?
                   WHERE id=?''',
                (utc_timestamp(datetime.now(timezone.utc)), status, inserted, skipped, warnings,
                 redact(error) if error else None, identity),
            )
