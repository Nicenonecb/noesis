"""Shared text filtering and resumable, transactional JSONL ingestion."""

from collections import Counter
import hashlib
import json
import os
import re
import sqlite3

from ..models import Event, ToolUpdate, utc_timestamp
from ..projects import resolve_project
from ..redact import redact


class UnknownRecord(ValueError):
    """Unrecognized format; report location only, never raw data."""


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"] for block in content
        if isinstance(block, dict)
        and block.get("type") in {"text", "Text", "input_text", "output_text"}
        and isinstance(block.get("text"), str)
    )


def human_text(text: str, strip_tags=None) -> str:
    # Only recognized, delimited control wrappers are stripped. Ordinary mentions
    # of AGENTS.md, environment fields, etc. remain human input.
    text = re.sub(r"(?m)^# AGENTS\.md instructions[^\n]*\n\s*<INSTRUCTIONS>.*?</INSTRUCTIONS>",
                  "", text, flags=re.DOTALL)
    for tag in strip_tags if strip_tags is not None else ("system-reminder", "environment_context", "external_codex_apps_open_page",
                "user_instructions", "permissions instructions",
                "local-command-caveat", "command-name", "command-message", "command-args",
                "local-command-stdout", "local-command-stderr"):
        text = re.sub(rf"<{re.escape(tag)}(?:\s[^>]*)?>.*?</{re.escape(tag)}>", "", text, flags=re.DOTALL)
    return text.strip()


def make_event(source, identity, role, timestamp, text, session, cwd, path, line, limit, meta=None):
    if not isinstance(session, str) or not session or (cwd is not None and not isinstance(cwd, str)):
        raise ValueError("context")
    if not isinstance(timestamp, str):
        raise ValueError("timestamp")
    text = human_text(text) if role == "user" else text.strip()
    if not text and not (meta or {}).get("tools"):
        return None
    clean = redact(text)
    metadata = dict(meta or {})
    metadata["cwd"] = cwd
    metadata["text_hash"] = fingerprint(text)
    metadata["text_prefix_hash"] = fingerprint(text[:100])
    metadata["session_hash"] = fingerprint(session)
    metadata["truncated"] = role == "assistant" and len(clean) > limit
    metadata["content_chars"] = len(clean)
    return Event(
        source=source, source_id=identity, kind=f"{role}_msg", ts=timestamp,
        content=truncate(clean, limit) if role == "assistant" else clean,
        session_id=session, project=resolve_project(cwd),
        raw_ref=f"{path}:{line}", meta=metadata,
    )


def truncate(text, limit):
    """The limit bounds retained content; the explanatory suffix is additional."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated {len(text) - limit} chars]"


class FileReadError(OSError):
    """A failed file can already have durable earlier batches."""

    def __init__(self, counts, issues):
        super().__init__("source read/checkpoint failed")
        self.counts = counts
        self.issues = issues


def read_file(db, path, source, parse, *, replay=False, reset=False, start=None):
    """Checkpoint at most 500 complete records with their exact parser cursor.

    Verify the old prefix to retain M1's same-size rewrite detection. Re-read
    each new batch before committing it to detect concurrent changes in that
    batch. Failure rolls back the current batch; earlier checkpoints survive.
    Replay rebuilds parser state without replacing the normal cursor.
    """
    counts = Counter(files=1)
    warnings = []
    key = str(path.resolve())
    try:
        old = None if replay or reset else db.get_cursor(source, key)
        with path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            offset = old.get("offset", 0) if old else 0
            digest = hashlib.sha256()
            valid = bool(old and old.get("device") == stat.st_dev
                         and old.get("inode") == stat.st_ino and offset <= stat.st_size)
            if valid:
                remaining = offset
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        valid = False
                        break
                    digest.update(chunk)
                    remaining -= len(chunk)
                valid = valid and digest.hexdigest() == old.get("prefix_hash")
            if valid:
                state = old["state"]
                line_number = old["line"]
            else:
                offset, line_number, state = 0, 0, {}
                handle.seek(0)
                digest = hashlib.sha256()
                if old:
                    counts["resets"] += 1
            finished = False
            while not finished:
                batch_start = offset
                batch_hash = hashlib.sha256()
                batch_counts = Counter()
                batch_warnings = []
                with db.transaction():
                    for _ in range(500):
                        if handle.tell() >= stat.st_size:
                            finished = True
                            break
                        raw = handle.readline(stat.st_size - handle.tell())
                        if not raw.endswith(b"\n"):
                            batch_counts["pending_tails"] += 1
                            finished = True
                            break
                        digest.update(raw)
                        batch_hash.update(raw)
                        offset = handle.tell()
                        line_number += 1
                        batch_counts["lines"] += 1
                        try:
                            record = json.loads(raw)
                            if not isinstance(record, dict):
                                raise ValueError("record")
                            event = parse(record, state, path, line_number)
                        except (ValueError, TypeError, KeyError, OverflowError) as exc:
                            category = "unknown_records" if isinstance(exc, UnknownRecord) else "invalid_lines"
                            batch_counts[category] += 1
                            if len(batch_warnings) < 20:
                                batch_warnings.append({"file_hash": fingerprint(key), "line": line_number,
                                                       "error": category})
                            continue
                        if event is None:
                            batch_counts["skipped"] += 1
                        elif isinstance(event, ToolUpdate):
                            if not start or event.ts >= utc_timestamp(start):
                                db.append_tool(event)
                            batch_counts['skipped'] += 1
                        elif start and event.ts < utc_timestamp(start):
                            batch_counts['filtered_by_date'] += 1
                        elif (db.merge_assistant(event) if event.meta.get("fragment_id") else
                              db.upsert_codex_event(event) if source == 'codex' else db.insert_event(event)):
                            batch_counts["inserted"] += 1
                        else:
                            batch_counts["duplicates"] += 1
                    handle.seek(batch_start)
                    verification = hashlib.sha256()
                    remaining = offset - batch_start
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise OSError("source changed during collection")
                        verification.update(chunk)
                        remaining -= len(chunk)
                    if verification.digest() != batch_hash.digest():
                        raise OSError("source changed during collection")
                    if not replay:
                        db.set_cursor(source, key, {
                            "offset": offset, "line": line_number, "device": stat.st_dev,
                            "inode": stat.st_ino, "size": stat.st_size, "mtime": stat.st_mtime_ns,
                            "prefix_hash": digest.hexdigest(), "state": state,
                        })
                    db.record_session_hint(source, state, path)
                counts.update(batch_counts)
                warnings.extend(batch_warnings[:max(0, 20 - len(warnings))])
    except (OSError, sqlite3.Error) as exc:
        raise FileReadError(counts, warnings) from exc
    return counts, warnings
