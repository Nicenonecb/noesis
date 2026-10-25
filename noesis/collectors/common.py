"""Shared text filtering and resumable, transactional JSONL ingestion."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from ..models import Event
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


def human_text(text: str) -> str:
    # Only recognized, delimited control wrappers are stripped. Ordinary mentions
    # of AGENTS.md, environment fields, etc. remain human input.
    text = re.sub(r"(?m)^# AGENTS\.md instructions[^\n]*\n\s*<INSTRUCTIONS>.*?</INSTRUCTIONS>",
                  "", text, flags=re.DOTALL)
    for tag in ("system-reminder", "environment_context", "external_codex_apps_open_page",
                "local-command-caveat", "command-name", "command-message", "command-args",
                "local-command-stdout", "local-command-stderr"):
        text = re.sub(rf"<{tag}(?:\s[^>]*)?>.*?</{tag}>", "", text, flags=re.DOTALL)
    return text.strip()


def make_event(source, identity, role, timestamp, text, session, cwd, path, line, limit, meta=None):
    if not isinstance(session, str) or not session or (cwd is not None and not isinstance(cwd, str)):
        raise ValueError("context")
    if not isinstance(timestamp, str):
        raise ValueError("timestamp")
    text = human_text(text) if role == "user" else text.strip()
    if not text:
        return None
    clean = redact(text)
    metadata = dict(meta or {})
    metadata["cwd"] = cwd
    metadata["text_hash"] = fingerprint(text)
    metadata["session_hash"] = fingerprint(session)
    metadata["truncated"] = role == "assistant" and len(clean) > limit
    return Event(
        source=source, source_id=identity, kind=f"{role}_msg", ts=timestamp,
        content=clean[:limit] if role == "assistant" else clean,
        session_id=session, project=Path(cwd).name if cwd else None,
        raw_ref=f"{path}:{line}", meta=metadata,
    )


def read_file(db, path, source, parse, *, replay=False):
    """Commit each file and its cursor together; retain incomplete tails.

    Verify the consumed prefix on every run to detect in-place edits even if the
    inode and length are unchanged. This reads old bytes but only parses new lines.
    Replay rebuilds parser state without replacing the normal cursor.
    """
    counts = Counter(files=1)
    warnings = []
    key = str(path.resolve())
    with db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        old = None if replay else db.get_cursor(source, key)
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
            while handle.tell() < stat.st_size:
                raw = handle.readline(stat.st_size - handle.tell())
                if not raw.endswith(b"\n"):
                    counts["pending_tails"] += 1
                    break
                digest.update(raw)
                offset = handle.tell()
                line_number += 1
                counts["lines"] += 1
                try:
                    record = json.loads(raw)
                    if not isinstance(record, dict):
                        raise ValueError("record")
                    event = parse(record, state, path, line_number)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    category = "unknown_records" if isinstance(exc, UnknownRecord) else "invalid_lines"
                    counts[category] += 1
                    if len(warnings) < 20:
                        warnings.append({"file_hash": fingerprint(key), "line": line_number,
                                         "error": category})
                    continue
                if event is None:
                    counts["skipped"] += 1
                elif db.insert_event(event):
                    counts["inserted"] += 1
                else:
                    counts["duplicates"] += 1
            # An in-place rewrite during this pass must not commit a mixed view.
            handle.seek(0)
            verification = hashlib.sha256()
            remaining = offset
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError("source changed during collection")
                verification.update(chunk)
                remaining -= len(chunk)
            if verification.digest() != digest.digest():
                raise OSError("source changed during collection")
            if not replay:
                db.set_cursor(source, key, {
                    "offset": offset, "line": line_number, "device": stat.st_dev,
                    "inode": stat.st_ino, "prefix_hash": digest.hexdigest(), "state": state,
                })
    return counts, warnings
