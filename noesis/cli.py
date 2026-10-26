"""Local initialization, diagnostics and one-shot conversation collection."""

import argparse
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .config import ConfigError, initialize, load_config
from .doctor import diagnose
from .redact import redact
from .runtime import AlreadyRunning, run_logger, collection_lock


def backfill_window(value):
    if value == 'all':
        return value
    if value.endswith('d') and value[:-1].isdigit() and int(value[:-1]) > 0:
        return timedelta(days=int(value[:-1]))
    raise argparse.ArgumentTypeError('使用 7d、30d 或 all。')


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
    collect.add_argument("--source", choices=["all", "claude_code", "codex",'git','browser_history'], default="all")
    history = collect.add_mutually_exclusive_group()
    history.add_argument("--replay", action="store_true", help="重读完整来源，幂等回填且不改变增量游标")
    history.add_argument('--backfill', type=backfill_window, help='回填 7d / 30d / all，更新增量游标')
    collect.add_argument('--dry-run', action='store_true', help='解析并统计，不修改数据库和游标')
    stats = sub.add_parser("stats", help="查看来源事件数量与最近采集状态")
    stats.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    search = sub.add_parser("search", help="搜索本地记录（中文短词同样支持）")
    search.add_argument("query")
    search.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    search.add_argument("--source", choices=["claude_code", "codex", "git", "browser_history", "capture"])
    search.add_argument("--limit", type=int, default=50)
    repos=sub.add_parser('repos',help='查看、添加或停用 Git 仓库')
    repos.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    actions=repos.add_subparsers(dest='action',required=True)
    actions.add_parser('list')
    for action in ('add','disable'):
        actions.add_parser(action).add_argument('path',type=Path)
    reproject=sub.add_parser('reproject',help='统一既有事件和会话的项目名')
    reproject.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
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
        if args.command in {'repos','reproject'}:
            from .db import Database
            from . import queries
            from .collectors.git_log import repo_info
            with collection_lock(config.root), Database(config.db_path) as db:
                with db.transaction():
                    if args.command=='reproject':
                        output={'updated':db.reproject()}
                    elif args.action=='list':
                        output=queries.get_repos(db.connection)
                    elif args.action=='add':
                        info=repo_info(args.path)
                        db.upsert_repo(info,'config')
                        db.set_repo_enabled(info['path'],True)
                        output=info
                    else:
                        db.set_repo_enabled(args.path,False)
                        output={'disabled':str(args.path.resolve())}
                print(json.dumps(output,ensure_ascii=False))
                return 0
        if args.command in {"stats", "search"}:
            from . import queries
            # Read-only commands never migrate or acquire the writer lock.
            connection = sqlite3.connect(config.db_path.as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                if args.command == "stats":
                    output = asdict(queries.stats(connection, tz=config.timezone))
                else:
                    hits = queries.search(connection, args.query, limit=args.limit, sources=args.source)
                    output = [{"id": hit.event.id, "source": hit.event.source, "ts": hit.event.ts,
                               "project": hit.event.project, "title": hit.event.title,
                               "snippet": hit.snippet} for hit in hits]
                print(json.dumps(output, ensure_ascii=False, sort_keys=True))
                return 0
            finally:
                connection.close()
        if args.command == "collect":
            from .collectors.collect import collect
            results = collect(config, args.source, replay=args.replay, backfill=args.backfill, dry_run=args.dry_run)
            print(json.dumps(results, ensure_ascii=False, sort_keys=True))
            return 1 if any(result.get("status") in {"partial", "failed"}
                            for result in results.values()) else 0
        checks = diagnose(config)
        for check in checks:
            print(check.render())
        failed = sum(check.status == "fail" for check in checks)
        manual = sum(check.status == "manual" for check in checks)
        print(f"诊断完成：{failed} 项失败，{manual} 项需要手动验证；未启动采集或定时任务。")
        return 1 if args.strict and failed else 0
    except AlreadyRunning as exc:
        with run_logger(config) as logger:
            logger.info(str(exc))
        print(str(exc))
        return 0
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
    except (OSError, sqlite3.Error, ValueError) as exc:
        # Paths, SQLite errors, and invalid data can contain source text/secrets.
        print(f"❌ 操作失败（{type(exc).__name__}）。请检查本机配置、目录权限和数据库。", file=sys.stderr)
    return 2
