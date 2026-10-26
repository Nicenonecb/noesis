"""One-shot collection with shared locking, source isolation and run records."""

from collections import Counter
import os
from pathlib import Path
import sqlite3

from ..db import Database
from ..runtime import collection_lock, run_logger
from . import claude_code, codex
from .base import Context, CollectResult
from .common import FileReadError, read_file


def _collect_source(ctx, name, module, key, *, replay):
    config, db = ctx.config, ctx.db
    total, warnings = Counter(), []

    def ingest(path, parse):
        try:
            if name == 'claude_code' and config.values[name]['skip_sidechain'] and claude_code.is_sidechain(path):
                total['sidechains'] += 1
                return
            counts, issues = read_file(db, path, name, parse, replay=replay)
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


def collect(config, source="all", *, replay=False):
    results = {}
    with collection_lock(config.root), run_logger(config) as logger, Database(config.db_path) as db:
        ctx = Context(config, db, logger, config.timezone)
        for name, module, key in (("claude_code", claude_code, "root"), ("codex", codex, "sessions_root")):
            if source not in {"all", name} or not config.values["sources"][name]:
                continue
            run_id = db.start_run(name)
            logger.info("source=%s started", name)
            fatal = None
            try:
                total, issues = _collect_source(ctx, name, module, key, replay=replay)
            except Exception as exc:
                # Source data and exception text may contain secrets. Only retain the type.
                fatal = type(exc).__name__
                total, issues = Counter(failed_files=1), []
            summary = CollectResult(
                name, total["inserted"], total["duplicates"],
                sum(total[key] for key in ("invalid_lines", "unknown_records", "failed_files", "missing_sources")),
                [fatal] if fatal else (["file_failure"] if total["failed_files"] else []),
            )
            failed_all = total["failed_files"] and not total["completed_files"] and not total["lines"]
            status = "failed" if fatal or failed_all else ("partial" if summary.warnings else "ok")
            db.finish_run(run_id, status=status, inserted=summary.inserted, skipped=summary.skipped,
                          warnings=summary.warnings, error=",".join(summary.errors) or None)
            log = logger.warning if summary.warnings else logger.info
            log("source=%s status=%s inserted=%d duplicates=%d warnings=%d error=%s",
                name, status, summary.inserted, summary.skipped, summary.warnings, fatal or "none")
            # Preserve M1's JSON fields; skipped historically means filtered lines.
            results[name] = dict(total) | {"warnings": issues, "warning_count": summary.warnings, "status": status}
    return results
