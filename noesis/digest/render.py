"""Local morning report, rendered from validated data without remote assets or scripts."""

from datetime import datetime
from html import escape, unescape
import json

from ..files import write_if_changed
from ..capture.render import single_line
from ..render.markdown import export_markdown, render_markdown

LABELS = {'completed': '昨日成果', 'progress': '进行中的工作', 'unfinished': '未完成与待确认', 'priorities': '今日建议 · 待你确认'}
CSS = '''body{margin:0;background:#f4f3ed;color:#20342c;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
main{max-width:960px;margin:auto;padding:40px 24px}header{border-bottom:1px solid #ccd4c9;padding-bottom:26px;margin-bottom:26px}
.brand{letter-spacing:.16em;color:#577564;font-size:13px}h1{font-size:34px;line-height:1.3;margin:12px 0}h2{font-size:20px;margin-top:0}
.muted{color:#65766b;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.project-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:7px}.project-tag{display:inline-block;border:1px solid #b9cbbb;border-radius:6px;padding:2px 9px;background:#edf3e9;color:#365b42;font-size:13px;font-weight:650;overflow-wrap:anywhere;max-width:100%;box-sizing:border-box}
section{padding:24px;background:white;border:1px solid #dce2d8;border-radius:14px}.focus{background:#e6efdf;border-color:#aec5a0}
ul{padding-left:22px;margin-bottom:0}li{margin:12px 0}a{color:#39724d}summary{cursor:pointer;font-weight:600}
details{margin-top:24px;padding:20px;background:#fff;border-radius:12px}.evidence{padding:24px 0;border-top:1px solid #e1e5de;scroll-margin-top:24px}
.evidence-heading{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.evidence-title{font-weight:600;margin:16px 0 10px}
.markdown-body{min-width:0;overflow-wrap:anywhere}.markdown-body>:first-child{margin-top:0}.markdown-body>:last-child{margin-bottom:0}
.markdown-body p{margin:12px 0}.markdown-body h1,.markdown-body h2{font-size:22px;margin:24px 0 12px}
.markdown-body h3,.markdown-body h4,.markdown-body h5,.markdown-body h6{font-size:18px;margin:20px 0 10px}
.markdown-body ul,.markdown-body ol{padding-left:24px;margin:10px 0}.markdown-body li{margin:5px 0}
.markdown-body blockquote{margin:16px 0;padding:2px 16px;border-left:3px solid #9cb590;background:#f4f7f0;color:#50634f}
.markdown-body code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em;background:#eef1e9;padding:2px 5px;border-radius:4px}
.markdown-body pre{margin:16px 0;padding:16px;background:#eef1e9;border:1px solid #dce2d8;border-radius:8px;overflow-x:auto;white-space:pre}
.markdown-body pre code{background:none;padding:0;border-radius:0;font-size:13px;line-height:1.6}
.markdown-body table{display:block;overflow-x:auto;border-collapse:collapse;max-width:100%;font-size:14px;margin:16px 0}
.markdown-body th,.markdown-body td{border:1px solid #d5decf;padding:8px 12px;text-align:left}.markdown-body th{background:#eef3e7}
.markdown-body hr{border:0;border-top:1px solid #dce2d8;margin:22px 0}.markdown-body .task-list-item{list-style:none}
.markdown-body .task-list-item-checkbox{margin:0 7px 0 -18px;accent-color:#507b48}.references{margin-top:8px;font-size:13px}
.image-reference{color:#65766b;font-size:14px}.grid section{min-width:0}footer{margin-top:22px}
@media(max-width:700px){.grid{grid-template-columns:1fr}h1{font-size:28px}main{padding:24px 16px}}'''


