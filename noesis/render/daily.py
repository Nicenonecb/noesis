"""Deterministic, project-oriented Markdown derived only through queries."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import json
from zoneinfo import ZoneInfo

from .. import queries
from ..db import Database
from ..runtime import collection_lock, run_logger
from ..timeutils import day_range
from ..redact import redact
from ..capture.render import single_line
from ..files import atomic_write

LABELS={'claude_code':'Claude Code','codex':'Codex','git':'Git','browser_history':'浏览','capture':'收藏'}


def excerpt(value,limit):
    value=single_line(value)
    return value[:limit]+('…' if len(value)>limit else '')


def local_time(event,tz):
    return datetime.fromisoformat(event.ts).astimezone(tz).strftime('%H:%M')


def capture_link(event):
    path=str(Path(event.meta['screenshot']).with_suffix('.md'))
    label=single_line(event.title).replace('|','¦').replace('[','').replace(']','')
    return f'[[{path}|{label}]]'


def rounds(events):
    result=[]
    for event in events:
        if event.kind=='user_msg' or not result:
            result.append([])
        result[-1].append(event)
    return result


def render_day(conn, day, tz):
    if isinstance(tz,str):tz=ZoneInfo(tz)
    start,end=day_range(day,tz)
    events=queries.get_events(conn,start=start,end=end)
    sessions={(s.source,s.session_id):s for s in queries.get_sessions(conn,start=start,end=end)}
    counts=dict(sorted(Counter(e.source for e in events).items()))
    projects=sorted({e.project for e in events if e.project})
    times=queries.project_time(conn,start=start,end=end)
    durations={item.project:item.minutes for item in times}
    lines=['---',f'date: {day.isoformat()}','type: daily',
           'sources: '+json.dumps(counts,ensure_ascii=False,sort_keys=True),
           'projects: '+json.dumps(projects,ensure_ascii=False),'---',f'# {day.isoformat()} 活动日志','',
           '## 概览','', '；'.join(f'{LABELS[source]} {number}' for source,number in counts.items()) or '暂无活动。','']
    for item in times[:8]:
        lines.append(f'- {single_line(item.project)}：约 {item.minutes//60}h {item.minutes%60}m')
    lines+=['','## ⭐ 手动收藏','']
    for event in (e for e in events if e.source=='capture'):
        lines.append(f'- {local_time(event,tz)} {capture_link(event)}')
        if event.url:lines.append('  '+event.url)
        if event.meta.get('note'):lines.append('  备注：'+excerpt(event.meta['note'],300))
        if event.content:lines.append('  摘录：'+excerpt(event.content,300))
    lines+=['','## 按项目','']
    groups=defaultdict(list)
    for event in events:
        if event.source in {'claude_code','codex','git'}:groups[event.project or None].append(event)
    order=sorted((project for project in groups if project),key=lambda p:(-durations.get(p,0),p))
    if None in groups:order.append(None)
    for project in order:
        minutes=durations.get(project,0)
        lines+=([f'### {single_line(project)} · 约 {minutes//60}h {minutes%60}m',''] if project else ['## 未归类',''])
        conversation=defaultdict(list)
        for event in groups[project]:
            if event.source in {'claude_code','codex'}:conversation[(event.source,event.session_id)].append(event)
        for key,items in sorted(conversation.items(),key=lambda pair:(pair[1][0].ts,str(pair[0]))):
            session=sessions.get(key)
            title=session.title if session else items[0].content[:60]
            lines += [f'#### {LABELS[key[0]]} · {local_time(items[0],tz)}–{local_time(items[-1],tz)} · 《{single_line(title)}》','']
            turns=rounds(items)
            for turn in turns[:20]:
                users=[e for e in turn if e.kind=='user_msg']
                if users:lines.append(f'- 👤 {local_time(users[0],tz)} {excerpt(users[0].content,120)}')
                replies=[e for e in turn if e.kind=='assistant_msg']
                if replies:
                    tools=Counter(tool.get('name','unknown') if isinstance(tool,dict) else str(tool)
                                  for event in replies for tool in event.meta.get('tools',[]))
                    summary=excerpt(' '.join(event.content for event in replies if event.content),300)
                    suffix=' `[tools: '+', '.join(f'{name}×{number}' for name,number in sorted(tools.items()))+']`' if tools else ''
                    lines.append('- 🤖 '+summary+suffix)
            if len(turns)>20:lines.append(f'…另有 {len(turns)-20} 轮')
            lines.append('')
        commits=[e for e in groups[project] if e.source=='git' and not e.meta.get('is_merge')]
        if commits:
            lines+=['#### Git','']
            for event in commits:
                meta=event.meta
                lines.append(f"- {local_time(event,tz)} `{event.source_id[:7]}` {excerpt(event.title,200)}（+{meta.get('insertions',0)}/−{meta.get('deletions',0)}，{meta.get('files_changed',0)} 个文件）")
            lines.append('')
    lines+=['## 浏览（按域名）','','| 域名 | 次数 | 停留 | 代表页面 |','|---|---:|---:|---|']
    for domain in queries.domain_summary(conn,start=start,end=end):
        pages='；'.join(excerpt(page['title'],60)+' <'+page['url'].replace('|','%7C')+'>' for page in domain.pages)
        lines.append(f'| {domain.domain} | {domain.visits} | {round(domain.duration_seconds)}s | {pages.replace("|","¦")} |')
    return redact('\n'.join(lines).strip()+'\n')


def write_day(config, conn, day):
    path=config.root/'daily'/f'{day.isoformat()}.md'
    content=render_day(conn,day,config.timezone)
    if path.exists() and path.read_text()==content:
        return False
    atomic_write(path,content)
    return True


def build_daily(config, *, day=None, catch_up=None):
    today=datetime.now(config.timezone).date()
    if catch_up is not None and catch_up<1:
        raise ValueError('catch-up 必须大于零。')
    if catch_up:
        days=[today-timedelta(days=n) for n in range(catch_up-1,-1,-1)]
    else:
        selected=today if day in (None,'today') else today-timedelta(days=1) if day=='yesterday' else date.fromisoformat(day)
        days=[selected]
    result={'written':[],'unchanged':[]}
    with collection_lock(config.root), Database(config.db_path) as db, run_logger(config) as logger:
        for selected in days:
            # Compare deterministic bytes rather than mtimes: handles deletions,
            # old-event edits and session-title changes without another cache table.
            changed=write_day(config,db.connection,selected)
            result['written' if changed else 'unchanged'].append(selected.isoformat())
        logger.info('build-daily written=%d unchanged=%d',len(result['written']),len(result['unchanged']))
    return result
