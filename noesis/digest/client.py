"""Bounded DeepSeek requests. Credentials, prompts and raw errors never enter logs."""

import json
import os
import shlex
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..files import atomic_write

API = 'https://api.deepseek.com'
ENV_NAME = 'DEEPSEEK_API_KEY'


class DigestError(ValueError):
    """Only a fixed, non-sensitive code may be surfaced to the CLI/logs."""


def validate_key(key):
    key = key.strip()
    if not key:
        raise DigestError('api_key_missing')
    if any(char.isspace() for char in key):
        raise DigestError('api_key_invalid')
    return key


def env_assignment(line):
    name, _, value = line.strip().removeprefix('export ').partition('=')
    return name.strip(), value.strip()


def api_key(env_file=None):
    key = os.environ.get(ENV_NAME)
    if key is None and env_file is not None and env_file.exists():
        for line in env_file.read_text().splitlines():
            name, value = env_assignment(line)
            if name == ENV_NAME:
                try:
                    parts = shlex.split(value, comments=True)
                except ValueError:
                    raise DigestError('api_key_invalid') from None
                if len(parts) != 1:
                    raise DigestError('api_key_invalid')
                key = parts[0]
    return validate_key(key or '')


def save_api_key(env_file, key):
    key = validate_key(key)
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    lines = [line for line in lines if env_assignment(line)[0] != ENV_NAME]
    lines.append(ENV_NAME + '=' + shlex.quote(key))
    atomic_write(env_file, '\n'.join(lines) + '\n')  # Atomic replacement uses mode 0600.


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the Authorization header to another endpoint.


def request(path, *, body=None, timeout=90, env_file=None):
    key = api_key(env_file)
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = Request(API + path, data=data, headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    for attempt in range(2):
        try:
            with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise DigestError('response_too_large')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise DigestError('invalid_response')
            return result
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if attempt == 0 and (status == 429 or status >= 500):
                time.sleep(1)
                continue
            raise DigestError(f'http_{status}') from None
        except (URLError, TimeoutError, OSError):
            # Do not immediately repeat a timed-out paid generation: outcome is unknown.
            raise DigestError('network_unavailable_or_timeout') from None
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, DigestError):
                raise
            raise DigestError('invalid_response') from None


def check_model(env_file=None):
    data = request('/models', timeout=20, env_file=env_file)
    items = data.get('data')
    if not isinstance(items, list):
        raise DigestError('invalid_response')
    available = any(isinstance(item, dict) and item.get('id') == 'deepseek-flash'
                    for item in items)
    if not available:
        raise DigestError('requested_model_unavailable')
    return {'model': 'deepseek-flash', 'available': True}


def complete(settings, system, payload, *, env_file=None):
    response = request('/chat/completions', timeout=settings['request_timeout'], body={
        'model': settings['model'], 'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
        'thinking': {'type': 'enabled'}, 'reasoning_effort': settings['reasoning_effort'],
        'response_format': {'type': 'json_object'}, 'max_tokens': settings['max_tokens'], 'stream': False}, env_file=env_file)
    try:
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise DigestError('incomplete_generation')
        value = json.loads(choice['message']['content'])
        usage_data = response.get('usage', {})
        if not isinstance(usage_data, dict):
            raise DigestError('invalid_generation')
        usage = {key: number for key, number in usage_data.items()
                 if key in {'prompt_tokens', 'completion_tokens', 'total_tokens'} and type(number) is int}
        return value, usage, response.get('model', settings['model'])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, DigestError):
            raise
        raise DigestError('invalid_generation') from None