def write_briefing(config, record):
    day = record['delivery_day']
    result = record['result']
    tasks = {task['id']: task for task in result.get('tasks', [])}
    evidence = {item['id']: item for item in record['evidence']}
    metadata = f"总结日期 {record['source_day']} · 来源 {sum(record['source_counts'].values())} 条 · 引用摘录 {len(record['evidence'])} 条"
    caveat = 'AI 根据活动记录归纳，完成状态仍需核实；今日重点是建议。'
    if record['omitted_events']:
        caveat += f" 本次输入未包含 {record['omitted_events']} 条事件。"
    unhealthy = [name for name, status in record['source_health'].items() if status != 'ok']
    if unhealthy:
        caveat += ' 来源采集未全部成功：' + '、'.join(unhealthy) + '。'
    md = ['---', 'type: morning-briefing', 'date: ' + day,
          'source_date: ' + record['source_day'], 'model: ' + json.dumps(record['model']), '---',
          f'# {day} 晨报', '', export_markdown(result['summary'], 'summary'), '', metadata, '', caveat, '']
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
            f'<title>NOESIS 晨报 · {day}</title><style>{CSS}</style><main>',
            f'<header><div class="brand">NOESIS · 求是 / MORNING BRIEF</div><h1>{day}，从昨天继续。</h1>',
            f'<div class="markdown-body">{render_markdown(result["summary"], "summary")}</div>'
            f'<div class="muted">{escape(metadata)}</div></header><div class="grid">']
    for key in ('priorities', 'completed', 'progress', 'unfinished'):
        md += ['## ' + LABELS[key], '']
        html += [f'<section class="{"focus" if key == "priorities" else ""}"><h2>{LABELS[key]}</h2><ul>']
        if not result[key]:
            md.append('暂无足够依据。')
            html.append('<li class="muted">暂无足够依据。</li>')
        for index, item in enumerate(result[key]):
            task = tasks.get(item.get('task_id'), {})
            if 'projects' in task:
                projects = task['projects']
                prefix = ''
            else:
                # Old reports only know the source session's project, which may
                # differ from the project actually discussed in the message.
                projects = list(dict.fromkeys(evidence[ref]['project'] for ref in item['refs']
                                              if evidence[ref].get('project')))
                prefix = '来源项目：'
            labels = [prefix + project for project in projects] or ['未归属项目']
            badges = ''.join(f'<span class="project-tag">{escape(label)}</span>' for label in labels)
            refs = ' '.join(f'<a href="#{ref}">[{ref}]</a>' for ref in item['refs'])
            html.append(f'<li><div class="project-tags">{badges}</div><div class="markdown-body">{render_markdown(item["text"], f"{key}-{index}")}</div>'
                        f'<div class="references">{refs}</div></li>')
            lines = export_markdown(item['text'], f'{key}-{index}').split('\n')
            # Entities keep names literal, including Markdown and auto-link syntax.
            project_label = ' · '.join(labels)
            project_label = ''.join(f'&#{ord(c)};' if c in '\\`*_{}[]<>()#+!|~&:' else c
                                    for c in single_line(project_label))
            md.append('- **' + project_label + '**\n\n  ' + lines[0] + ''.join('\n  ' + line for line in lines[1:]) + '\n\n  '
                      + ' '.join(f'[{ref}](#{ref.lower()})' for ref in item['refs']))
        md.append('')
        html.append('</ul></section>')
    html.append('</div><details open><summary>查看来源摘录</summary>')
    md += ['## 来源摘录', '']
    for item in record['evidence']:
        timestamp = datetime.fromisoformat(item['time']).astimezone(config.timezone).strftime('%Y-%m-%d %H:%M')
        source = {'codex': 'Codex', 'claude_code': 'Claude Code', 'browser_history': '浏览历史', 'git': 'Git', 'capture': '收藏'}.get(item['source'], item['source'])
        label = ' · '.join(str(value) for value in (source, item.get('project'), timestamp) if value)
        title = unescape(item['title']).strip()
        text = item['text'].strip('\r\n')
        if item['source'] == 'browser_history':
            text = unescape(text)
        if ' '.join(title.split()) == ' '.join(text.split()):
            if item['source'] == 'browser_history':
                text = ''
            else:
                title = ''  # Keep Markdown semantics when a message repeats its title.
        html.append(f'<article class="evidence" id="{item["id"]}"><div class="evidence-heading"><strong>{item["id"]}</strong>'
                    f'<span class="muted">{escape(label)}</span></div>')
        md += ['### ' + item['id'], '', single_line(label), '']
        if title:
            html.append(f'<p class="evidence-title">{escape(title)}</p>')
            md += [single_line(title), '']
        if text:
            html.append(f'<div class="markdown-body">{render_markdown(text, item["id"])}</div>')
            md += [export_markdown(text, item['id']), '']
        if item.get('excerpt_truncated'):
            html.append('<p class="muted">此处为截断摘录。</p>')
            md += ['*此处为截断摘录。*', '']
        html.append('</article>')
    html += ['</details><footer class="muted">' + escape(caveat) + '</footer></main></html>']
    root = config.root / 'briefings' / day
    write_if_changed(root.with_suffix('.md'), '\n'.join(md))
    write_if_changed(root.with_suffix('.html'), '\n'.join(html))
