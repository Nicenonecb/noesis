"""Import screenshots that other tools already saved into watched folders."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import time

from .. import queries
from ..db import Database
from ..models import Event
from ..redact import redact
from ..runtime import AlreadyRunning, file_lock, run_logger
from .capture import new_capture, start_enrichment

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.heic', '.webp', '.tiff'}
SYSTEM_NAME = re.compile(r'^(?:screenshot|screen shot|截屏|屏幕快照|屏幕截图|截图)', re.IGNORECASE)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def import_title(path, local_time):
    if SYSTEM_NAME.match(path.stem):
        return f'截图 {local_time:%Y-%m-%d %H:%M}'
    return path.stem[:80]


def import_screenshot(config, source, *, move=True, background=True):
    """Copy or move one image into captures/; the same bytes are imported once."""
    source = Path(source).expanduser()
    if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('不是可导入的图片。')
    source = source.resolve()
    if source.stat().st_size == 0:
        raise ValueError('图片为空。')
    if source.is_relative_to((config.root / 'captures').resolve()):
        raise ValueError('该图片已经在收藏目录中。')
    digest = file_digest(source)
    modified = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
    with Database(config.db_path) as db:
        existing = queries.capture_by_hash(db.connection, digest)
        if existing:
            return {'status': 'duplicate', 'id': existing}
        identity, destination = new_capture(config)
        try:
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
            local = modified.astimezone(config.timezone)
            event = Event('capture', identity, 'capture', modified,
                          title=redact(import_title(source, local)),
                          meta={'app_bundle': '', 'app_name': '截图导入',
                                'window_title': redact(source.stem)[:200],
                                'screenshot': str(destination.relative_to(config.root)),
                                'ocr_status': 'pending', 'note': '', 'selection': '',
                                'page_text_len': 0, 'text_sections': [],
                                'content_hash': digest,
                                'imported_from': 'inbox',
                                'imported_name': redact(source.name)[:200]})
            inserted = db.insert_event(event)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if not inserted:
            destination.unlink(missing_ok=True)
            raise ValueError('收藏 ID 冲突。')
        if move:
            source.unlink(missing_ok=True)
    from .render import render_capture
    render_capture(config, identity)
    if background:
        start_enrichment(config, identity)
    return {'status': 'imported', 'id': identity}


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def scan_inbox(config, *, wait=1.0, limit=50):
    """Import stable images from every configured watch directory."""
    if wait:
        time.sleep(wait)
    imported, duplicates, skipped, errors = [], 0, 0, 0
    directories = [path for path in config.watch_dirs if path.is_dir()]
    with file_lock(config.root / 'run/inbox.lock', blocking=False):
        for directory in directories:
            candidates = sorted((path for path in directory.iterdir() if path.is_file()),
                                key=lambda path: (_mtime(path), path.name))
            for path in candidates:
                if len(imported) >= limit:
                    break
                try:
                    age = time.time() - path.stat().st_mtime
                    if (path.name.startswith('.') or path.suffix.lower() not in IMAGE_SUFFIXES
                            or path.stat().st_size == 0 or age < 0.3):
                        skipped += 1
                        continue
                    result = import_screenshot(config, path, move=True)
                except (OSError, ValueError):
                    errors += 1
                    continue
                if result['status'] == 'imported':
                    imported.append(result['id'])
                else:
                    duplicates += 1
    with run_logger(config) as logger:
        logger.info('inbox dirs=%d imported=%d duplicates=%d skipped=%d errors=%d',
                    len(directories), len(imported), duplicates, skipped, errors)
    return {'imported': imported, 'duplicates': duplicates, 'skipped': skipped,
            'errors': errors, 'directories': len(directories)}


def run_inbox(config, *, wait=1.0, limit=50):
    try:
        return scan_inbox(config, wait=wait, limit=limit)
    except AlreadyRunning:
        return {'imported': [], 'duplicates': 0, 'skipped': 0, 'errors': 0,
                'directories': 0, 'status': 'busy'}
