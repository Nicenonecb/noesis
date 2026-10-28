from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from noesis.config import initialize, load_config, ConfigError
from noesis.db import Database
from noesis.models import Event
from noesis.digest import client
from noesis.digest.digest import generate, snapshot, validate
from noesis.digest.schedule import morning_run, acknowledge


@pytest.fixture
def config(tmp_path):
    config = initialize(tmp_path / 'data')
    config.values['digest']['enabled'] = True
    return config


def add_event(config, day, *, identity='one', content='已经修复解析器并通过测试。', project='demo'):
    with Database(config.db_path) as db:
        db.insert_event(Event('codex', identity, 'assistant_msg', day.isoformat() + 'T04:00:00Z',
                             content=content, project=project, raw_ref='/private/original.jsonl:1'))


def output(payload):
    refs = [payload['evidence'][0]['id']]
    return {'summary': '已推进解析器工作。', 'completed': [],
            'tasks': [{'id': 'T1', 'state': 'active', 'text': '解析器等待验收。', 'refs': refs}],
            'progress': [{'task_id': 'T1', 'text': '对话中报告解析器已修复，等待验收。', 'refs': refs}],
            'unfinished': [], 'priorities': []}


@pytest.mark.parametrize('state', ['completed', 'abandoned', 'deferred'])
@pytest.mark.parametrize('section', ['progress', 'unfinished', 'priorities'])
def test_resolved_tasks_cannot_reappear_as_open_work(config, monkeypatch, state, section):
    day = date(2026, 10, 22)
    add_event(config, day)
    def model(settings, system, payload, *, env_file=None):
        value = output(payload)
        value['tasks'][0]['state'] = state
        item = value['progress'].pop()
        value[section] = [item]
        return value, {}, 'deepseek-flash'
    monkeypatch.setattr(client, 'complete', model)
    with pytest.raises(client.DigestError, match='inconsistent_task_state'):
        generate(config, day)
    assert not list((config.root / 'briefings').glob('*'))


def test_reconciled_tasks_preserve_decision_and_completion_evidence():
    evidence = [{'id': f'E{i}'} for i in range(1, 5)]
    value = {'summary': '旧方案已放弃，导出已完成，下一步验证同步。',
             'tasks': [
                 {'id': 'T1', 'state': 'abandoned', 'text': '用户放弃旧方案。', 'refs': ['E1', 'E2']},
                 {'id': 'T2', 'state': 'completed', 'text': '导出已完成。', 'refs': ['E3']},
                 {'id': 'T3', 'state': 'active', 'text': '同步待验证。', 'refs': ['E4']}],
             'completed': [{'task_id': 'T2', 'text': '对话中报告导出完成。', 'refs': ['E3']}],
             'progress': [], 'unfinished': [],
             'priorities': [{'task_id': 'T3', 'text': '验证同步，待确认。', 'refs': ['E4']}]}
    result = validate(value, evidence)
    assert result['tasks'] == value['tasks']
    assert result['priorities'][0]['task_id'] == 'T3'
    value['priorities'][0]['refs'] = ['E1']
    with pytest.raises(client.DigestError, match='missing_task_state_evidence'):
        validate(value, evidence)


@pytest.mark.parametrize('mutation,error', [
    (lambda v: v.pop('tasks'), 'invalid_task_schema'),
    (lambda v: v['tasks'].append(dict(v['tasks'][0])), 'invalid_task_schema'),
    (lambda v: v['tasks'][0].update(state='invented'), 'invalid_task_schema'),
    (lambda v: v['tasks'][0].update(refs=['missing']), 'invalid_evidence_reference'),
    (lambda v: v['progress'][0].update(task_id='missing'), 'invalid_task_reference'),
    (lambda v: v['progress'][0].update(task_id=[]), 'invalid_task_reference'),
    (lambda v: v['tasks'][0].update(state='uncertain'), 'inconsistent_task_state'),
])
def test_invalid_task_reconciliation_is_rejected(mutation, error):
    evidence = [{'id': 'E1'}]
    value = output({'evidence': evidence})
    mutation(value)
    with pytest.raises(client.DigestError, match=error):
        validate(value, evidence)


