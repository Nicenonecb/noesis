"""Local initialization, diagnostics and one-shot conversation collection."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .config import ConfigError, initialize, load_config
from .doctor import diagnose
from .redact import redact


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="noesis",
        description="NOESIS · 求是 本地活动采集（M1）",
        epilog="从实事中求是，让每一次循环都进到高一级",
    )
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--data-dir", type=Path, help="数据目录（默认 ~/NOESIS 或 NOESIS_DATA_DIR）")
    sub = root.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="增量采集本地 Claude Code / Codex 对话")
    collect.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    collect.add_argument("--source", choices=["all", "claude_code", "codex"], default="all")
    collect.add_argument("--replay", action="store_true", help="重读完整来源，幂等回填且不改变增量游标")
    for name, help_text in [("init", "初始化目录、配置与数据库，可重复运行"), ("doctor", "只读检查路径与权限，列出手动操作")]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="数据目录")
        if name == "doctor":
            command.add_argument("--strict", action="store_true", help="检测到 ❌ 时返回退出码 1")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            config = initialize(args.data_dir)
            print(redact(f"✅ 初始化完成：{config.root}（保留已有配置与数据）"))
            return 0
        config = load_config(args.data_dir)
        if args.command == "collect":
            from .collectors.collect import collect
            results = collect(config, args.source, replay=args.replay)
            print(json.dumps(results, ensure_ascii=False, sort_keys=True))
            return 1 if any(result.get("failed_files") or result.get("invalid_lines")
                            for result in results.values()) else 0
        checks = diagnose(config)
        for check in checks:
            print(check.render())
        failed = sum(check.status == "fail" for check in checks)
        manual = sum(check.status == "manual" for check in checks)
        print(f"诊断完成：{failed} 项失败，{manual} 项需要手动验证；未启动采集或定时任务。")
        return 1 if args.strict and failed else 0
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
    except (OSError, sqlite3.Error, ValueError) as exc:
        # Paths, SQLite errors, and invalid data can contain source text/secrets.
        print(f"❌ 操作失败（{type(exc).__name__}）。请检查本机配置、目录权限和数据库。", file=sys.stderr)
    return 2
