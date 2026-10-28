"""User-owned focus areas and daily check-ins; model advice never changes this state."""

from datetime import date, datetime, timedelta
import json
from uuid import uuid4

from .config import ConfigError
from .files import atomic_write
from .redact import redact_value
from .runtime import file_lock

OUTCOMES = {'done': '已完成', 'missed': '未完成', 'snoozed': '已延后'}
MAX_ACTIVE = 3


def local_day(config):
    return datetime.now(config.timezone).date()


def read_focuses(config):
    path = config.root / 'focus.json'
    return json.loads(path.read_text()) if path.exists() else []


def _text(value, label, limit, *, optional=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (not optional and not value.strip()):
        raise ConfigError(f'{label}需要填写 1–{limit} 个字符。' if not optional else f'{label}最多 {limit} 个字符。')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ConfigError(f'{label}不能包含控制字符。')
    return value.strip()


def change_focus(config, action, *, identity=None, title=None, direction=None, step=None,
                 outcome=None, note='', until=None, expected_day=None, today=None):
    today = today or local_day(config)
    if expected_day is not None and expected_day != today.isoformat():
        raise ConfigError('该提醒已跨日，请重新打开今天的晨报再反馈。')
    tomorrow = (today + timedelta(days=1)).isoformat()
    with file_lock(config.root / 'run/focus.lock'):
        focuses = read_focuses(config)
        if action == 'add':
            item = {'id': uuid4().hex[:12], 'active': True, 'revision': 0,
                    'created_on': today.isoformat(), 'next_due': tomorrow, 'checkins': []}
            focuses.append(item)
        else:
            item = next((item for item in focuses if item['id'] == identity), None)
            if item is None:
                raise ConfigError('未找到该关注方向，请先运行 noesis focus list。')
        if action in {'add', 'update'}:
            for key, value, label, limit in [('title', title, '名称', 80),
                                            ('direction', direction, '发展方向', 300),
                                            ('step', step, '具体行动', 200)]:
                if value is not None or action == 'add':
                    item[key] = _text(value, label, limit)
        elif action in {'pause', 'resume'}:
            item['active'] = action == 'resume'
            if action == 'resume':
                item['next_due'] = tomorrow
        elif action == 'checkin':
            if not item['active']:
                raise ConfigError('该方向已暂停，请先恢复再反馈。')
            if outcome not in OUTCOMES:
                raise ConfigError('反馈必须是 done、missed 或 snoozed。')
            due = tomorrow
            if until is not None:
                if outcome != 'snoozed' or date.fromisoformat(until) <= today:
                    raise ConfigError('延后日期必须晚于今天，且仅用于 snoozed。')
                due = date.fromisoformat(until).isoformat()
            entry = {'day': today.isoformat(), 'outcome': outcome,
                     'note': _text(note, '反馈备注', 200, optional=True)}
            # A correction replaces today's answer; retries cannot duplicate it.
            item['checkins'] = [c for c in item['checkins'] if c['day'] != today.isoformat()]
            item['checkins'] = (item['checkins'] + [entry])[-30:]
            item['next_due'] = due
        else:
            raise ConfigError('不支持的关注方向操作。')
        if sum(item['active'] for item in focuses) > MAX_ACTIVE:
            raise ConfigError('最多同时启用 3 个关注方向，请先暂停一个。')
        item['revision'] += 1
        atomic_write(config.root / 'focus.json', json.dumps(redact_value(focuses), ensure_ascii=False, indent=2) + '\n')
    return {'status': 'saved', 'id': item['id'], 'next_due': item['next_due']}


def due_focuses(config, day):
    """Bounded context, including the latest explicit answer rather than inferred progress."""
    return [{key: item[key] for key in ('id', 'title', 'direction', 'step', 'revision', 'next_due')}
            | {'last_checkin': item['checkins'][-1] if item['checkins'] else None}
            for item in read_focuses(config)
            if item['active'] and item['created_on'] <= day.isoformat() and item['next_due'] <= day.isoformat()]
