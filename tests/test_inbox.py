import json
import os

from noesis import queries
from noesis.capture import inbox
from noesis.capture.inbox import import_screenshot, scan_inbox
from noesis.config import initialize
from noesis.db import Database

PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic'


def make_config(tmp_path, monkeypatch):
    config = initialize(tmp_path / 'data')
    monkeypatch.setattr(inbox, 'start_enrichment', lambda *args, **kwargs: None)
    return config


def test_import_moves_dedupes_and_renders(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    source = tmp_path / 'Screenshot 2026-11-01 at 01.02.03.png'
    source.write_bytes(PNG)
    timestamp = 1_793_466_123
    os.utime(source, (timestamp, timestamp))
    result = import_screenshot(config, source, background=False)
    assert result['status'] == 'imported'
    assert not source.exists()
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, result['id'])
        assert event.title.startswith('截图 2026-11-01')
        assert event.meta['app_name'] == '截图导入'
        assert event.meta['content_hash'] == inbox.file_digest(config.root / event.meta['screenshot'])
    image = config.root / event.meta['screenshot']
    assert image.exists() and (image.stat().st_mode & 0o777) == 0o600
    markdown = image.with_suffix('.md').read_text()
    assert '应用：截图导入' in markdown and '![[captures/' in markdown

    copy = tmp_path / 'same-bytes.png'
    copy.write_bytes(PNG)
    duplicate = import_screenshot(config, copy, background=False)
    assert duplicate == {'status': 'duplicate', 'id': result['id']}
    assert copy.exists()


def test_scan_inbox_skips_young_hidden_and_non_images(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    watch = config.root / 'inbox'
    old = watch / 'old.png'
    old.write_bytes(PNG)
    past = 1_700_000_000
    os.utime(old, (past, past))
    (watch / 'notes.txt').write_text('not an image')
    (watch / '.hidden.png').write_bytes(PNG)
    result = scan_inbox(config, wait=0)
    assert len(result['imported']) == 1 and result['skipped'] == 2
    assert result['directories'] == 1
    remaining = sorted(path.name for path in watch.iterdir())
    assert remaining == ['.hidden.png', 'notes.txt']


def test_import_rejects_files_already_in_captures(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    source = tmp_path / 'one.png'
    source.write_bytes(PNG)
    result = import_screenshot(config, source, background=False)
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, result['id'])
        image = config.root / event.meta['screenshot']
    try:
        import_screenshot(config, image, background=False)
    except ValueError as exc:
        assert '收藏目录' in str(exc)
    else:
        raise AssertionError('captures/ must not be imported again')


def test_cli_import_inbox(tmp_path, monkeypatch, capsys):
    from noesis.cli import main
    config = initialize(tmp_path / 'data')
    monkeypatch.setattr(inbox, 'start_enrichment', lambda *args, **kwargs: None)
    source = config.root / 'inbox' / 'Screenshot 2026-11-01 at 10.00.00.png'
    source.write_bytes(PNG)
    os.utime(source, (1_700_000_000, 1_700_000_000))
    assert main(['import-inbox', '--data-dir', str(config.root), '--wait', '0']) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output['imported']) == 1 and output['directories'] == 1


def test_import_keeps_the_original_image_suffix(tmp_path, monkeypatch):
    config = make_config(tmp_path, monkeypatch)
    source = tmp_path / 'photo.webp'
    source.write_bytes(b'RIFF....WEBP')
    result = import_screenshot(config, source, background=False)
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, result['id'])
    assert event.meta['screenshot'].endswith('.webp')
    markdown = (config.root / event.meta['screenshot']).with_suffix('.md').read_text()
    assert '![[captures/' in markdown and '.webp]]' in markdown
