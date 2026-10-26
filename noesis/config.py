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

[codex]
sessions_root = "~/.codex/sessions"
history_file = "~/.codex/history.jsonl"
max_assistant_chars = 4000

[browser]
enabled = ["chrome", "arc", "safari"]
blacklist_domains = ["*.bank*", "1password.com", "mail.google.com", "localhost"]
max_page_chars = 200000

[git]
author_emails = []
repos = []
scan_roots = ["~/code", "~/Desktop"]
discover_from_sessions = true

[capture]
hotkey = "alt+cmd+s"
ask_note = true
'''

GOALS_TEMPLATE = '''# M6 使用；仅为模板，尚未启用 AI 或网络调用。
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
            if isinstance(expected, list) and not all(isinstance(v, str) for v in actual):
                raise ConfigError(f"配置项 {label} 必须是字符串列表。")
            if type(expected) is int and actual < 1:
                raise ConfigError(f"配置项 {label} 必须大于零。")
    try:
        ZoneInfo(values["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("timezone 必须是有效的 IANA 时区名称。") from None
    if data_root(values["data_dir"]) != root:
        raise ConfigError("config.toml 的 data_dir 与配置所在目录不一致，请使用 --data-dir 选择该目录。")
    if set(values["browser"]["enabled"]) - {"chrome", "arc", "safari"}:
        raise ConfigError("browser.enabled 仅支持 chrome、arc、safari。")
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
    for name in ("db", "daily", "captures", "logs", "bin", "run"):
        private_directory(root / name)
    write_template(root / "goals.yaml", GOALS_TEMPLATE)
    with Database(config.db_path):
        pass
    return config
