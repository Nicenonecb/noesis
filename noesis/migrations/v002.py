"""Shared query foundation and a synchronized index of existing events."""

STATEMENTS = (
    "ALTER TABLE events ADD COLUMN source_id TEXT",
    "CREATE INDEX idx_events_ts ON events(ts)",
    "CREATE INDEX idx_events_created_at ON events(created_at)",
    """CREATE TABLE sessions (
        id TEXT PRIMARY KEY NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('claude_code','codex')),
        session_id TEXT NOT NULL, project TEXT, cwd TEXT, title TEXT NOT NULL,
        started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
        n_user INTEGER NOT NULL CHECK(n_user >= 0),
        n_assistant INTEGER NOT NULL CHECK(n_assistant >= 0),
        raw_path TEXT NOT NULL,
        UNIQUE(source, session_id)
    )""",
    "CREATE INDEX idx_sessions_time ON sessions(started_at, ended_at)",
    """CREATE TABLE ingest_runs (
        id TEXT PRIMARY KEY NOT NULL, source TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT,
        status TEXT NOT NULL CHECK(status IN ('ok','partial','failed')),
        inserted INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
        warnings INTEGER NOT NULL DEFAULT 0, error TEXT
    )""",
    "CREATE INDEX idx_ingest_runs_source_time ON ingest_runs(source, started_at)",
    """CREATE VIRTUAL TABLE events_fts USING fts5(
        title, content, url, content='events', content_rowid='rowid', tokenize='trigram'
    )""",
    """CREATE TRIGGER events_ai AFTER INSERT ON events BEGIN
        INSERT INTO events_fts(rowid,title,content,url) VALUES(new.rowid,new.title,new.content,new.url);
    END""",
    """CREATE TRIGGER events_ad AFTER DELETE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,title,content,url)
        VALUES('delete',old.rowid,old.title,old.content,old.url);
    END""",
    """CREATE TRIGGER events_au AFTER UPDATE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,title,content,url)
        VALUES('delete',old.rowid,old.title,old.content,old.url);
        INSERT INTO events_fts(rowid,title,content,url) VALUES(new.rowid,new.title,new.content,new.url);
    END""",
    "INSERT INTO events_fts(events_fts) VALUES('rebuild')",
)


def apply(conn):
    for sql in STATEMENTS:
        conn.execute(sql)
