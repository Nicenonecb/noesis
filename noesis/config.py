"""Local TOML configuration; never consult a network service."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    pass


DEFAULT_CONFIG = '''timezone = "Asia/Shanghai"
data_dir = __DATA_DIR__

[sources]
claude_code = true
codex = true
browser_history = true
git = true

[claude_code]
root = "~/.claude/projects"
skip_sidechain = true
max_assistant_chars = 4000
strip_tags = ["system-reminder", "environment_context", "user_instructions", "local-command-caveat", "local-command-stdout", "local-command-stderr"]

[codex]
sessions_root = "~/.codex/sessions"
history_file = "~/.codex/history.jsonl"
max_assistant_chars = 4000
injected_prefixes = ["<environment_context>", "<user_instructions>", "# AGENTS.md instructions", "<permissions instructions>"]

[browser]
enabled = ["chrome", "arc", "safari"]
blacklist_domains = ["*.bank*", "1password.com", "mail.google.com", "localhost"]
blacklist_url_regex = []
max_page_chars = 200000

[[browser.profiles_glob]]
name = "chrome"
glob = "~/Library/Application Support/Google/Chrome/{Default,Profile *}/History"
kind = "chromium"
[[browser.profiles_glob]]
name = "arc"
glob = "~/Library/Application Support/Arc/User Data/{Default,Profile *}/History"
kind = "chromium"
[[browser.profiles_glob]]
name = "safari"
glob = "~/Library/Safari/History.db"
kind = "safari"

[git]
author_emails = []
repos = []
scan_roots = ["~/code", "~/Desktop"]
discover_from_sessions = true

[capture]
hotkey = "alt+cmd+s"
ask_note = true

[digest]
enabled = false
model = "deepseek-flash"
reasoning_effort = "high"
generate_after = "00:30"
notify_on_unlock = true
max_input_chars = 60000
max_events = 240
max_tokens = 32768
request_timeout = 180
'''

GOALS_TEMPLATE = '''# 晨报目标模板；只采用 active: true 的目标。
goals:
  - name: "示例目标（请替换）"
    description: "希望推进的事情"
    active: false
'''


def data_root(override: str | Path | None = None) -> Path:
    raw = override or os.environ.get("NOESIS_DATA_DIR") or "~/NOESIS"
    root = Path(raw).expanduser().resolve()
    code_root = Path(__file__).resolve().parents[1]
    if (code_root / "pyproject.toml").exists() and root.is_relative_to(code_root):
        raise ConfigError("数据目录不能放在 noesis 代码仓库中；请使用 ~/NOESIS。")
    return root


@dataclass(frozen=True)
class Config:
    root: Path
    values: dict

    @property
    def db_path(self) -> Path:
        return self.root / "db" / "noesis.sqlite"

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.values["timezone"])

    def source_path(self, section: str, key: str) -> Path:
        return Path(self.values[section][key]).expanduser()


def default_config(root: Path) -> str:
    return DEFAULT_CONFIG.replace("__DATA_DIR__", json.dumps(str(root), ensure_ascii=False))


def load_config(override: str | Path | None = None) -> Config:
    root = data_root(override)
    try:
        with (root / "config.toml").open("rb") as handle:
            values = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError("未找到配置文件，请先运行 noesis init。") from None
    except tomllib.TOMLDecodeError:
        # The offending TOML may contain secrets; do not echo it.
        raise ConfigError("config.toml 不是有效的 TOML，请检查语法。") from None
    defaults = tomllib.loads(default_config(root))
    for name, default in defaults.items():
        if name not in values:
            values[name] = default
        elif isinstance(default, dict):
            if not isinstance(values[name], dict):
                raise ConfigError(f"配置项 {name} 必须是表。")
            values[name] = default | values[name]
    for name, default in defaults.items():
        entries = default.items() if isinstance(default, dict) else [(None, default)]
        for key, expected in entries:
            actual = values[name][key] if key else values[name]
            label = f"{name}.{key}" if key else name
            if type(actual) is not type(expected):
                raise ConfigError(f"配置项 {label} 类型不正确。")
            if isinstance(expected, list) and key != 'profiles_glob' and not all(isinstance(v, str) for v in actual):
                raise ConfigError(f"配置项 {label} 必须是字符串列表。")
            if type(expected) is int and actual < 1:
                raise ConfigError(f"配置项 {label} 必须大于零。")
    try:
        ZoneInfo(values["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("timezone 必须是有效的 IANA 时区名称。") from None
    if data_root(values["data_dir"]) != root:
        raise ConfigError("config.toml 的 data_dir 与配置所在目录不一致，请使用 --data-dir 选择该目录。")
    for profile in values['browser']['profiles_glob']:
        if not isinstance(profile,dict) or not all(isinstance(profile.get(key),str) for key in ('name','glob','kind')) or profile['kind'] not in {'chromium','safari'}:
            raise ConfigError('browser.profiles_glob 结构不正确。')
    if set(values['browser']['enabled']) - {p['name'] for p in values['browser']['profiles_glob']}:
        raise ConfigError('browser.enabled 包含没有配置路径的浏览器。')
    import re
    for key in ('generate_after',):
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', values['digest'][key]):
            raise ConfigError(f'digest.{key} 必须是 HH:MM。')
    if values['digest']['model'] != 'deepseek-flash':
        raise ConfigError('当前晨报仅接入 DeepSeek deepseek-flash。')
    if values['digest']['reasoning_effort'] not in {'low', 'high', 'max'}:
        raise ConfigError('digest.reasoning_effort 必须是 low、high 或 max。')
    if values['digest']['max_tokens'] > 393216:
        raise ConfigError('digest.max_tokens 不能超过 393216。')
    if not 8000 <= values['digest']['max_input_chars'] <= 200000 or not 1 <= values['digest']['max_events'] <= 1000:
        raise ConfigError('晨报输入范围：8000–200000 字符、1–1000 条事件。')
    try:
        for pattern in values['browser']['blacklist_url_regex']:
            re.compile(pattern)
    except re.error:
        raise ConfigError('browser.blacklist_url_regex 不是有效正则。') from None
    for section, keys in {"claude_code": ["root"], "codex": ["sessions_root", "history_file"]}.items():
        for key in keys:
            if not Path(values[section][key]).expanduser().is_absolute():
                raise ConfigError(f"{section}.{key} 必须是绝对路径或 ~/ 路径。")
    return Config(root, values)


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def write_template(path: Path, content: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def initialize(override: str | Path | None = None) -> Config:
    from .db import Database

    root = data_root(override)
    private_directory(root)
    write_template(root / "config.toml", default_config(root))
    config = load_config(root)
    for name in ("db", "daily", "captures", "briefings", "logs", "bin", "run"):
        private_directory(root / name)
    write_template(root / "goals.yaml", GOALS_TEMPLATE)
    with Database(config.db_path):
        pass
    return config