def test_legacy_cache_renders_and_failed_regeneration_preserves_it(config, monkeypatch):
    day = date(2026, 10, 22)
    add_event(config, day)
    monkeypatch.setattr(client, 'complete', lambda settings, system, payload, **kw: (output(payload), {}, 'deepseek-flash'))
    path = Path(generate(config, day)['path'])
    target = path.with_suffix('.json')
    record = json.loads(target.read_text())
    record['prompt_version'] = 1
    record['result'].pop('tasks')
    record['result']['progress'][0].pop('task_id')
    target.write_text(json.dumps(record))
    def model(settings, system, payload, **kw):
        value = output(payload)
        value['tasks'][0]['state'] = 'abandoned'
        return value, {}, 'deepseek-flash'
    monkeypatch.setattr(client, 'complete', model)
    assert generate(config, day)['status'] == 'cached'
    originals = {p: p.read_bytes() for p in [target, path, path.with_suffix('.md')]}
    with pytest.raises(client.DigestError, match='inconsistent_task_state'):
        generate(config, day, force=True)
    assert all(p.read_bytes() == content for p, content in originals.items())


def mock_collection(monkeypatch):
    monkeypatch.setattr('noesis.digest.schedule.collect', lambda config: {'codex': {'status': 'ok'}})
    monkeypatch.setattr('noesis.digest.schedule.build_daily', lambda *a, **kw: {})


def test_snapshot_bounds_redaction_and_project_coverage(config):
    day = date(2026, 10, 22)
    for i in range(30):
        add_event(config, day, identity=str(i), content=('sk-' + 'X' * 24 + 'data ' * 600), project='busy')
    add_event(config, day, identity='small', project='small')
    config.values['digest']['max_input_chars'] = 8000
    payload, health = snapshot(config, day)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(serialized) <= 8000
    assert '/private/original' not in serialized and 'sk-' not in serialized
    assert {item['project'] for item in payload['evidence']} == {'busy', 'small'}
    assert payload['omitted_events'] > 0
    assert all(item['excerpt_truncated'] for item in payload['evidence'] if item['project'] == 'busy')


def test_generate_cache_repair_force_and_escaped_html(config, monkeypatch):
    day = datetime.now(config.timezone).date() - timedelta(days=1)
    add_event(config, day, content='<script>alert(1)</script> sk-' + 'X' * 24)
    calls = []
    def model(settings, system, payload, *, env_file=None):
        assert env_file == config.root / '.env'
        calls.append(payload)
        value = output(payload)
        value['summary'] = '<img src="https://example.invalid/private"> sk-' + 'Y' * 24
        return value, {'total_tokens': 42}, 'deepseek-flash'
    monkeypatch.setattr(client, 'complete', model)
    first = generate(config, day)
    path = Path(first['path'])
    html = path.read_text()
    assert '<script>' not in html and '<img ' not in html
    assert all('sk-' + letter * 24 not in html for letter in ('X', 'Y'))
    assert '&lt;script&gt;' in html and "default-src 'none'" in html
    before = path.stat().st_mtime_ns
    assert generate(config, day)['status'] == 'cached'
    assert path.stat().st_mtime_ns == before and len(calls) == 1
    path.write_text('<pre>old renderer</pre>')
    assert generate(config, day)['status'] == 'cached'
    assert path.read_text() == html and len(calls) == 1
    path.unlink()
    assert generate(config, day)['status'] == 'cached' and path.exists() and len(calls) == 1
    generate(config, day, force=True)
    assert len(calls) == 2


def test_invalid_references_never_save_success(config, monkeypatch):
    day = date(2026, 10, 22)
    add_event(config, day)
    def model(settings, system, payload, *, env_file=None):
        value = output(payload)
        value['progress'][0]['refs'] = ['invented']
        return value, {}, 'deepseek-flash'
    monkeypatch.setattr(client, 'complete', model)
    with pytest.raises(client.DigestError, match='invalid_evidence_reference'):
        generate(config, day)
    assert not list((config.root / 'briefings').glob('*'))


