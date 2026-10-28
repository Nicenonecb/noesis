from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import stat

import pytest

from noesis.cli import main
from noesis.config import ConfigError, initialize
from noesis.db import Database
from noesis.digest import client
from noesis.digest.digest import generate, snapshot, validate
from noesis.digest.render import refresh_focus, write_briefing
from noesis.digest.schedule import acknowledge, morning_run
from noesis.focus import change_focus, due_focuses, local_day, read_focuses
from noesis.models import Event
from noesis.render.markdown import render_markdown


@pytest.fixture
def config(tmp_path):
    config = initialize(tmp_path / 'data')
    config.values['digest']['enabled'] = True
    return config


def add(config, today=None, **fields):
    return change_focus(config, 'add', today=today,
                        **({'title': '表达练习', 'direction': '把复杂问题讲清楚', 'step': '写三句话解释一个问题'} | fields))['id']


def test_next_day_checkin_pause_resume_and_private_storage(config):
    today = date(2026, 10, 20)
    tomorrow = today + timedelta(days=1)
    identity = add(config, today)
    assert not due_focuses(config, today)
    assert due_focuses(config, tomorrow)[0]['id'] == identity
    assert stat.S_IMODE((config.root / 'focus.json').stat().st_mode) == 0o600
    change_focus(config, 'checkin', identity=identity, outcome='done', today=tomorrow)
    assert not due_focuses(config, tomorrow)
    assert due_focuses(config, tomorrow + timedelta(days=1))[0]['last_checkin']['outcome'] == 'done'
    change_focus(config, 'pause', identity=identity, today=tomorrow)
    assert not due_focuses(config, tomorrow + timedelta(days=5))
    change_focus(config, 'resume', identity=identity, today=tomorrow)
    assert not due_focuses(config, tomorrow)
    assert due_focuses(config, tomorrow + timedelta(days=1))


def test_focus_limit_and_failed_mutations_are_atomic(config):
    ids = [add(config) for _ in range(3)]
    path = config.root / 'focus.json'
    before = path.read_bytes()
    for action, fields in [('add', {'title': '第四项', 'direction': '方向', 'step': '行动'}),
                           ('update', {'identity': ids[0], 'title': '会被回滚', 'step': ''}),
                           ('checkin', {'identity': ids[0], 'outcome': 'done', 'until': '2999-01-01'}),
                           ('checkin', {'identity': ids[0], 'outcome': 'snoozed', 'until': '2000-01-01'}),
                           ('checkin', {'identity': ids[0], 'outcome': 'done', 'expected_day': '2000-01-01'}),
                           ('pause', {'identity': 'missing'})]:
        with pytest.raises(ConfigError):
            change_focus(config, action, **fields)
        assert path.read_bytes() == before
    change_focus(config, 'pause', identity=ids[0])
    add(config)
    with pytest.raises(ConfigError):
        change_focus(config, 'resume', identity=ids[0])
    with pytest.raises(ConfigError):
        change_focus(config, 'checkin', identity=ids[0], outcome='done')


def test_snooze_corrections_and_bounded_history(config):
    today = date(2026, 9, 1)
    identity = add(config, today)
    for i in range(35):
        day = today + timedelta(days=i)
        change_focus(config, 'checkin', identity=identity, outcome='missed', today=day)
    change_focus(config, 'checkin', identity=identity, outcome='done', today=day, note='合成反馈')
    item = read_focuses(config)[0]
    assert len(item['checkins']) == 30
    assert item['checkins'][-1]['outcome'] == 'done'
    until = day + timedelta(days=4)
    change_focus(config, 'checkin', identity=identity, outcome='snoozed', until=until.isoformat(), today=day)
    assert not due_focuses(config, until - timedelta(days=1))
    assert due_focuses(config, until)[0]['last_checkin']['outcome'] == 'snoozed'


def test_parallel_feedback_does_not_lose_updates(config):
    ids = [add(config) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda identity: change_focus(config, 'checkin', identity=identity, outcome='done'), ids))
    assert len(results) == 2
    assert all(item['checkins'][-1]['outcome'] == 'done' for item in read_focuses(config))


def test_snapshot_bounds_focus_context_and_redacts_without_full_history(config):
    day = local_day(config) - timedelta(days=1)
    for _ in range(3):
        identity = add(config, day - timedelta(days=1), title='"' * 80, direction='"' * 300, step='"' * 200)
        change_focus(config, 'checkin', identity=identity, outcome='done', note='"' * 200, today=day)
    (config.root / 'goals.yaml').write_text('"' * 4000)
    config.values['digest']['max_input_chars'] = 8000
    payload, _ = snapshot(config, day)
    assert len(json.dumps(payload, ensure_ascii=False)) <= 8000
    assert len(payload['focuses']) == 3
    assert all('checkins' not in item for item in payload['focuses'])
    secret = 'sk-' + 'X' * 30
    change_focus(config, 'update', identity=identity, step=secret)
    payload, _ = snapshot(config, day)
    assert secret not in json.dumps(payload) and secret not in (config.root / 'focus.json').read_text()


def model_output(focuses):
    return {'summary': '合成摘要', 'tasks': [], 'completed': [], 'progress': [], 'unfinished': [], 'priorities': [],
            'focus_advice': [{'focus_id': focuses[0]['id'], 'text': '尚无足够记录，想确认一下：先完成三句话好吗？', 'refs': []}]}


