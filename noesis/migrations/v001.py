"""Original M0 schema; preserve existing event IDs and cursor storage."""

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('claude_code','codex','browser_history','capture','git')),
        kind TEXT NOT NULL CHECK(kind IN ('user_msg','assistant_msg','visit','capture','commit')),
        ts TEXT NOT NULL, session_id TEXT, project TEXT, title TEXT,
        content TEXT NOT NULL, url TEXT,
        meta TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(meta)),
        raw_ref TEXT NOT NULL,
        importance TEXT NOT NULL DEFAULT 'normal' CHECK(importance IN ('normal','high')),
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_source_ts ON events(source, ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_project_ts ON events(project, ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id)",
    """CREATE TABLE IF NOT EXISTS cursors (
        source TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        PRIMARY KEY(source, key)
    )""",
)


def apply(conn):
    for sql in STATEMENTS:
        conn.execute(sql)
