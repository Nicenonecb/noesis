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
    capture=sub.add_parser('capture',help='截图收藏，后台识别文字')
    capture.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    capture.add_argument('--window-id',type=int)
    capture.add_argument('--app',default='')
    capture.add_argument('--app-name',default='')
    capture.add_argument('--window-title',default='')
    capture.add_argument('--region',action='store_true')
    for command in ('capture-ocr','annotate'):
        child=sub.add_parser(command)
        child.add_argument('id')
        child.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
        if command=='annotate':
            child.add_argument('--note',required=True)
    for command in ('build-daily','daily-run'):
        daily=sub.add_parser(command,help='生成每日 Markdown；daily-run 先采集')
        daily.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
        choice=daily.add_mutually_exclusive_group()
        choice.add_argument('--date',default='today')
        choice.add_argument('--catch-up',type=int)
    audit=sub.add_parser('audit-redaction',help='仅报告脱敏命中位置，可修复并重建 Markdown')
    audit.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    audit.add_argument('--fix',action='store_true')
    digest=sub.add_parser('digest',help='用 DeepSeek 生成指定完整日期的晨报')
    digest.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    digest.add_argument('--date',default='yesterday')
    digest.add_argument('--force',action='store_true',help='重新调用模型，替换已有晨报')
    model=sub.add_parser('digest-check',help='检查钥匙串与官方模型接口')
    model.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    morning=sub.add_parser('morning-run',help='按计划生成晨报；解锁后请求展示')
    morning.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    morning.add_argument('--unlocked',action='store_true')
    morning.add_argument('--unlock-event',action='store_true',help='原生观察器报告一次真实解锁，可补一次临时故障重试')
    ack=sub.add_parser('morning-ack',help='由本机晨报窗口确认已经展示')
    ack.add_argument('date')
    ack.add_argument('--failure',action='store_true')
    ack.add_argument('--data-dir',type=Path,default=argparse.SUPPRESS)
    for name, help_text in [("init", "初始化目录、配置与数据库，可重复运行"), ("doctor", "只读检查路径与权限，列出手动操作")]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="数据目录")
        if name == "doctor":
            command.add_argument("--strict", action="store_true", help="检测到 ❌ 时返回退出码 1")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = None
    try:
        if args.command == "init":
            config = initialize(args.data_dir)
            print(redact(f"✅ 初始化完成：{config.root}（保留已有配置与数据）"))
            return 0
        config = load_config(args.data_dir)
        if args.command in {'digest','digest-check','morning-run','morning-ack'}:
            from datetime import date,datetime
            from .digest import client
            from .digest.digest import generate
            from .digest.schedule import morning_run,acknowledge
            try:
                if args.command=='digest-check':
                    result=client.check_model()
                elif args.command=='digest':
                    selected=datetime.now(config.timezone).date()-timedelta(days=1) if args.date=='yesterday' else date.fromisoformat(args.date)
                    result=generate(config,selected,force=args.force)
                elif args.command=='morning-ack':
                    result=acknowledge(config,args.date,failure=args.failure)
                else:
                    result=morning_run(config,unlocked=args.unlocked or args.unlock_event,unlock_event=args.unlock_event)
                print(json.dumps(result,ensure_ascii=False))
                return 1 if result.get('status')=='failed' else 0
            except client.DigestError as exc:
                print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False))
                return 1
        if args.command in {'build-daily','daily-run'}:
            from .render.daily import build_daily
            collected=None
            if args.command=='daily-run':
                from .collectors.collect import collect
                collected=collect(config)
            result=build_daily(config,day=args.date,catch_up=args.catch_up)
            print(json.dumps({'daily':result,'collect':collected} if collected is not None else result,ensure_ascii=False))
            return 1 if collected and any(r['status'] in {'partial','failed'} for r in collected.values()) else 0
        if args.command=='audit-redaction':
            from .audit import audit_redaction
            result=audit_redaction(config,fix=args.fix)
            print(json.dumps(result,ensure_ascii=False))
            return 1 if result['remaining'] else 0
        if args.command in {'capture','capture-ocr','annotate'}:
            from .capture.capture import create_capture,enrich_capture,annotate
            if args.command=='capture':
                result=create_capture(config,window_id=args.window_id,app=args.app,app_name=args.app_name,window_title=args.window_title,region=args.region)
            elif args.command=='capture-ocr':
                result=enrich_capture(config,args.id)
            else:
                result=annotate(config,args.id,args.note)
            print(json.dumps(result,ensure_ascii=False))
            return 0
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
        if config is not None and args.command in {'capture','capture-ocr','annotate'}:
            import traceback
            frames=';'.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in traceback.extract_tb(exc.__traceback__))
            try:
                with run_logger(config) as logger:
                    logger.error('command=%s error=%s frames=%s',args.command,type(exc).__name__,frames)
            except OSError:
                pass  # A log write error must not obscure the original failure.
        # Paths, SQLite errors, and invalid data can contain source text/secrets.
        print(f"❌ 操作失败（{type(exc).__name__}）。请检查本机配置、目录权限和数据库。", file=sys.stderr)
    return 2
