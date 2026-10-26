"""One-shot collection with shared locking, source isolation and run records."""

from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sqlite3

from ..db import Database
from ..runtime import collection_lock, run_logger
from . import claude_code, codex, git_log, browser_history
from ..migrations import migrate
from .base import Context, CollectResult
from .common import FileReadError, read_file


def _collect_source(ctx, name, module, key, *, replay, backfill=None):
    config, db = ctx.config, ctx.db
    total, warnings = Counter(), []
    start = datetime.now(timezone.utc) - backfill if isinstance(backfill, timedelta) else None

    def ingest(path, parse):
        try:
            if start and path.stat().st_mtime < start.timestamp():
                total['filtered_files'] += 1
                return
            if name == 'claude_code' and config.values[name]['skip_sidechain'] and claude_code.is_sidechain(path):
                total['sidechains'] += 1
                return
            counts, issues = read_file(db, path, name, parse, replay=replay,
                                      reset=backfill is not None, start=start)
            total.update(counts)
            total["completed_files"] += 1
            warnings.extend(issues[:max(0, 20 - len(warnings))])
        except FileReadError as exc:
            total.update(exc.counts)
            warnings.extend(exc.issues[:max(0, 20 - len(warnings))])
            total["failed_files"] += 1
        except (OSError, sqlite3.Error):
            total["failed_files"] += 1

    root = config.source_path(name, key)
    if not root.exists():
        total["missing_sources"] += 1
    elif not root.is_dir():
        total["failed_files"] += 1
    else:
        def onerror(error):
            total["failed_files"] += 1
        paths = []
        for directory, dirs, files in os.walk(root, onerror=onerror):
            if name == "claude_code" and config.values[name]["skip_sidechain"]:
                dirs[:] = [d for d in dirs if d != "subagents"]
            paths.extend(Path(directory) / file for file in files if file.endswith(".jsonl"))
        for path in sorted(paths):
            if not path.is_symlink():
                ingest(path, module.parser(config.values[name]))
    if name == "codex":
        history = config.source_path(name, "history_file")
        if history.exists() and not history.is_symlink():
            ingest(history, codex.history_parser(config.values[name]))
        total["history_reconciled"] = codex.reconcile_history(db)
    with db.transaction():
        db.refresh_sessions(name)
    return total, warnings


@contextmanager
def collection_database(config, dry_run):
    if not dry_run:
        with Database(config.db_path) as db:
            yield db
        return
    with Database(':memory:') as db:
        original = sqlite3.connect(config.db_path.as_uri() + '?mode=ro', uri=True)
        try:
            original.backup(db.connection)
        finally:
            original.close()
        with db.transaction():
            migrate(db.connection)
        yield db


def collect(config, source="all", *, replay=False, backfill=None, dry_run=False):
    results = {}
    logger_context = nullcontext(logging.Logger('noesis.dry-run')) if dry_run else run_logger(config)
    lock_context = nullcontext() if dry_run else collection_lock(config.root)
    with lock_context, logger_context as logger, collection_database(config, dry_run) as db:
        ctx = Context(config, db, logger, config.timezone)
        for name, module, key in (("claude_code", claude_code, "root"), ("codex", codex, "sessions_root"),
                                  ('git',git_log,None),('browser_history',browser_history,None)):
            if source not in {"all", name} or not config.values["sources"][name]:
                continue
            run_id = None if dry_run else db.start_run(name)
            logger.info("source=%s started", name)
            fatal = None
            try:
                if key is None:
                    total, issues = module.collect(ctx, backfill='all' if replay else backfill, dry_run=dry_run)
                else:
                    total, issues = _collect_source(ctx, name, module, key, replay=replay, backfill=backfill)
            except Exception as exc:
                # Source data and exception text may contain secrets. Only retain the type.
                fatal = type(exc).__name__
                total, issues = Counter(failed_files=1), []
            summary = CollectResult(
                name, total["inserted"], total["duplicates"],
                sum(total[key] for key in ("invalid_lines", "unknown_records", "failed_files", "missing_sources",'discovery_warnings','missing_authors')),
                [fatal] if fatal else (["file_failure"] if total["failed_files"] else []),
            )
            failed_all = total["failed_files"] and not total["completed_files"] and not total["lines"]
            status = "failed" if fatal or failed_all else ("partial" if summary.warnings else "ok")
            if run_id:
                db.finish_run(run_id, status=status, inserted=summary.inserted, skipped=summary.skipped,
                              warnings=summary.warnings, error=",".join(summary.errors) or None)
            log = logger.warning if summary.warnings else logger.info
            log("source=%s status=%s inserted=%d duplicates=%d warnings=%d error=%s",
                name, status, summary.inserted, summary.skipped, summary.warnings, fatal or "none")
            # Preserve M1's JSON fields; skipped historically means filtered lines.
            results[name] = dict(total) | {"warnings": issues, "warning_count": summary.warnings, "status": status, 'dry_run': dry_run}
        if config.values['sources']['git'] and source in {'all','git'}:
            with db.transaction():
                db.reproject()
    return results
