"""Read-only diagnostics. Never prompt for permissions or launch applications."""

from dataclasses import dataclass
from pathlib import Path
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from .config import Config
from .db import SCHEMA_VERSION
from .redact import redact


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def render(self) -> str:
        symbol = {"ok": "✅", "fail": "❌", "manual": "⚠️", "skip": "⚪"}[self.status]
        suffix = f"；处理：{self.fix}" if self.fix else ""
        return redact(f"{symbol} {self.name}：{self.detail}{suffix}")


def inspect_history(path: Path, tables: tuple[str, ...]) -> None:
    """Read a disposable copy, including WAL, and discard all rows.

    Copying an active SQLite database is not an atomic snapshot. Retry a failed
    copy/check once; a failure is reported rather than called permission success.
    M3 will implement collection and its cursor strategy separately.
    """
    for attempt in range(2):
        try:
            with tempfile.TemporaryDirectory(prefix="noesis-doctor-") as temp:
                target = Path(temp) / path.name
                shutil.copyfile(path, target)
                target.chmod(0o600)
                wal = path.with_name(path.name + "-wal")
                if wal.exists():
                    wal_copy = target.with_name(target.name + "-wal")
                    shutil.copyfile(wal, wal_copy)
                    wal_copy.chmod(0o600)
                connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)
                try:
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("快照一致性检查失败")
                    for table in tables:
                        # Only internal constant table names are accepted by callers.
                        if table not in {"urls", "visits", "history_items", "history_visits"}:
                            raise ValueError("未知历史表")
                        connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                finally:
                    connection.close()
            return
        except (OSError, sqlite3.Error):
            if attempt:
                raise


def _source_check(name: str, root: Path, pattern: str) -> Check:
    try:
        if not root.is_dir():
            return Check(name, "fail", f"目录不存在：{root}", "检查配置路径；不使用该来源时在 sources 中关闭")
        # Path.rglob may suppress permission errors; probe the root explicitly.
        with os.scandir(root):
            pass
        sample = next(root.rglob(pattern), None)
        if sample is None:
            return Check(name, "manual", f"路径可访问，尚无 {pattern} 文件：{root}", "产生一次会话后重试")
        with sample.open("rb") as handle:
            handle.read(1)
        return Check(name, "ok", f"目录与一个样本可读：{root}（未检查全部文件）")
    except OSError as exc:
        return Check(name, "fail", f"无法读取（{type(exc).__name__}）", "检查目录权限及运行解释器的授权")


def _installed(bundle: str) -> bool:
    return any((root / bundle).exists() for root in (Path("/Applications"), Path.home() / "Applications"))


