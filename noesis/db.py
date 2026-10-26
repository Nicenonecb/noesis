"""Transactional writes with mandatory redaction; reads live in queries.py."""

from contextlib import contextmanager
from dataclasses import asdict, replace
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


def _event_values(event):
    fields = [event.session_id, event.project, event.title, event.content, event.url, event.raw_ref]
    session_id, project, title, content, url, raw_ref = [
        redact(value) if value is not None else None for value in fields
    ]
    return (event.id, event.source, event.kind, event.ts, session_id, project, title, content,
            url, _json(event.meta), raw_ref, event.importance, redact(event.source_id))


def insert_event(conn, event: Event) -> bool:
    cursor = conn.execute(
        """INSERT INTO events
           (id,source,kind,ts,session_id,project,title,content,url,meta,raw_ref,importance,source_id,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
        _event_values(event) + (utc_timestamp(datetime.now(timezone.utc)),),
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
        return upsert_events(self.connection, events)

    def replace_event(self, event):
        """Update in place, retaining rowid and the original created_at."""
        values = _event_values(event)
        self.connection.execute(
            """UPDATE events SET source=?,kind=?,ts=?,session_id=?,project=?,title=?,content=?,
               url=?,meta=?,raw_ref=?,importance=?,source_id=? WHERE id=?""",
            values[1:] + (event.id,))

    def merge_assistant(self, event):
        from .queries import get_event, legacy_fragment_ids
        old = get_event(self.connection, event.id)
        fragment = event.meta['fragment_id']
        self.delete_events(legacy_fragment_ids(self.connection, event))
        if old and fragment in old.meta.get('fragment_ids', []):
            return False
        limit = event.meta['max_chars']
        incoming = event.content[:min(event.meta['content_chars'], limit)]
        if old and old.meta.get('fragment_ids'):
            previous_chars = old.meta['content_chars']
            separator = '\n' if previous_chars and event.meta['content_chars'] else ''
            full_chars = previous_chars + len(separator) + event.meta['content_chars']
            retained = old.content[:min(previous_chars, limit)]
            if previous_chars < limit:
                retained = (retained + separator + incoming)[:limit]
            meta = old.meta | event.meta | {
                'content_chars': full_chars,
                'fragment_ids': old.meta['fragment_ids'] + [fragment],
                'tools': old.meta.get('tools', []) + event.meta.get('tools', []),
            }
            event = replace(event, ts=min(old.ts, event.ts), raw_ref=old.raw_ref, content=retained, meta=meta)
        else:
            full_chars = event.meta['content_chars']
            event = replace(event, content=incoming, meta=event.meta | {'fragment_ids': [fragment]})
        content = event.content[:limit]
        if full_chars > limit:
            content += f'…[truncated {full_chars - limit} chars]'
        event = replace(event, content=content, meta=event.meta | {'truncated': full_chars > limit})
        if old:
            self.replace_event(event)
        else:
            self.insert_event(event)
        return old is None

    def upsert_codex_event(self, event):
        from .queries import get_event
        old = get_event(self.connection, event.id)
        if old is None:
            return self.insert_event(event)
        order = ['completed', 'response', 'legacy'] if event.kind == 'user_msg' else ['legacy', 'completed', 'response']
        priority = {channel: index for index, channel in enumerate(order)}
        preferred = priority.get(event.meta.get('channel'), -1) > priority.get(old.meta.get('channel'), -1)
        meta = old.meta | event.meta if preferred else event.meta | old.meta
        for key in ('history_matches', 'tools', 'tool_call_ids'):
            if key in old.meta:
                meta[key] = old.meta[key]
        replacement = replace(event if preferred else old, meta=meta)
        if replacement != old:
            self.replace_event(replacement)
        return False

    def append_tool(self, update):
        from .queries import get_event
        event = get_event(self.connection, update.event_id)
        if event is None or update.call_id in event.meta.get('tool_call_ids', []):
            return
        self.update_event_meta(event.id, {'tools': event.meta.get('tools', []) + [update.tool],
                                         'tool_call_ids': event.meta.get('tool_call_ids', []) + [update.call_id]})

    def record_session_hint(self, source, state, path):
        from .queries import session_record
        from .projects import resolve_project
        if not state.get('session') or not state.get('started_at'):
            return
        current = session_record(self.connection, source, redact(state['session']))
        session = current or Session(source, state['session'], state['started_at'], state['ended_at'])
        self.upsert_session(replace(session, title=state.get('title') or session.title,
                                    cwd=state.get('cwd') or session.cwd,
                                    project=resolve_project(state.get('cwd')) or session.project,
                                    raw_path=str(path)))

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
