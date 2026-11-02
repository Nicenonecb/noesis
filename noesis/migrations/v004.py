"""Add DSH as a conversation source; SQLite CHECK constraints require a rebuild."""

EVENTS = '''CREATE TABLE events_new (
    id TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('claude_code','codex','dsh','browser_history','capture','git')),
    kind TEXT NOT NULL CHECK(kind IN ('user_msg','assistant_msg','visit','capture','commit')),
    ts TEXT NOT NULL, session_id TEXT, project TEXT, title TEXT,
    content TEXT NOT NULL, url TEXT,
    meta TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(meta)),
    raw_ref TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'normal' CHECK(importance IN ('normal','high')),
    created_at TEXT NOT NULL,
    source_id TEXT
)'''

SESSIONS = '''CREATE TABLE sessions_new (
    id TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('claude_code','codex','dsh')),
    session_id TEXT NOT NULL, project TEXT, cwd TEXT, title TEXT NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
    n_user INTEGER NOT NULL CHECK(n_user >= 0),
    n_assistant INTEGER NOT NULL CHECK(n_assistant >= 0),
    raw_path TEXT NOT NULL,
    UNIQUE(source, session_id)
)'''

INDEXES = (
    'CREATE INDEX idx_events_source_ts ON events(source, ts)',
    'CREATE INDEX idx_events_project_ts ON events(project, ts)',
    'CREATE INDEX idx_events_session_id ON events(session_id)',
    'CREATE INDEX idx_events_ts ON events(ts)',
    'CREATE INDEX idx_events_created_at ON events(created_at)',
)

TRIGGERS = (
    '''CREATE TRIGGER events_ai AFTER INSERT ON events BEGIN
        INSERT INTO events_fts(rowid,title,content,url) VALUES(new.rowid,new.title,new.content,new.url);
    END''',
    '''CREATE TRIGGER events_ad AFTER DELETE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,title,content,url)
        VALUES('delete',old.rowid,old.title,old.content,old.url);
    END''',
    '''CREATE TRIGGER events_au AFTER UPDATE ON events BEGIN
        INSERT INTO events_fts(events_fts,rowid,title,content,url)
        VALUES('delete',old.rowid,old.title,old.content,old.url);
        INSERT INTO events_fts(rowid,title,content,url) VALUES(new.rowid,new.title,new.content,new.url);
    END''',
)


def apply(conn):
    for trigger in ('events_ai', 'events_ad', 'events_au'):
        conn.execute(f'DROP TRIGGER IF EXISTS {trigger}')
    conn.execute('ALTER TABLE events RENAME TO events_old')
    conn.execute(EVENTS)
    conn.execute('''INSERT INTO events_new
        (id,source,kind,ts,session_id,project,title,content,url,meta,raw_ref,importance,created_at,source_id)
        SELECT id,source,kind,ts,session_id,project,title,content,url,meta,raw_ref,importance,created_at,source_id
        FROM events_old''')
    conn.execute('DROP TABLE events_old')
    conn.execute('ALTER TABLE events_new RENAME TO events')
    for sql in INDEXES + TRIGGERS:
        conn.execute(sql)
    conn.execute("INSERT INTO events_fts(events_fts) VALUES('rebuild')")
    conn.execute('ALTER TABLE sessions RENAME TO sessions_old')
    conn.execute(SESSIONS)
    conn.execute('''INSERT INTO sessions_new
        (id,source,session_id,project,cwd,title,started_at,ended_at,n_user,n_assistant,raw_path)
        SELECT id,source,session_id,project,cwd,title,started_at,ended_at,n_user,n_assistant,raw_path
        FROM sessions_old''')
    conn.execute('DROP TABLE sessions_old')
    conn.execute('ALTER TABLE sessions_new RENAME TO sessions')
    conn.execute('CREATE INDEX idx_sessions_time ON sessions(started_at, ended_at)')
