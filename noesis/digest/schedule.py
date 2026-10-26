"""00:30 generation, bounded recovery, and one acknowledged presentation per day."""

from datetime import date, datetime, timedelta
import json

from ..collectors.collect import collect
from ..files import atomic_write
from ..render.daily import build_daily
from ..runtime import AlreadyRunning, file_lock, run_logger
from .client import DigestError
from .digest import generate


def read_state(config, delivery):
    path = config.root / 'run/morning-state.json'
    if path.exists():
        state = json.loads(path.read_text())
        if state.get('delivery_day') == delivery:
            return state
    return {'delivery_day': delivery, 'attempts': 0}


def save_state(config, state):
    atomic_write(config.root / 'run/morning-state.json', json.dumps(state, ensure_ascii=False) + '\n')


def morning_run(config, *, unlocked=False, unlock_event=False, now=None):
    if not config.values['digest']['enabled']:
        return {'status': 'disabled'}
    now = (now or datetime.now(config.timezone)).astimezone(config.timezone)
    if now.strftime('%H:%M') < config.values['digest']['generate_after']:
        return {'status': 'not_due'}
    delivery = now.date().isoformat()
    day = now.date() - timedelta(days=1)
    with file_lock(config.root / 'run/morning.lock', blocking=False), run_logger(config) as logger:
        state = read_state(config, delivery)
        target = config.root / 'briefings' / (delivery + '.json')
        if not target.exists():
            transient = state.get('error') in {'network_unavailable_or_timeout', 'keychain_unavailable', 'keychain_locked_or_denied', 'http_429'} or state.get('error', '').startswith('http_5')
            recovery = unlock_event and transient and not state.get('unlock_retry_used')
            retry_due = not state.get('last_attempt') or now - datetime.fromisoformat(state['last_attempt']) >= timedelta(minutes=30)
            if (state['attempts'] < 3 and retry_due) or recovery:
                # A busy collector is not a model failure and does not consume a retry.
                try:
                    collected = collect(config)
                    build_daily(config, catch_up=7)
                except AlreadyRunning:
                    return {'status': 'busy'}
                state['source_status'] = {key: value['status'] for key, value in collected.items()}
                state['attempts'] += 1
                if recovery:state['unlock_retry_used'] = True
                state['last_attempt'] = now.isoformat()
                save_state(config, state)
                try:
                    generate(config, day)
                    state.pop('error', None)
                except AlreadyRunning:
                    state['attempts'] -= 1
                    if recovery:state.pop('unlock_retry_used', None)
                    state.pop('last_attempt', None)
                    save_state(config, state)
                    return {'status': 'busy'}
                except DigestError as exc:
                    state['error'] = str(exc)
                    if str(exc) in {'http_401', 'http_402', 'http_403', 'api_key_missing'}:
                        state['attempts'] = 3
                    logger.error('digest day=%s error=%s attempt=%d', day, str(exc), state['attempts'])
                save_state(config, state)
        if target.exists():
            result = generate(config, day)  # Cached; also repairs derived HTML/Markdown.
            if unlocked and config.values['digest']['notify_on_unlock'] and not state.get('presented_at'):
                return {'status': 'ready', 'show': result['path'], 'delivery_day': delivery, 'failure': False}
            return {'status': 'already_presented' if state.get('presented_at') else 'ready_waiting_for_unlock', 'delivery_day': delivery}
        if unlocked and state.get('error') and not state.get('error_presented_at'):
            error_path = config.root / 'briefings' / (delivery + '-error.html')
            # Only fixed internal error codes reach this page; never provider error bodies.
            from html import escape
            atomic_write(error_path, '<!doctype html><meta charset="utf-8"><title>NOESIS 晨报</title>'
                '<main style="max-width:700px;margin:70px auto;font:18px/1.8 -apple-system">'
                '<h1>晨报暂未生成</h1><p>昨日原始日志已保存。请检查网络、API 余额或钥匙串访问权限。</p>'
                f'<p>状态：{escape(state["error"])}</p><p>稍后会按重试规则补生成，成功后再次解锁即可查看。</p></main>')
            return {'status': 'failed', 'show': str(error_path), 'delivery_day': delivery, 'failure': True}
        return {'status': 'failed', 'error': state.get('error', 'retry_pending'), 'attempts': state['attempts']}


def acknowledge(config, delivery, *, failure=False):
    if date.fromisoformat(delivery) != datetime.now(config.timezone).date():
        raise DigestError('presentation_date_mismatch')
    suffix = '-error.html' if failure else '.html'
    if not (config.root / 'briefings' / (delivery + suffix)).is_file():
        raise DigestError('briefing_missing')
    with file_lock(config.root / 'run/morning.lock'):
        state = read_state(config, delivery)
        state['error_presented_at' if failure else 'presented_at'] = datetime.now(config.timezone).isoformat()
        save_state(config, state)
    return {'status': 'acknowledged', 'delivery_day': delivery}
