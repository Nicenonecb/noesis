"""Loopback-only todo board. Requests need the per-launch token, so other sites cannot drive it."""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from .config import ConfigError
from .files import atomic_write
from .runtime import file_lock
from .projects import resolve_project
from .todo import STATUSES, TAGS, change_todo, read_todos
from .render.markdown import PLUGINS, BriefingRenderer
from ._vendor.mistune import create_markdown
from ._vendor.mistune.plugins.table import table_in_list
from .todo_page import PAGE

MAX_BODY = 64 * 1024
DEFAULT_PREFS = {'lang': 'zh', 'view': 'todo', 'folded': ['done'], 'expanded': []}
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
FRONT_MATTER = re.compile(r'\A---\n.*?\n---\n', re.S)


class DailyRenderer(BriefingRenderer):
    def softbreak(self):
        return '<br>\n'  # Match Obsidian: note/excerpt lines under a list item stay on their own lines.


_render = create_markdown(renderer=DailyRenderer(escape=True), plugins=[*PLUGINS, table_in_list])
FLAT = re.compile(r'^(?P<lead>[ \t]*(?:- )?)(?P<tag>👤 \d{2}:\d{2} |🤖 |备注：|摘录：)(?P<body>.*⏎.*)$', re.M)
BLOCK = re.compile(r'(#{1,6} |\||[-*+] |>|\d+\. |```)')


def _unflatten(match):
    # daily.py folds each message onto one line (⏎ for newlines, ʼʼʼ for fences) so
    # Obsidian keeps the list intact; the viewer restores it as Markdown nested in the item.
    pad = ' ' * len(match['lead'].expandtabs())
    lines = match['body'].replace('ʼʼʼ', '```').replace(' ⏎ ', '\n').replace('⏎', '\n').split('\n')
    head = match['lead'] + match['tag'].rstrip()
    if lines and not BLOCK.match(lines[0]):
        head += ' ' + lines.pop(0)
    return head + ('\n' + '\n'.join(pad + line if line else pad for line in lines) if lines else '')


def render_daily(text):
    # What remains are session-title headings, which must stay on one line.
    return _render(FLAT.sub(_unflatten, text).replace(' ⏎ ', ' '))
WIKILINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]*))?\]\]')