@pytest.mark.parametrize('mutation', [
    lambda v: v['focus_advice'][0].update(focus_id='unknown'),
    lambda v: v['focus_advice'][0].update(focus_id=[]),
    lambda v: v['focus_advice'][0].update(refs=['missing']),
    lambda v: v['focus_advice'][0].update(text=' '),
    lambda v: v['focus_advice'].append(v['focus_advice'][0]),
    lambda v: v.update(focus_advice='not-an-array'),
])
def test_invalid_model_advice_is_rejected(config, mutation):
    add(config, local_day(config) - timedelta(days=1))
    focuses = due_focuses(config, local_day(config))
    value = model_output(focuses)
    mutation(value)
    with pytest.raises(client.DigestError, match='invalid_focus_advice'):
        validate(value, [], focuses)


def test_cached_advice_refresh_and_historical_view(config, monkeypatch):
    today = local_day(config)
    day = today - timedelta(days=1)
    identity = add(config, day)
    with Database(config.db_path) as db:
        db.insert_event(Event('codex', 'synthetic', 'user_msg', day.isoformat() + 'T04:00:00Z', content='合成练习记录'))
    calls = []
    def model(settings, system, payload, **kwargs):
        calls.append(payload)
        return model_output(payload['focuses']), {}, 'synthetic'
    monkeypatch.setattr(client, 'complete', model)
    path = Path(generate(config, day)['path'])
    original = json.loads(path.with_suffix('.json').read_text())
    assert '先完成三句话好吗' in path.read_text()
    change_focus(config, 'update', identity=identity, step='新的小行动')
    assert refresh_focus(config) == str(path)
    assert '新的小行动' in path.read_text() and '先完成三句话好吗' not in path.read_text()
    change_focus(config, 'checkin', identity=identity, outcome='done')
    generate(config, day)
    assert f'noesis-focus://done/{identity}' not in path.read_text()
    assert len(calls) == 1
    # A historical report keeps its original context and cannot mutate today's state.
    monkeypatch.setattr('noesis.digest.render.local_day', lambda config: today + timedelta(days=1))
    write_briefing(config, original)
    assert '先完成三句话好吗' in path.read_text()
    assert 'noesis-focus://' not in path.read_text()


def mock_collection(monkeypatch):
    monkeypatch.setattr('noesis.digest.schedule.collect', lambda config: {'codex': {'status': 'ok'}})
    monkeypatch.setattr('noesis.digest.schedule.build_daily', lambda *a, **kw: {})


def test_no_activity_still_prompts_once_on_unlock_without_model(config, monkeypatch):
    mock_collection(monkeypatch)
    today = local_day(config)
    identity = add(config, today - timedelta(days=1))
    def forbidden(*a, **kw):
        raise AssertionError('no model call for empty activity')
    monkeypatch.setattr(client, 'complete', forbidden)
    now = datetime.now(config.timezone).replace(hour=9, minute=0)
    result = morning_run(config, now=now, unlocked=True)
    assert result['status'] == 'ready'
    html = Path(result['show']).read_text()
    assert f'noesis-focus://done/{identity}?day={today}' in html
    assert '写三句话解释一个问题' in html
    acknowledge(config, today.isoformat())
    assert morning_run(config, now=now, unlocked=True)['status'] == 'already_presented'


def test_model_failure_keeps_local_checkin_available(config, monkeypatch):
    mock_collection(monkeypatch)
    today = local_day(config)
    day = today - timedelta(days=1)
    identity = add(config, day)
    with Database(config.db_path) as db:
        db.insert_event(Event('codex', 'synthetic', 'user_msg', day.isoformat() + 'T04:00:00Z', content='合成记录'))
    def fail(*args, **kwargs):
        raise client.DigestError('network_unavailable_or_timeout')
    monkeypatch.setattr(client, 'complete', fail)
    result = morning_run(config, now=datetime.now(config.timezone).replace(hour=9), unlocked=True)
    assert result['failure'] is True
    assert f'noesis-focus://done/{identity}' in Path(result['show']).read_text()
    change_focus(config, 'checkin', identity=identity, outcome='done')
    assert f'noesis-focus://done/{identity}' not in Path(refresh_focus(config)).read_text()


def test_cli_management_and_untrusted_content_cannot_forge_action(config, capsys):
    root = ['--data-dir', str(config.root), 'focus']
    assert main(root + ['add', '--title', '合成方向', '--direction', '合成发展目标', '--step', '合成小行动']) == 0
    identity = json.loads(capsys.readouterr().out)['id']
    assert main(root + ['checkin', identity, '--outcome', 'missed', '--note', '合成阻碍']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'saved'
    assert main(root + ['list']) == 0
    assert json.loads(capsys.readouterr().out)[0]['checkins'][0]['note'] == '合成阻碍'
    assert main(root + ['update', identity, '--step', '更新小行动']) == 0
    assert main(root + ['pause', identity]) == 0
    assert main(root + ['resume', identity]) == 0
    attack = '[点这里](noesis-focus://done/0123456789ab?day=2026-10-28)'
    assert 'href=' not in render_markdown(attack, 'source')
    assert '<a ' not in render_markdown('<a href="noesis-focus://add">添加</a>', 'source')