def test_no_data_does_not_spend_tokens_and_current_day_is_rejected(config, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('no model call allowed')
    monkeypatch.setattr(client, 'complete', forbidden)
    assert generate(config, date(2026, 10, 22))['mode'] == 'no_data'
    with pytest.raises(client.DigestError, match='source_day_not_complete'):
        generate(config, datetime.now(config.timezone).date())


def test_schedule_generates_at_0030_but_only_offers_on_unlock(config, monkeypatch):
    mock_collection(monkeypatch)
    today = datetime.now(config.timezone).date()
    before = datetime.combine(today, datetime.min.time(), config.timezone) + timedelta(minutes=29)
    due = before + timedelta(minutes=1)
    assert morning_run(config, now=before, unlocked=True)['status'] == 'not_due'
    assert morning_run(config, now=due)['status'] == 'ready_waiting_for_unlock'
    ready = morning_run(config, now=due + timedelta(hours=8), unlocked=True)
    assert ready['status'] == 'ready' and Path(ready['show']).exists()
    # Requesting a window is not proof it was shown. Only the viewer may acknowledge.
    assert morning_run(config, now=due, unlocked=True)['status'] == 'ready'
    acknowledge(config, today.isoformat())
    assert morning_run(config, now=due, unlocked=True)['status'] == 'already_presented'


def test_schedule_retries_bounded_and_failure_not_claimed_as_success(config, monkeypatch):
    mock_collection(monkeypatch)
    today = datetime.now(config.timezone).date()
    now = datetime.combine(today, datetime.min.time(), config.timezone) + timedelta(hours=9)
    add_event(config, today - timedelta(days=1))
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise client.DigestError('network_unavailable_or_timeout')
    monkeypatch.setattr(client, 'complete', fail)
    first = morning_run(config, now=now, unlocked=True)
    assert first['failure'] and first['status'] == 'failed'
    acknowledge(config, today.isoformat(), failure=True)
    assert 'show' not in morning_run(config, now=now + timedelta(minutes=5), unlocked=True)
    for minute in (30, 60, 90):
        morning_run(config, now=now + timedelta(minutes=minute), unlocked=True)
    assert len(calls) == 3
    assert not (config.root / 'briefings' / (today.isoformat() + '.json')).exists()
    # A real unlock can recover once after an overnight network outage or missing environment key.
    morning_run(config, now=now + timedelta(hours=3), unlocked=True, unlock_event=True)
    morning_run(config, now=now + timedelta(hours=4), unlocked=True, unlock_event=True)
    assert len(calls) == 4


def test_collection_lock_conflict_does_not_consume_model_retry(config, monkeypatch):
    from noesis.runtime import AlreadyRunning
    def busy(*a, **kw):
        raise AlreadyRunning()
    monkeypatch.setattr('noesis.digest.schedule.collect', busy)
    now = datetime.now(config.timezone).replace(hour=12)
    assert morning_run(config, now=now)['status'] == 'busy'
    assert not (config.root / 'run/morning-state.json').exists()


def test_environment_key_is_not_printed_or_read_from_keychain(monkeypatch, capsys, tmp_path):
    secret = 'sk-' + 'S' * 24
    def forbidden(*args, **kwargs):
        raise AssertionError('credential access must not start subprocesses')
    monkeypatch.setattr('subprocess.run', forbidden)
    monkeypatch.setenv('DEEPSEEK_API_KEY', secret)
    assert client.api_key() == secret
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    with pytest.raises(client.DigestError, match='api_key_missing'):
        client.api_key(tmp_path / '.env')
    assert not capsys.readouterr().out


def test_local_environment_rotation_permissions_and_process_override(config, monkeypatch):
    import stat
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    path = config.root / '.env'
    path.write_text('# local settings\nOTHER_SETTING=keep\nexport DEEPSEEK_API_KEY=old\nDEEPSEEK_API_KEY=duplicate\n')
    path.chmod(0o644)
    secret = 'sk-' + 'S' * 24
    client.save_api_key(path, secret)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().count('DEEPSEEK_API_KEY=') == 1
    assert 'OTHER_SETTING=keep' in path.read_text()
    assert client.api_key(path) == secret
    client.save_api_key(path, 'rotated-synthetic')
    assert client.api_key(path) == 'rotated-synthetic'
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'process-override')
    path.write_text('DEEPSEEK_API_KEY="unclosed')
    assert client.api_key(path) == 'process-override'


@pytest.mark.parametrize('line,expected', [
    ('export DEEPSEEK_API_KEY="synthetic" # comment', 'synthetic'),
    ("DEEPSEEK_API_KEY='literal$(not_executed)'", 'literal$(not_executed)'),
])
def test_local_environment_quotes_and_literal_values(config, monkeypatch, line, expected):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    path = config.root / '.env'
    path.write_text(line + '\n')
    assert client.api_key(path) == expected


@pytest.mark.parametrize('value', ['"unclosed', 'two words', '', '"has space"'])
def test_invalid_local_environment_has_fixed_error_without_secret(config, monkeypatch, value):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    path = config.root / '.env'
    path.write_text('DEEPSEEK_API_KEY=' + value)
    with pytest.raises(client.DigestError) as error:
        client.api_key(path)
    assert str(error.value) == 'api_key_invalid'


