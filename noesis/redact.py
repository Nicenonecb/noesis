"""Best-effort pattern redaction, shared by every persistent text boundary.

This does not redact screenshot pixels or promise to detect arbitrary secrets.
Call before truncation so truncated credentials cannot evade recognition.
"""

import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from typing import Any


def clean_url(url: str, *, tracking=False) -> str:
    parsed=urlsplit(url)
    secret={'token','access_token','code','key','sig','signature','password','session','api_key','auth','secret'}
    query=[]
    for name,value in parse_qsl(parsed.query,keep_blank_values=True):
        key=name.lower()
        if tracking and (key.startswith(('utm_','share_')) or key in {'fbclid','gclid','spm','from'}):
            continue
        query.append((name,'REDACTED' if key in secret else redact(value)))
    netloc=parsed.netloc.rsplit('@',1)[-1] if '@' in parsed.netloc else parsed.netloc
    return redact(urlunsplit((parsed.scheme,netloc,parsed.path,urlencode(query),parsed.fragment)))

_PATTERNS = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----[\s\S]*?-----END \1-----")),
    ("API_KEY", re.compile(r"(?<![\w-])sk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
]
_ENV = re.compile(
    r"^(?P<prefix>[ \t]*(?:export[ \t]+)?(?=[A-Za-z_][A-Za-z0-9_]*[ \t]*=)"
    r"[A-Za-z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD)[A-Za-z0-9_]*[ \t]*=[ \t]*)"
    r"(?P<value>[^\r\n]+)", re.MULTILINE | re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r'''(?P<prefix>(?<![\w])(?:password|passwd|secret|token|api_key)["']?\s*[:=]\s*)'''
    r'''(?P<value>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\[REDACTED:[A-Z_]+\]|[^\s,;}&<>"']+)''',
    re.IGNORECASE,
)


def redact(text: str) -> str:
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)

    def assignment(match: re.Match, label: str) -> str:
        value = match["value"]
        quote = value[0] if value.startswith(('"', "'")) else ""
        bare = value[1:-1] if quote else value
        if re.fullmatch(r"\[REDACTED:[A-Z_]+\]", bare):
            return match.group(0)
        return match["prefix"] + quote + f"[REDACTED:{label}]" + quote

    text = _ENV.sub(lambda match: assignment(match, "ENV_SECRET"), text)
    return _ASSIGNMENT.sub(lambda match: assignment(match, "SECRET"), text)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON 对象的键必须是字符串。")
        result = {}
        for key, child in value.items():
            clean_key = redact(key)
            if clean_key in result:
                raise ValueError("脱敏后 JSON 键发生冲突。")
            # Structured credentials have no textual '=' or ':' until serialized.
            if re.search(r"secret|token|password|passwd|api_?key", key, re.IGNORECASE):
                result[clean_key] = "[REDACTED:SECRET]"
            else:
                result[clean_key] = redact_value(child)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_value(child) for child in value]
    if value is None or type(value) in (int, float, bool):
        return value
    raise ValueError("只支持 JSON 兼容的数据。")
