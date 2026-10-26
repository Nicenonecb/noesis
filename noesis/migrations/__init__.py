"""Ordered SQLite migrations, executed inside the caller's transaction."""

from . import v001, v002

SCHEMA_VERSION = 2


def migrate(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError("数据库版本比当前程序新，拒绝修改。")
    for number, migration in enumerate((v001, v002), start=1):
        if version < number:
            migration.apply(conn)
            conn.execute(f"PRAGMA user_version={number}")
