"""User-owned todo records with linked local folders; stored beside focus.json, never sent to a model."""

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from .config import ConfigError
from .files import atomic_write
from .focus import _text
from .redact import redact
from .runtime import file_lock

TAGS = {'urgent_important': '重要紧急', 'important': '重要不紧急',
        'urgent': '紧急不重要', 'neither': '不重要不紧急'}
STATUSES = {'todo': '未开始', 'doing': '进行中', 'done': '已完成'}
LIMITS = {'title': 200, 'category': 40, 'note': 2000}
MAX_FOLDERS = 10


def _path(config):
    return config.root / 'todos.json'


def read_todos(config):
    path = _path(config)
    return json.loads(path.read_text()) if path.exists() else []


def _now(config):
    return datetime.now(config.timezone).isoformat(timespec='seconds')


def _folders(value):
    if not isinstance(value, list) or len(value) > MAX_FOLDERS:
        raise ConfigError(f'每个任务最多关联 {MAX_FOLDERS} 个文件夹。')
    result = []
    for item in value:
        if not isinstance(item, str) or not Path(item).is_absolute():
            raise ConfigError('关联文件夹必须是绝对路径。')
        path = Path(item).resolve()
        if not path.is_dir():
            raise ConfigError('关联的文件夹不存在。')
        if str(path) not in result:
            result.append(str(path))
    return result


def _apply(item, fields):
    labels = {'title': '任务名称', 'category': '任务类别', 'note': '解决办法/备忘'}
    for key, value in fields.items():
        if key in LIMITS:
            item[key] = redact(_text(value, labels[key], LIMITS[key], optional=True))
        elif key == 'tag':
            if value is not None and value not in TAGS:
                raise ConfigError('任务标签不在可选范围内。')
            item['tag'] = value
        elif key == 'status':
            if value not in STATUSES:
                raise ConfigError('状态必须是 todo、doing 或 done。')
            item['status'] = value
        elif key == 'folders':
            item['folders'] = _folders(value)
        else:
            raise ConfigError(f'不支持修改字段 {key}。')


def change_todo(config, action, *, identity=None, ids=(), parent=None, **fields):
    """Create, update or delete under one lock; deleting a record removes its subtasks."""
    with file_lock(config.root / 'run/todo.lock'):
        todos = read_todos(config)
        now = _now(config)
        if action == 'create':
            if parent is not None and not any(item['id'] == parent for item in todos):
                raise ConfigError('未找到父记录。')
            item = {'id': uuid4().hex[:12], 'title': '', 'tag': None, 'status': 'todo', 'category': '',
                    'note': '', 'folders': [], 'parent': parent, 'created_at': now, 'updated_at': now,
                    'done_at': None}
            _apply(item, fields)
            todos.append(item)
        elif action == 'update':
            item = next((item for item in todos if item['id'] == identity), None)
            if item is None:
                raise ConfigError('未找到该任务，请刷新后再试。')
            _apply(item, fields)
            item['updated_at'] = now
        elif action == 'delete':
            doomed = set(ids)
            while True:  # Collect descendants until the set stops growing.
                grown = doomed | {item['id'] for item in todos if item['parent'] in doomed}
                if grown == doomed:
                    break
                doomed = grown
            todos = [item for item in todos if item['id'] not in doomed]
            item = None
        else:
            raise ConfigError('不支持的待办操作。')
        if item is not None and 'status' in fields:
            # Completion time drives the duration column; leaving "done" restarts the clock.
            item['done_at'] = (item['done_at'] or now) if item['status'] == 'done' else None
        atomic_write(_path(config), json.dumps(todos, ensure_ascii=False, indent=2) + '\n')
    return item if item is not None else {'deleted': sorted(doomed)}
