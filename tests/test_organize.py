from dataclasses import replace
import json

from noesis import queries
from noesis.capture.inbox import import_screenshot
from noesis.config import initialize
from noesis.db import Database
from noesis.digest import client
from noesis.organize import organize_capture

PNG = b'\x89PNG\r\n\x1a\nsynthetic'
SECRET = 'sk-' + 'X' * 24


def setup_capture(tmp_path, monkeypatch, content):
    config = initialize(tmp_path / 'data')
    monkeypatch.setattr('noesis.capture.inbox.start_enrichment', lambda *args, **kwargs: None)
    source = tmp_path / 'Screenshot 2026-11-01 at 09.30.00.png'
    source.write_bytes(PNG)
    result = import_screenshot(config, source, background=False)
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, result['id'])
        db.replace_event(replace(event, title='旧标题', content=content))
    config.values['organize']['enabled'] = True
    return config, result['id']


def fake_completion(seen):
    def complete(settings, system, payload, *, env_file=None):
        seen.append((settings, payload))
        return ({'title': '实体卡保号方案对比', 'summary': '整理了五种海外手机卡的月租和保号成本。',
                 'tags': ['#手机卡', 'eSIM', '保号', '手机卡'], 'category': '工具', 'project': 'NOESIS'},
                {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30},
                'deepseek-flash')
    return complete


def test_organize_applies_title_summary_tags_and_redacts(tmp_path, monkeypatch):
    config, identity = setup_capture(tmp_path, monkeypatch, '选择手机卡。token=' + SECRET)
    seen = []
    monkeypatch.setattr('noesis.organize.client.complete', fake_completion(seen))
    result = organize_capture(config, identity)
    assert result['status'] == 'done' and result['project'] == 'NOESIS'
    assert result['tags'] == ['手机卡', 'eSIM', '保号']
    assert SECRET not in json.dumps(seen[0][1], ensure_ascii=False)
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, identity)
        assert event.title == '实体卡保号方案对比'
        assert event.meta['tags'] == ['手机卡', 'eSIM', '保号']
        assert event.meta['category'] == '工具'
        assert event.meta['ai']['summary'].startswith('整理了五种')
        assert event.meta['ai']['usage']['total'] == 30
    markdown = (config.root / event.meta['screenshot']).with_suffix('.md').read_text()
    for value in ('标签：#手机卡 #eSIM #保号', '分类：工具', '## AI 摘要'):
        assert value in markdown


def test_organize_is_cached_and_failure_keeps_capture(tmp_path, monkeypatch):
    config, identity = setup_capture(tmp_path, monkeypatch, '正文')
    calls = []
    monkeypatch.setattr('noesis.organize.client.complete', fake_completion(calls))
    assert organize_capture(config, identity)['status'] == 'done'
    assert organize_capture(config, identity)['status'] == 'cached'
    assert len(calls) == 1

    def fail(*args, **kwargs):
        raise client.DigestError('http_500')
    monkeypatch.setattr('noesis.organize.client.complete', fail)
    failed = organize_capture(config, identity, force=True)
    assert failed == {'id': identity, 'status': 'failed', 'error': 'http_500'}
    with Database(config.db_path) as db:
        event = queries.capture_by_id(db.connection, identity)
        assert event.meta['ai_status'] == 'failed' and event.meta['ai_error'] == 'http_500'
        assert event.title == '实体卡保号方案对比'
        assert (config.root / event.meta['screenshot']).exists()


def test_organize_rejects_invalid_schema_and_is_opt_in(tmp_path, monkeypatch):
    config, identity = setup_capture(tmp_path, monkeypatch, '正文')
    monkeypatch.setattr('noesis.organize.client.complete', lambda *args, **kwargs: (
        {'title': 'x', 'summary': 'y', 'tags': [], 'category': '未知', 'project': ''}, {}, 'deepseek-flash'))
    assert organize_capture(config, identity)['status'] == 'failed'
    config.values['organize']['enabled'] = False
    assert organize_capture(config, identity) == {'id': identity, 'status': 'failed', 'error': 'organize_disabled'}


def test_cli_organize_uses_config_file(tmp_path, monkeypatch, capsys):
    from noesis.cli import main
    config, identity = setup_capture(tmp_path, monkeypatch, '正文')
    path = config.root / 'config.toml'
    path.write_text(path.read_text().replace('[organize]\nenabled = false', '[organize]\nenabled = true'))
    monkeypatch.setattr('noesis.organize.client.complete', fake_completion([]))
    assert main(['organize', identity, '--data-dir', str(config.root)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'done' and output['tags'][0] == '手机卡'
