import json
import stat

import pytest

from noesis.cli import main
from noesis.config import ConfigError, initialize
from noesis.todo import change_todo, read_todos
from noesis import todo_server
from noesis.todo_server import Board


@pytest.fixture
def config(tmp_path):
    return initialize(tmp_path / 'data')


def test_create_update_done_clock_and_private_storage(config, tmp_path):
    folder = tmp_path / 'project'
    folder.mkdir()
    item = change_todo(config, 'create', title='  写周报 ', tag='urgent_important', folders=[str(folder), str(folder)])
    assert item['title'] == '写周报' and item['folders'] == [str(folder)] and item['status'] == 'todo'
    assert stat.S_IMODE((config.root / 'todos.json').stat().st_mode) == 0o600
    done = change_todo(config, 'update', identity=item['id'], status='done')
    assert done['done_at']
    # Editing other fields keeps the completion time; reopening clears it.
    assert change_todo(config, 'update', identity=item['id'], note='补充')['done_at'] == done['done_at']
    assert change_todo(config, 'update', identity=item['id'], status='doing')['done_at'] is None


@pytest.mark.parametrize('fields', [{'tag': 'later'}, {'status': 'archived'}, {'title': 'x' * 201},
                                    {'folders': ['relative/path']}, {'folders': ['/definitely/missing/noesis']},
                                    {'title': 'a\x00b'}, {'owner': 'me'}])
def test_rejects_invalid_fields(config, fields):
    with pytest.raises(ConfigError):
        change_todo(config, 'create', **fields)
    assert read_todos(config) == []


def test_delete_cascades_to_subtasks(config):
    root = change_todo(config, 'create', title='分享会')['id']
    child = change_todo(config, 'create', title='大纲', parent=root)['id']
    change_todo(config, 'create', title='细节', parent=child)
    keep = change_todo(config, 'create', title='其他')['id']
    with pytest.raises(ConfigError):
        change_todo(config, 'create', title='孤儿', parent='missing')
    assert len(change_todo(config, 'delete', ids=[root])['deleted']) == 3
    assert [item['id'] for item in read_todos(config)] == [keep]


def test_titles_are_redacted(config):
    item = change_todo(config, 'create', title='key sk-' + 'a' * 30)
    assert 'aaaa' not in item['title']


def request(board, method, path, body=None, token=True, host=None):
    headers = {'Host': host or f'127.0.0.1:{board.port}'}
    if token:
        headers['X-Noesis-Token'] = board.token
    status, _, payload = board.dispatch(method, path, headers, json.dumps(body).encode() if body is not None else b'')
    return status, payload


def test_board_requires_token_and_loopback_host(config):
    board = Board(config, 8765)
    assert request(board, 'GET', '/')[0] == 403
    status, page = request(board, 'GET', f'/?token={board.token}')
    assert status == 200 and board.token.encode() in page and b'__TOKEN__' not in page
    assert request(board, 'GET', '/api/todos', token=False)[0] == 403
    assert request(board, 'GET', '/api/todos', host='evil.test:8765')[0] == 403
    assert request(board, 'GET', '/api/todos')[0] == 200


def test_board_crud_and_folder_actions(config, tmp_path, monkeypatch):
    folder = tmp_path / 'linked'
    folder.mkdir()
    board = Board(config, 8765)
    status, payload = request(board, 'POST', '/api/todos', {'title': '部署'})
    identity = json.loads(payload)['id']
    status, payload = request(board, 'PATCH', f'/api/todos/{identity}', {'folders': [str(folder)]})
    assert status == 200
    snapshot = json.loads(request(board, 'GET', '/api/todos')[1])
    assert snapshot['todos'][0]['folders'] == [str(folder)]
    assert snapshot['folders'][str(folder)]['project'] == 'linked'
    opened = []
    monkeypatch.setattr(todo_server.subprocess, 'run', lambda args, **kwargs: opened.append(args))
    assert request(board, 'POST', '/api/open-folder', {'id': identity, 'index': 0})[0] == 200
    assert opened == [['open', str(folder)]]
    # Only folders already linked to a task can be opened.
    assert request(board, 'POST', '/api/open-folder', {'id': identity, 'index': 1})[0] == 400
    status, payload = request(board, 'PATCH', f'/api/todos/{identity}', {'tag': 'nope'})
    assert status == 400 and '任务标签' in json.loads(payload)['error']
    assert request(board, 'POST', '/api/todos', ['not', 'object'])[0] == 400
    assert request(board, 'POST', '/api/delete', {'ids': [identity]})[0] == 200
    assert read_todos(config) == []


def test_cli_add_and_list(config, tmp_path, capsys):
    folder = tmp_path / 'repo'
    folder.mkdir()
    assert main(['--data-dir', str(config.root), 'todo', 'add', '整理文稿', '--tag', 'important',
                 '--folder', str(folder)]) == 0
    capsys.readouterr()
    assert main(['--data-dir', str(config.root), 'todo', 'list']) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]['title'] == '整理文稿' and listed[0]['folders'] == [str(folder.resolve())]


def test_server_exits_when_app_closes_stdin(config, monkeypatch, capsys):
    import io
    monkeypatch.setattr(todo_server.sys, 'stdin', io.StringIO(''))
    assert todo_server.serve(config, open_browser=False, exit_on_stdin_eof=True) == 0
    assert 'http://127.0.0.1:' in capsys.readouterr().out


def test_daily_list_and_render_are_escaped_and_confined(config):
    daily = config.root / 'daily'
    daily.mkdir(exist_ok=True)
    (daily / '2026-11-08.md').write_text('---\ndate: 2026-11-08\n---\n# 日志\n\n- 09:10 [[captures/a.md|参考资料]]\n'
                                         '  备注：保留\n\n<script>alert(1)</script>\n\n[外链](https://example.invalid)\n')
    (daily / '2026-11-09.md').write_text('# 今天\n')
    (daily / 'notes.md').write_text('# 不是日报\n')
    board = Board(config, 8765)
    assert json.loads(request(board, 'GET', '/api/daily')[1]) == {'days': ['2026-11-09', '2026-11-08']}
    status, payload = request(board, 'GET', '/api/daily/2026-11-08')
    html = json.loads(payload)['html']
    assert status == 200 and 'date:' not in html and '📎 参考资料' in html and '[[' not in html
    assert '<br>' in html and '<script>' not in html and 'href="https://example.invalid"' in html
    for bad in ('notes', '..%2Fconfig', '2026-11-07'):
        assert request(board, 'GET', f'/api/daily/{bad}')[0] == 400
