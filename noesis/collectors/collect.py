"""One-shot local conversation collection; no scheduler or network access."""

from collections import Counter
import os
from pathlib import Path

from ..db import Database
from . import claude_code, codex
from .common import read_file


def collect(config, source="all", *, replay=False):
    results = {}
    with Database(config.db_path) as db:
        for name, module, key in (("claude_code", claude_code, "root"),
                                  ("codex", codex, "sessions_root")):
            if source not in {"all", name} or not config.values["sources"][name]:
                continue
            total = Counter()
            warnings = []
            root = config.source_path(name, key)
            if not root.exists():
                total["missing_sources"] += 1
            elif not root.is_dir():
                total["failed_files"] += 1
            else:
                # os.walk reports permission failures instead of silently missing files.
                def onerror(error):
                    total["failed_files"] += 1
                paths = []
                for directory, dirs, files in os.walk(root, onerror=onerror):
                    if name == "claude_code" and config.values[name]["skip_sidechain"]:
                        dirs[:] = [d for d in dirs if d != "subagents"]
                    paths.extend(Path(directory) / file
                                 for file in files if file.endswith(".jsonl"))
                for path in sorted(paths):
                    if path.is_symlink():
                        continue
                    try:
                        counts, issues = read_file(db, path, name, module.parser(config.values[name]), replay=replay)
                        total.update(counts)
                        warnings.extend(issues[:max(0, 20 - len(warnings))])
                    except OSError:
                        total["failed_files"] += 1
            if name == "codex":
                history = config.source_path(name, "history_file")
                if history.exists() and not history.is_symlink():
                    try:
                        counts, issues = read_file(db, history, name, codex.history_parser(config.values[name]), replay=replay)
                        total.update(counts)
                        warnings.extend(issues[:max(0, 20 - len(warnings))])
                    except OSError:
                        total["failed_files"] += 1
                total["history_reconciled"] = codex.reconcile_history(db)
            results[name] = dict(total) | {"warnings": warnings}
    return results