def diagnose(config: Config) -> list[Check]:
    checks = [
        Check("Python", "ok" if sys.version_info >= (3, 11) else "fail", platform.python_version()),
        Check("运行解释器", "ok", f"{sys.executable}；真实二进制：{Path(sys.executable).resolve()}"),
        Check("配置", "ok", f"{config.root / 'config.toml'}；时区 {config.timezone.key}"),
        Check("操作系统", "ok" if sys.platform == "darwin" else "manual", platform.system(),
              "截图、AppleScript、launchd 需要 macOS" if sys.platform != "darwin" else ""),
    ]
    try:
        connection = sqlite3.connect(config.db_path.as_uri() + "?mode=ro", uri=True)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise sqlite3.DatabaseError("schema version mismatch")
            connection.execute("SELECT id, source, ts, meta FROM events LIMIT 0")
            connection.execute("SELECT source, key, value FROM cursors LIMIT 0")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
        finally:
            connection.close()
        checks.append(Check("数据库", "ok", f"schema v{version}，一致性检查通过"))
    except (OSError, sqlite3.Error):
        checks.append(Check("数据库", "fail", "无法读取或结构不完整", "先运行 noesis init；已有数据时先备份再检查"))
    enabled = config.values["sources"]
    if enabled["claude_code"]:
        checks.append(_source_check("Claude Code", config.source_path("claude_code", "root"), "*.jsonl"))
    if enabled["codex"]:
        checks.append(_source_check("Codex sessions", config.source_path("codex", "sessions_root"), "rollout-*.jsonl"))
        try:
            with config.source_path("codex", "history_file").open("rb") as handle:
                handle.read(1)
            checks.append(Check("Codex history", "ok", "补充历史文件可读；不保证覆盖桌面会话"))
        except OSError:
            checks.append(Check("Codex history", "manual", "补充历史不可读；sessions 仍可独立使用", "检查 codex.history_file"))
    browsers = {
        "chrome": ("Google Chrome.app", Path.home() / "Library/Application Support/Google/Chrome", "*/History", ("urls", "visits")),
        "arc": ("Arc.app", Path.home() / "Library/Application Support/Arc/User Data", "*/History", ("urls", "visits")),
        "safari": ("Safari.app", Path.home() / "Library/Safari", "History.db", ("history_items", "history_visits")),
    }
    if enabled["browser_history"]:
        for name in config.values["browser"]["enabled"]:
            bundle, root, pattern, tables = browsers[name]
            installed = _installed(bundle)
            try:
                paths = sorted(root.glob(pattern))
                if not paths:
                    checks.append(Check(name, "manual" if installed else "skip", "未发现历史库", "确认已使用此浏览器；检查路径/访问权限" if installed else ""))
                for path in paths:
                    try:
                        inspect_history(path, tables)
                        checks.append(Check(f"{name}/{path.parent.name}", "ok", "历史库副本（含存在的 WAL）可读"))
                    except PermissionError:
                        checks.append(Check(name, "fail", "历史库访问被拒绝", "系统设置 → 隐私与安全性 → 完全磁盘访问权限；核对上面打印的解释器及启动终端/Codex，重启后重试"))
                    except (OSError, sqlite3.Error) as exc:
                        checks.append(Check(name, "fail", f"历史库副本读取失败（{type(exc).__name__}）", "稍后重试，并检查文件权限及数据库完整性"))
            except OSError:
                checks.append(Check(name, "fail", "历史目录不可读", "检查完全磁盘访问权限"))
    if enabled["git"]:
        git = shutil.which("git")
        if git is None:
            checks.append(Check("Git", "fail", "未找到 git", "安装 Xcode Command Line Tools"))
        elif config.values["git"]["author_emails"]:
            checks.append(Check("Git 作者", "ok", "已在配置中指定作者邮箱"))
        else:
            try:
                result = subprocess.run([git, "config", "--get", "user.email"], capture_output=True, text=True, timeout=5)
                checks.append(Check("Git 作者", "ok" if result.returncode == 0 and result.stdout.strip() else "manual",
                                    "已找到默认邮箱" if result.returncode == 0 and result.stdout.strip() else "未找到默认邮箱",
                                    "" if result.returncode == 0 and result.stdout.strip() else "在 git.author_emails 中填写自己的提交邮箱"))
            except (OSError, subprocess.SubprocessError):
                checks.append(Check("Git 作者", "fail", "git config 检查失败", "检查本机 git 可用性"))
    hs = _installed("Hammerspoon.app")
    checks.extend([
        Check("Hammerspoon（M4）", "ok" if hs else "manual", "已安装" if hs else "未安装", "M4 前安装 Hammerspoon" if not hs else ""),
        Check("屏幕录制（M4）", "manual", "未验证 Hammerspoon 及实际截图进程的授权", "系统设置 → 隐私与安全性 → 屏幕录制；M4 通过真实快捷键截图复验"),
        Check("辅助功能（M4）", "manual", "未验证 Hammerspoon 授权", "系统设置 → 隐私与安全性 → 辅助功能 → Hammerspoon"),
        Check("自动化 / Apple 事件（M4）", "manual", "未发送 Apple 事件，不触发授权弹窗", "M4 首次运行时允许实际调用方控制浏览器，并在隐私与安全性 → 自动化核对"),
        Check("浏览器 JavaScript（M4）", "manual", "未运行浏览器脚本", "Chrome：显示 → 开发者 → 允许 Apple 事件中的 JavaScript；Safari：开发 → 允许 Apple 事件中的 JavaScript；Arc 在 M4 实测"),
        Check("OCR（M4）", "ok" if (config.root / "bin/noesis-ocr").is_file() else "manual", "已发现二进制" if (config.root / "bin/noesis-ocr").is_file() else "尚未编译；M4 实现"),
        Check("launchd（M5）", "manual", "尚未安装；当前进程的权限不代表定时任务权限", "M5 安装后给 plist 中实际解释器授权，并通过 launchd 实测 Safari 读取"),
    ])
    return checks
