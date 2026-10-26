"""Claude Code text, commands and ordered assistant fragments."""

import json
import re

from ..models import utc_timestamp
from .common import fingerprint, human_text, make_event, text_content


def is_sidechain(path):
    """A sidechain marker applies to the whole file, including earlier records."""
    with path.open('rb') as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if isinstance(row, dict) and row.get('isSidechain') is True:
                return True
    return False


def tool_summary(block):
    name = block.get('name')
    if not isinstance(name, str):
        return None
    params = block.get('input') or {}
    if not isinstance(params, dict):
        params = {}
    detail = next((params[key] for key in ('file_path', 'path', 'command', 'pattern', 'query')
                   if isinstance(params.get(key), str)), '')
    return {'name': name, 'summary': detail[:200]}


def parser(settings):
    def parse(record, state, path, line):
        role = record.get('type')
        session = record.get('sessionId') or state.get('session') or path.stem
        if not isinstance(session, str) or (record.get('cwd') is not None and not isinstance(record['cwd'], str)):
            raise ValueError('context')
        state['session'] = session
        if record.get('cwd'):
            state['cwd'] = record['cwd']
        if timestamp := record.get('timestamp'):
            stamp = utc_timestamp(timestamp)
            state['started_at'] = min(state.get('started_at', stamp), stamp)
            state['ended_at'] = max(state.get('ended_at', stamp), stamp)
        if role in {'summary', 'custom-title'}:
            title = record.get('summary') or record.get('customTitle')
            if isinstance(title, str):
                state['title'] = title[:200]
            return None
        if role not in {'user', 'assistant'}:
            skipped = state.setdefault('skipped_types', {})
            key = role if isinstance(role, str) else 'missing_type'
            skipped[key] = skipped.get(key, 0) + 1
            return None
        if record.get('isMeta') or (settings['skip_sidechain'] and record.get('isSidechain')):
            return None
        message = record.get('message')
        if not isinstance(message, dict) or message.get('role') != role:
            return None
        uuid = record.get('uuid')
        if not isinstance(uuid, str) or not uuid:
            raise ValueError('uuid')
        blocks = message.get('content')
        text = text_content(blocks)
        metadata = {'git_branch': record.get('gitBranch'), 'model': message.get('model')}
        if role == 'user':
            command = re.search(r'<command-name>(.*?)</command-name>', text, re.S)
            if command:
                args = re.search(r'<command-args>(.*?)</command-args>', text, re.S)
                text = command[1].strip() + (' ' + args[1].strip() if args and args[1].strip() else '')
                metadata['is_command'] = True
            else:
                text = human_text(text, settings.get('strip_tags'))
            if text.strip() in {'[Request interrupted by user]', '[Request interrupted by user for tool use]'}:
                return None
            if isinstance(blocks, list):
                metadata['images'] = sum(isinstance(b, dict) and b.get('type') == 'image' for b in blocks)
            identity = uuid
        else:
            tools = [tool_summary(b) for b in blocks if isinstance(b, dict) and b.get('type') == 'tool_use'] if isinstance(blocks, list) else []
            metadata['tools'] = [tool for tool in tools if tool]
            identity = message.get('id') or uuid
            metadata['fragment_id'] = fingerprint(uuid)
            metadata['max_chars'] = settings['max_assistant_chars']
        # Keep the existing session prefix for namespace stability.
        return make_event('claude_code', f'{session}:{identity}', role, record['timestamp'], text,
                          session, state.get('cwd'), path, line, settings['max_assistant_chars'], metadata)
    return parse