def test_cli_key_entry_and_model_check_use_selected_data_directory(config, monkeypatch, capsys):
    from noesis.cli import main
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    secret = 'sk-' + 'S' * 24
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('getpass.getpass', lambda prompt: secret)
    assert main(['digest-key', '--data-dir', str(config.root)]) == 0
    assert secret not in capsys.readouterr().out
    def check(env_file):
        assert env_file == config.root / '.env'
        assert client.api_key(env_file) == secret
        return {'model': 'deepseek-flash', 'available': True}
    monkeypatch.setattr(client, 'check_model', check)
    assert main(['digest-check', '--data-dir', str(config.root)]) == 0
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize('status,expected_calls', [(429, 2), (503, 2), (401, 1), (402, 1), (302, 1)])
def test_http_retry_policy_and_no_provider_body_leak(monkeypatch, status, expected_calls):
    monkeypatch.setattr(client, 'api_key', lambda env_file=None: 'synthetic')
    monkeypatch.setattr(client.time, 'sleep', lambda n: None)
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        raise HTTPError(req.full_url, status, 'sk-' + 'X' * 24, {}, io.BytesIO(b'private response'))
    monkeypatch.setattr(client, 'build_opener', lambda *a: SimpleNamespace(open=fail))
    with pytest.raises(client.DigestError) as exc:
        client.request('/chat/completions', body={'synthetic': True})
    assert str(exc.value) == f'http_{status}' and len(calls) == expected_calls
    assert client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None


def test_client_json_mode_and_truncation_rejection(monkeypatch, config):
    def respond(path, *, body, timeout, env_file=None):
        assert env_file == config.root / '.env'
        assert body['model'] == 'deepseek-flash'
        assert body['response_format'] == {'type': 'json_object'}
        assert 'tools' not in body and body['thinking']['type'] == 'disabled'
        return {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
    monkeypatch.setattr(client, 'request', respond)
    with pytest.raises(client.DigestError, match='incomplete_generation'):
        client.complete(config.values['digest'], 'json', {}, env_file=config.root / '.env')


def test_ai_install_schedule_and_uninstall_keep_key_and_reports(config, tmp_path, monkeypatch):
    from noesis.install import install, uninstall, MORNING_LABEL
    import plistlib
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    commands = []
    monkeypatch.setattr('noesis.install.subprocess.run', lambda args, **kw: commands.append(args) or SimpleNamespace(returncode=0, stdout=''))
    result = install(config, Path(__file__).resolve().parents[1], load=False)
    assert len(result['installed']) == 3 and MORNING_LABEL in result['installed']
    agent = home / 'Library/LaunchAgents/com.justin.noesis.daily.plist'
    value = plistlib.loads(agent.read_bytes())
    assert value['StartCalendarInterval'] == {'Hour': 0, 'Minute': 30}
    assert 'morning-run' in value['ProgramArguments'] and value['RunAtLoad']
    assert value['StartInterval'] == 300
    assert str(Path(__file__).resolve().parents[1]) not in json.dumps(value)
    assert all('security' not in cmd for cmd in commands)
    report = config.root / 'briefings/test.md'
    report.write_text('keep')
    uninstall(config, load=False)
    assert report.exists()
    assert not list((home / 'Library/LaunchAgents').glob('com.justin.noesis.*.plist'))


def test_installed_runtime_does_not_need_the_desktop_checkout(config, tmp_path):
    import subprocess
    from noesis.install import install_runtime
    install_runtime(config, Path(__file__).resolve().parents[1])
    result = subprocess.run([str(config.root / 'bin/noesis'), '--version'],
                            cwd=tmp_path, capture_output=True, text=True, check=True,
                            env={'PATH':'/usr/bin:/bin', 'PYTHONPATH':'/does/not/exist'})
    assert result.stdout.strip() == '0.1.0'
    # Exercise the packaged Markdown parser, not only the CLI --version path.
    day = date(2026, 10, 22)
    generated = generate(config, day)
    config_path = config.root / 'config.toml'
    config_path.write_text(config_path.read_text().replace('[digest]\nenabled = false', '[digest]\nenabled = true'))
    Path(generated['path']).unlink()
    (config.root / '.env').write_text('DEEPSEEK_API_KEY="broken')
    result = subprocess.run([str(config.root / 'bin/noesis'), 'digest', '--date', day.isoformat(), '--data-dir', str(config.root)],
                            cwd=tmp_path, capture_output=True, text=True, check=True,
                            env={'PATH':'/usr/bin:/bin', 'PYTHONPATH':'/does/not/exist'})
    assert json.loads(result.stdout)['status'] == 'cached'
    assert Path(generated['path']).exists()
    import zipfile
    with zipfile.ZipFile(config.root / 'bin/noesis.pyz') as archive:
        assert 'noesis/_vendor/mistune/LICENSE' in archive.namelist()


@pytest.mark.parametrize('field,value', [('generate_after','24:30'), ('generate_after','0:30'), ('model','unknown')])
def test_digest_config_rejects_invalid_schedule(config, field, value):
    path = config.root / 'config.toml'
    old = config.values['digest'][field]
    path.write_text(path.read_text().replace(f'{field} = "{old}"', f'{field} = "{value}"'))
    with pytest.raises(ConfigError):
        load_config(config.root)
