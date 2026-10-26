"""Disposable copies of live application databases; never open originals in SQLite."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import tempfile


@contextmanager
def history_snapshot(path):
    with tempfile.TemporaryDirectory(prefix='noesis-history-') as temporary:
        target=Path(temporary)/path.name
        for attempt in range(2):
            connection=None
            try:
                for suffix in ('','-wal','-journal'):
                    source=path.with_name(path.name+suffix)
                    copy=target.with_name(target.name+suffix)
                    if source.exists() or not suffix:
                        shutil.copyfile(source,copy)
                        copy.chmod(0o600)
                    else:
                        copy.unlink(missing_ok=True)
                connection=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)
                connection.row_factory=sqlite3.Row
                if connection.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise sqlite3.DatabaseError('inconsistent snapshot')
                break
            except (OSError,sqlite3.Error):
                if connection:
                    connection.close()
                if attempt:
                    raise
        try:
            yield connection
        finally:
            connection.close()
