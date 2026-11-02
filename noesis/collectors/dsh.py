"""DeepSeek Harness sessions: zstd-compressed JSONL with user/assistant messages."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

from ..models import utc_timestamp
from .common import fingerprint, make_event

SESSION_FILE = 'session.v4.jsonl.zstd'


def _timestamp(milliseconds):
    if type(milliseconds) is not int:
        raise ValueError('timestamp')
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc)


def _text(content):
    if not isinstance(content, list):
        return '', 0
    parts, images = [], 0
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'image':
            images += 1
        elif item.get('type') in {'text', 'input_text', 'output_text'} and isinstance(item.get('text'), str):
            parts.append(item['text'])
    return '\n'.join(parts).strip(), images


def _zstd(path):
    executable = shutil.which('zstd')
    if executable is None:
        raise OSError('zstd_missing')
    result = subprocess.run([executable, '-dc', str(path)], capture_output=True, timeout=60)
    if result.returncode:
        raise OSError('zstd_failed')
    return result.stdout.decode('utf-8', errors='replace').splitlines()


def parse_session(path, settings):
    """Return (session hint, events, counts). Unknown DSH events are ignored."""
    lines = _zstd(path)
    session = cwd = title = None
    identity = path.parent.name.removeprefix('session-')
    created = None
    events, counts = [], Counter(lines=len(lines))
    started = ended = None
    for number, raw in enumerate(lines, 1):
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError('record')
        except (ValueError, TypeError):
            counts['invalid_lines'] += 1
            continue
        kind = record.get('type')
        if kind == 'session':
            session = record.get('id') or identity
            cwd = record.get('cwd') if isinstance(record.get('cwd'), str) else None
            created = record.get('createdAt')
            continue
        if kind == 'session/title':
            candidate = record.get('data', {}).get('title')
            if isinstance(candidate, str) and candidate.strip():
                title = candidate.strip()[:200]
            continue
        if kind not in {'user/message', 'assistant/message'}:
            continue
        data = record.get('data')
        if not isinstance(data, dict):
            counts['invalid_lines'] += 1
            continue
        try:
            stamp = _timestamp(record.get('time'))
        except (ValueError, TypeError, OverflowError):
            counts['invalid_lines'] += 1
            continue
        message = data if kind == 'user/message' else data.get('message')
        if not isinstance(message, dict):
            counts['invalid_lines'] += 1
            continue
        role = message.get('role')
        if role not in {'user', 'assistant'}:
            counts['invalid_lines'] += 1
            continue
        if role == 'user':
            source = message.get('source')
            if not isinstance(source, dict) or source.get('kind') != 'user':
                counts['skipped'] += 1
                continue
            content = message.get('content')
            message_id = message.get('id')
        else:
            content = message.get('content')
            message_id = message.get('id')
        text, images = _text(content)
        if not text:
            counts['skipped'] += 1
            continue
        message_id = message_id if isinstance(message_id, str) and message_id else str(record.get('seq', number))
        event = make_event('dsh', f"{session or identity}:{role}:{message_id}", role, utc_timestamp(stamp), text,
                           session or identity, cwd, path, number, settings['max_assistant_chars'],
                           {'channel': 'dsh', 'agent': 'dsh', 'message_id': message_id,
                            'turn': data.get('turn'), 'step': data.get('step'), 'images': images})
        if event:
            events.append(event)
            started = min(started or stamp, stamp)
            ended = max(ended or stamp, stamp)
    if created is not None:
        try:
            created = _timestamp(created)
        except (ValueError, TypeError, OverflowError):
            created = None
    started = started or created
    ended = ended or started
    hint = {'session': session or identity, 'cwd': cwd, 'title': title or '',
            'started_at': utc_timestamp(started) if started else None,
            'ended_at': utc_timestamp(ended) if ended else None}
    return hint, events, counts


def collect(ctx, *, backfill=None, dry_run=False):
    config, db = ctx.config, ctx.db
    root = config.source_path('dsh', 'root')
    counts, issues = Counter(inserted=0, duplicates=0), []
    if not root.exists():
        counts['missing_sources'] += 1
        return counts, issues
    if not root.is_dir():
        counts['failed_files'] += 1
        issues.append({'error': 'not_a_directory'})
        return counts, issues
    start = datetime.now(timezone.utc) - backfill if isinstance(backfill, timedelta) else None
    replay = backfill == 'all'
    paths = sorted(root.rglob(SESSION_FILE))
    if not paths:
        counts['missing_sources'] += 1
        return counts, issues
    for path in paths:
        if path.is_symlink():
            continue
        key = str(path.resolve())
        try:
            stat = path.stat()
        except OSError:
            counts['failed_files'] += 1
            continue
        if not replay and backfill is None:
            cursor = db.get_cursor('dsh', key)
            if cursor and cursor.get('size') == stat.st_size and cursor.get('mtime_ns') == stat.st_mtime_ns:
                counts['skipped_files'] += 1
                continue
        try:
            hint, events, parsed = parse_session(path, config.values['dsh'])
        except (OSError, subprocess.SubprocessError) as exc:
            counts['failed_files'] += 1
            issues.append({'file_hash': fingerprint(key), 'error': str(exc)[:40]})
            continue
        counts.update({name: value for name, value in parsed.items() if name != 'lines'})
        counts['lines'] += parsed['lines']
        selected = [event for event in events if not start or event.ts >= utc_timestamp(start)]
        counts['filtered_by_date'] += len(events) - len(selected)
        with db.transaction():
            for event in selected:
                if db.insert_event(event):
                    counts['inserted'] += 1
                else:
                    counts['duplicates'] += 1
            if hint['session'] and hint['started_at'] and hint['ended_at']:
                db.record_session_hint('dsh', hint, path)
            if not dry_run and not replay:
                db.set_cursor('dsh', key, {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                                           'session': hint['session']})
        counts['files'] += 1
        counts['completed_files'] += 1
    if not dry_run:
        with db.transaction():
            db.refresh_sessions('dsh')
    return counts, issues
