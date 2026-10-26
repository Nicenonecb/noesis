"""Repository registry, with one entry per shared Git directory."""


def apply(conn):
    conn.execute('''CREATE TABLE repos (
        path TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, common_dir TEXT NOT NULL UNIQUE,
        discovered_via TEXT NOT NULL CHECK(discovered_via IN ('config','scan','session')),
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
    )''')
