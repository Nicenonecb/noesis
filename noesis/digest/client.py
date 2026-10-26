"""Bounded DeepSeek requests. Credentials, prompts and raw errors never enter logs."""

import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

API = 'https://api.deepseek.com'
KEYCHAIN_SERVICE = 'com.justin.noesis.deepseek'


class DigestError(ValueError):
    """Only a fixed, non-sensitive code may be surfaced to the CLI/logs."""


def api_key():
    key = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if not key:
        try:
            result = subprocess.run(
                ['security', 'find-generic-password', '-a', 'noesis', '-s', KEYCHAIN_SERVICE, '-w'],
                capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise DigestError('keychain_unavailable') from None
        if result.returncode:
            raise DigestError('api_key_missing' if result.returncode == 44 else 'keychain_locked_or_denied')
        key = result.stdout.strip()
    if not key or any(char.isspace() for char in key):
        raise DigestError('api_key_invalid')
    return key


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the Authorization header to another endpoint.


def request(path, *, body=None, timeout=90):
    key = api_key()
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


def check_model():
    data = request('/models', timeout=20)
    items = data.get('data')
    if not isinstance(items, list):
        raise DigestError('invalid_response')
    available = any(isinstance(item, dict) and item.get('id') == 'deepseek-flash'
                    for item in items)
    if not available:
        raise DigestError('requested_model_unavailable')
    return {'model': 'deepseek-flash', 'available': True}


def complete(settings, system, payload):
    response = request('/chat/completions', timeout=settings['request_timeout'], body={
        'model': settings['model'], 'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
        'thinking': {'type': 'disabled'}, 'temperature': 0.2,
        'response_format': {'type': 'json_object'}, 'max_tokens': settings['max_tokens'], 'stream': False})
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