class Board:
    def __init__(self, config, port):
        self.config = config
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self._projects = {}

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/?token={self.token}'

    def _folder_info(self, paths):
        """Map linked folders to NOESIS projects and their latest recorded activity (read-only)."""
        if not paths or not self.config.db_path.exists():
            return {path: {'project': None, 'last_activity': None, 'exists': Path(path).is_dir()} for path in paths}
        connection = sqlite3.connect(self.config.db_path.as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            missing = [path for path in paths if path not in self._projects]
            if missing:  # Project resolution may call git, so it is cached per server run.
                repos = [dict(row) for row in connection.execute('SELECT * FROM repos WHERE enabled=1')]
                self._projects |= {path: resolve_project(path, repos) for path in missing}
            return {path: {'project': self._projects[path], 'last_activity': connection.execute(
                'SELECT max(ts) FROM events WHERE project=?', (self._projects[path],)).fetchone()[0],
                'exists': Path(path).is_dir()}
                for path in paths}
        finally:
            connection.close()

    def snapshot(self):
        todos = read_todos(self.config)
        paths = sorted({path for item in todos for path in item['folders']})
        return {'todos': todos, 'folders': self._folder_info(paths), 'tags': TAGS, 'statuses': STATUSES,
                'now': datetime.now(self.config.timezone).isoformat(timespec='seconds')}

    def daily_days(self):
        return sorted((path.stem for path in (self.config.root / 'daily').glob('*.md') if DAY.fullmatch(path.stem)),
                      reverse=True)

    def daily(self, day):
        # The fixed pattern keeps lookups inside daily/; logs hold collected text, so render escaped.
        path = self.config.root / 'daily' / f'{day}.md'
        if not DAY.fullmatch(day) or not path.is_file():
            raise ConfigError('没有这一天的日报。')
        text = FRONT_MATTER.sub('', path.read_text())
        # Obsidian links point at vault files the page cannot open; keep their labels.
        text = WIKILINK.sub(lambda match: '📎 ' + (match.group(2) or Path(match.group(1)).stem), text)
        return {'date': day, 'html': render_daily(text)}

    def prefs(self):
        path = self.config.root / 'ui.json'
        stored = json.loads(path.read_text()) if path.exists() else {}
        return DEFAULT_PREFS | {key: value for key, value in stored.items() if key in DEFAULT_PREFS}

    def save_prefs(self, changes):
        """Interface choices live in the data dir: the app's loopback origin changes port every launch."""
        checks = {'lang': lambda v: v in ('zh', 'en'), 'view': lambda v: v in ('todo', 'daily', 'settings'),
                  'folded': lambda v: isinstance(v, list) and set(v) <= set(STATUSES),
                  'expanded': lambda v: isinstance(v, list) and len(v) <= 500
                  and all(isinstance(i, str) and len(i) <= 32 for i in v)}
        for key, value in changes.items():
            if key not in checks or not checks[key](value):
                raise ConfigError(f'界面设置 {key} 无效。')
        with file_lock(self.config.root / 'run/ui.lock'):
            merged = self.prefs() | changes
            atomic_write(self.config.root / 'ui.json', json.dumps(merged, ensure_ascii=False, indent=2) + '\n')
        return merged

    def _folder(self, body):
        item = next((item for item in read_todos(self.config) if item['id'] == body.get('id')), None)
        index = body.get('index')
        if item is None or not isinstance(index, int) or not 0 <= index < len(item['folders']):
            raise ConfigError('未找到该关联文件夹。')
        return item['folders'][index]

    def dispatch(self, method, target, headers, body=b''):
        """Return (status, content type, bytes). Kept free of sockets so tests stay offline."""
        if headers.get('Host') != f'127.0.0.1:{self.port}':
            return 403, 'text/plain', b'forbidden'  # Blocks DNS rebinding to the loopback port.
        parsed = urlsplit(target)
        if method == 'GET' and parsed.path == '/':
            if parse_qs(parsed.query).get('token') != [self.token]:
                return 403, 'text/plain', b'forbidden'
            page = PAGE.replace('__TOKEN__', self.token)
            return 200, 'text/html; charset=utf-8', page.encode()
        if not parsed.path.startswith('/api/') or not secrets.compare_digest(headers.get('X-Noesis-Token', ''), self.token):
            return 403, 'text/plain', b'forbidden'
        try:
            data = json.loads(body or b'{}')
            if not isinstance(data, dict):
                raise ConfigError('请求格式无效。')
            route = (method, parsed.path)
            if route == ('GET', '/api/todos'):
                result = self.snapshot()
            elif route == ('GET', '/api/prefs'):
                result = self.prefs()
            elif route == ('PUT', '/api/prefs'):
                result = self.save_prefs(data)
            elif route == ('GET', '/api/daily'):
                result = {'days': self.daily_days()}
            elif method == 'GET' and parsed.path.startswith('/api/daily/'):
                result = self.daily(parsed.path.rsplit('/', 1)[1])
            elif route == ('POST', '/api/todos'):
                result = change_todo(self.config, 'create', **data)
            elif method == 'PATCH' and parsed.path.startswith('/api/todos/'):
                result = change_todo(self.config, 'update', identity=parsed.path.rsplit('/', 1)[1], **data)
            elif route == ('POST', '/api/delete'):
                result = change_todo(self.config, 'delete', ids=[str(item) for item in data.get('ids', [])])
            elif route == ('POST', '/api/pick-folder'):
                result = pick_folder()
            elif route == ('POST', '/api/open-folder'):
                subprocess.run(['open', self._folder(data)], check=True, timeout=10)
                result = {'status': 'opened'}
            else:
                return 404, 'application/json', b'{"error":"not_found"}'
        except (ConfigError, ValueError, TypeError) as exc:
            # ConfigError carries user-facing Chinese text; other parse errors stay generic.
            message = str(exc) if isinstance(exc, ConfigError) else '请求格式无效。'
            return 400, 'application/json', json.dumps({'error': message}, ensure_ascii=False).encode()
        except (OSError, subprocess.SubprocessError):
            return 500, 'application/json', json.dumps({'error': '本机操作失败。'}, ensure_ascii=False).encode()
        return 200, 'application/json', json.dumps(result, ensure_ascii=False).encode()


def pick_folder():
    """Native macOS folder chooser; the browser alone cannot report absolute paths."""
    script = ('tell application (path to frontmost application as text) to '
              'POSIX path of (choose folder with prompt "选择要关联的文件夹")')
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        return {'status': 'cancelled'}
    return {'status': 'picked', 'path': result.stdout.strip().rstrip('/') or '/'}


def serve(config, *, port=0, open_browser=True, exit_on_stdin_eof=False):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self):
            length = int(self.headers.get('Content-Length') or 0)
            if length > MAX_BODY:
                status, kind, payload = 413, 'text/plain', b'too large'
            else:
                status, kind, payload = board.dispatch(self.command, self.path, self.headers, self.rfile.read(length))
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_PUT = _respond

        def log_message(self, *args):
            pass  # Request lines carry the token; keep them out of terminals and logs.

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    board = Board(config, server.server_address[1])
    print(f'NOESIS 待办已启动：{board.url}\n按 Ctrl+C 停止。', flush=True)
    if open_browser:
        subprocess.run(['open', board.url], check=False)
    if exit_on_stdin_eof:
        # The desktop app holds stdin open; when it quits or crashes the server follows.
        threading.Thread(target=lambda: (sys.stdin.read(), server.shutdown()), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
