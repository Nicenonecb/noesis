"""Local morning report, rendered from validated data without remote assets or scripts."""

from datetime import datetime
from html import escape, unescape
import json
import re

from ..files import write_if_changed
from ..focus import OUTCOMES, due_focuses, local_day
from ..runtime import file_lock
from ..capture.render import single_line
from ..render.markdown import export_markdown, render_markdown

LABELS = {'completed': '昨日成果', 'progress': '进行中的工作', 'unfinished': '未完成与待确认', 'priorities': '今日建议 · 待你确认'}
CSS = '''*{box-sizing:border-box}
body{margin:0;background:#fbfaf6;color:#26332c;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:920px;margin:0 auto;padding:44px 44px 64px}
a{color:#3f6a4e;text-decoration:none;border-bottom:1px solid #ccd9cc}a:hover{border-bottom-color:#3f6a4e}
.muted{color:#7c8a80;font-size:12.5px;line-height:1.9}
.masthead{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding-bottom:10px;border-bottom:1.5px solid #26332c}
.wordmark{font-family:"Songti SC",STSong,serif;font-size:13px;font-weight:700;letter-spacing:.22em;color:#26332c}
.kicker{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:10.5px;letter-spacing:.24em;color:#7c8a80}
.lead-block{margin-top:26px}
h1{display:flex;align-items:baseline;flex-wrap:wrap;margin:0;font-family:"Songti SC",STSong,serif;font-size:38px;line-height:1.25;font-weight:700;letter-spacing:0}
h1 time{font-variant-numeric:tabular-nums;letter-spacing:.01em}
.h1-tail{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;font-size:20px;font-weight:500;letter-spacing:.02em;color:#5b6d61}
.summary{margin-top:14px;max-width:40em;font-size:16.5px;line-height:1.9;color:#2b3a31}
.summary .markdown-body{font-size:inherit;line-height:inherit}
.summary p{margin:0 0 14px}.summary p:last-child{margin-bottom:0}
.meta{margin-top:18px;padding-top:12px;border-top:1px solid #e6e8df;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:11px;letter-spacing:.06em;color:#87948a}
.focus{margin-top:30px;padding:24px 28px 22px;background:#eef3e7;border-left:3px solid #5f8265;border-radius:0 3px 3px 0}
.focus h2{margin:0 0 10px;font-family:"Songti SC",STSong,serif;font-size:21px;font-weight:700;letter-spacing:.01em}
.focus h3{margin:18px 0 4px;font-size:16px;font-weight:650}
.focus p{margin:6px 0;font-size:15px;line-height:1.85}
.focus .muted{font-size:12.5px;line-height:1.85;color:#64766a}
.checkin article+article{margin-top:18px;padding-top:14px;border-top:1px solid #d3ddcd}
.checkin-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px}
.checkin-actions a{padding:3px 12px;border:1px solid #b3c7ae;border-radius:2px;background:#fbfaf6;font-size:12.5px;line-height:1.8}
.ledger{margin-top:36px;border-top:1.5px solid #26332c}
.chapter{display:grid;grid-template-columns:180px minmax(0,1fr);gap:0 32px;padding:30px 0 10px;border-bottom:1px solid #e6e8df}
.chapter:last-child{border-bottom:0;padding-bottom:0}
.chapter-head{align-self:start;position:sticky;top:20px}
.chapter-no{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:10.5px;letter-spacing:.22em;color:#9aa79d}
.chapter-head h2{margin:7px 0 3px;font-size:15.5px;line-height:1.5;font-weight:650;letter-spacing:.04em}
.chapter-priorities .chapter-head h2{color:#37553f}
.chapter-count{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:10px;letter-spacing:.1em;color:#9aa79d}
.entries{min-width:0}
.entries ul{list-style:none;margin:0;padding:0}
.entries li{padding:0 0 22px;margin:0 0 22px;border-bottom:1px solid #eceee7}
.entries li:last-child{padding-bottom:0;margin-bottom:0;border-bottom:0}
.entries .markdown-body{font-size:15.5px;line-height:1.85;color:#2b3a31}
.project-tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}
.project-tag{display:inline-block;max-width:100%;padding:2px 8px;background:#edf2e8;border-radius:2px;color:#44624f;font-size:12px;font-weight:600;letter-spacing:.02em;overflow-wrap:anywhere}
.references{margin-top:9px;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:10.5px;letter-spacing:.04em;color:#93a096}
.references a{color:#6c8574;border-bottom:0}
.markdown-body{min-width:0;overflow-wrap:anywhere}
.markdown-body>:first-child{margin-top:0}.markdown-body>:last-child{margin-bottom:0}
.markdown-body p{margin:10px 0}
.markdown-body h1,.markdown-body h2{font-size:20px;margin:22px 0 10px}
.markdown-body h3,.markdown-body h4,.markdown-body h5,.markdown-body h6{font-size:17px;margin:18px 0 8px}
.markdown-body ul,.markdown-body ol{padding-left:22px;margin:10px 0}.markdown-body li{margin:4px 0}
.markdown-body blockquote{margin:14px 0;padding:2px 16px;border-left:2px solid #b9cbb2;color:#516353}
.markdown-body code{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:.88em;background:#eef0e8;padding:1px 5px;border-radius:2px}
.markdown-body pre{margin:14px 0;padding:14px 16px;background:#f1f2ec;border:1px solid #e6e8df;border-radius:3px;overflow-x:auto;white-space:pre}
.markdown-body pre code{background:none;padding:0;font-size:12.5px;line-height:1.65}
.markdown-body table{display:block;overflow-x:auto;border-collapse:collapse;max-width:100%;font-size:13.5px;margin:14px 0}
.markdown-body th,.markdown-body td{border:1px solid #e0e4da;padding:7px 11px;text-align:left}
.markdown-body th{background:#f1f3ec}
.markdown-body hr{border:0;border-top:1px solid #e6e8df;margin:20px 0}
.markdown-body .task-list-item{list-style:none}
.markdown-body .task-list-item-checkbox{margin:0 7px 0 -18px;accent-color:#5f8265}
.sources{margin-top:44px;border-top:1.5px solid #26332c;padding-top:16px}
.sources summary{display:flex;align-items:baseline;gap:10px;cursor:pointer;list-style:none;font-size:12.5px;font-weight:600;letter-spacing:.12em;color:#3f5548}
.sources summary::-webkit-details-marker{display:none}
.sources summary::after{content:"＋";margin-left:auto;font-weight:400;color:#8b988e}
.sources[open] summary::after{content:"－"}
.sources .count{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:10.5px;letter-spacing:.08em;color:#9aa79d;font-weight:400}
.evidence{padding:22px 0;border-top:1px solid #eceee7;scroll-margin-top:24px}
.evidence:first-of-type{border-top:0}
.evidence-heading{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.evidence-heading strong{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:11px;font-weight:600;letter-spacing:.06em;color:#5f7c66}
.evidence-heading .muted{font-size:11px;letter-spacing:.02em;color:#93a096}
.evidence-title{margin:2px 0 6px;font-size:15px;font-weight:600;line-height:1.7}
.evidence .markdown-body{max-width:52em;font-size:14.5px;line-height:1.8;color:#3a4a40}
.image-reference{color:#7c8a80;font-size:14px}
footer{margin-top:40px;padding-top:14px;border-top:1px solid #e6e8df;font-size:11.5px;line-height:1.9;color:#8b988e}
@media(max-width:760px){main{padding:28px 20px 48px}h1{font-size:31px}.h1-tail{font-size:18px}.lead-block{margin-top:20px}.focus{padding:20px 20px 18px;margin-top:28px}.chapter{grid-template-columns:1fr;gap:12px;padding:26px 0 6px}.chapter-head{position:static;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.chapter-head h2{margin:0;font-size:15px}.chapter-count{margin-left:auto}.evidence .markdown-body{max-width:none}}'''


SENTENCE_END = re.compile(r'[^。！？!?]+[。！？!?]+[”’」』]?|[^。！？!?]+$')
MARKDOWN_SYNTAX = re.compile(r'[*_`\[\]|#]')


def literal_markdown(text):
    return ''.join(f'&#{ord(c)};' if c in '\\`*_{}[]<>()#+!|~&:' else c for c in single_line(text))


def summary_paragraphs(text, projects=()):
    """Explicit paragraph breaks win; otherwise keep one project per paragraph."""
    blocks = [line.strip() for line in text.splitlines() if line.strip()]
    if len(blocks) != 1 or MARKDOWN_SYNTAX.search(blocks[0]):
        return blocks
    sentences = [match.group(0).strip() for match in SENTENCE_END.finditer(blocks[0])]
    names = tuple(sorted({name.strip() for name in projects if name and name.strip()},
                         key=len, reverse=True))
    paragraphs, pending, grouped = [], [], False
    for sentence in sentences:
        if any(sentence.startswith(name) and sentence[len(name):len(name) + 1]
               in {'', ' ', '：', ':', '，', ',', '、'} for name in names):
            grouped = True
            if pending:
                paragraphs.append(''.join(pending))
                pending = []
            paragraphs.append(sentence)
        else:
            pending.append(sentence)
    if pending:
        paragraphs.append(''.join(pending))
    if not grouped:
        # Without a recognisable project lead, keep short trailing notes with
        # the sentence before them instead of starting a one-line paragraph.
        merged = []
        for sentence in sentences:
            if merged and len(sentence) <= 24 and len(merged[-1]) <= 90:
                merged[-1] += sentence
            else:
                merged.append(sentence)
        return merged or blocks
    return paragraphs or blocks


def render_focus(focuses, advice=(), *, delivery=None):
    interactive = delivery is not None
    html = ['<section class="focus checkin"><h2>今天，朝想成为的自己走一步</h2>']
    md = ['## 主动跟进 · 你的发展方向', '']
    by_id = {item['focus_id']: item for item in advice}
    if not focuses:
        text = '今天没有待反馈的方向。已反馈或延后的方向会在下次到期时跟进；新设置的方向从次日开始提醒。'
        html.append('<p>' + text + '</p>')
        md += [text, '']
    for item in focuses:
        identity = item['id']
        last = item['last_checkin']
        feedback = ('最近反馈（' + last['day'] + '）：' + OUTCOMES[last['outcome']] +
                    ('；' + last['note'] if last['note'] else '')) if last else '还没有你的反馈；记录不足不代表没有行动。'
        question = '上次约定的行动推进了吗？今天先留出一点时间，完成这一步；遇到阻碍也可以如实记录。'
        suggestion = by_id.get(identity)
        if suggestion and suggestion['revision'] != item['revision']:
            suggestion = None  # Editing or answering invalidates cached coaching.
        html += ['<article><h3>' + escape(item['title']) + '</h3>',
                 '<p>想发展的方向：' + escape(item['direction']) + '</p>',
                 '<p><strong>你的具体行动：</strong>' + escape(item['step']) + '</p>',
                 '<p class="muted">' + escape(feedback) + '</p>', '<p>' + question + '</p>']
        md += ['### ' + literal_markdown(item['title']), '',
               '想发展的方向：' + literal_markdown(item['direction']), '',
               '你的具体行动：' + literal_markdown(item['step']), '', literal_markdown(feedback), '', question, '']
        if suggestion:
            html.append('<div class="markdown-body">' + render_markdown(suggestion['text'], 'focus-' + identity) + '</div>')
            html.append('<div class="references">' + ' '.join(f'<a href="#{ref}">[{ref}]</a>' for ref in suggestion['refs']) + '</div>')
            md += [export_markdown(suggestion['text'], 'focus-' + identity), '',
                   ' '.join(f'[{ref}](#{ref.lower()})' for ref in suggestion['refs']), '']
        if interactive:
            html.append('<div class="checkin-actions">' + ''.join(
                f'<a href="noesis-focus://{action}/{identity}?day={delivery}">{label}</a>'
                for action, label in [('done', '完成了'), ('missed', '还没完成'),
                                      ('snoozed', '明天再提醒'), ('pause', '暂停此方向')]) + '</div>')
            md += [f'反馈：`noesis focus checkin {identity} --outcome done`（也可用 missed / snoozed）。', '']
        html.append('</article>')
    if interactive:
        html.append(f'<p><a href="noesis-focus://add?day={delivery}">＋ 设置关注方向</a></p>'
                    '<p class="muted">按钮在 NOESIS 晨报窗口内使用。每次反馈只记录当天行动；长期方向会持续跟进，可随时暂停。最多启用 3 个方向。</p>')
    html.append('</section>')
    return '\n'.join(html), md


def write_failure(config, delivery, error):
    focus_html, _ = render_focus(due_focuses(config, local_day(config)), delivery=delivery)
    path = config.root / 'briefings' / (delivery + '-error.html')
    write_if_changed(path, '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        '<title>NOESIS 晨报</title><style>' + CSS + '</style><main>'
        '<div class="masthead"><span class="wordmark">NOESIS · 求是</span>'
        '<span class="kicker">MORNING BRIEF</span></div>'
        '<header class="lead-block"><h1>晨报暂未生成</h1>'
        '<p>请检查网络、API 余额或数据目录 .env 配置。</p>'
        '<p>状态：' + escape(error) + '</p><p>稍后会按重试规则补生成。你的关注方向仍可在本机反馈。</p></header>'
        + focus_html + '</main></html>')
    return str(path)


def refresh_focus(config):
    """Refresh local views after a user action, without resetting delivery acknowledgement."""
    day = local_day(config).isoformat()
    target = config.root / 'briefings' / (day + '.json')
    with file_lock(config.root / 'run/digest.lock'):
        if target.exists():
            write_briefing(config, json.loads(target.read_text()))
            return str(target.with_suffix('.html'))
        # Also gives settings/check-ins a usable view when the model is unavailable.
        return write_failure(config, day, 'briefing_pending')


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
    projects = {project for task in tasks.values() for project in task.get('projects', [])}
    projects.update(item.get('project') for item in record['evidence'] if item.get('project'))
    summary = '\n\n'.join(summary_paragraphs(result['summary'], projects))
    md = ['---', 'type: morning-briefing', 'date: ' + day,
          'source_date: ' + record['source_day'], 'model: ' + json.dumps(record['model']), '---',
          f'# {day} 晨报', '', export_markdown(summary, 'summary'), '', metadata, '', caveat, '']
    interactive = day == local_day(config).isoformat()
    focuses = due_focuses(config, local_day(config)) if interactive else record.get('focuses', [])
    focus_html, focus_md = render_focus(focuses, result.get('focus_advice', []), delivery=day if interactive else None)
    md += focus_md
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
            f'<title>NOESIS 晨报 · {day}</title><style>{CSS}</style><main>',
            '<div class="masthead"><span class="wordmark">NOESIS · 求是</span>'
            '<span class="kicker">MORNING BRIEF</span></div>',
            f'<header class="lead-block"><h1><time datetime="{day}">{day}</time>'
            '<span class="h1-tail">，从昨天继续。</span></h1>',
            f'<div class="summary markdown-body">{render_markdown(summary, "summary")}</div>'
            f'<div class="meta">{escape(metadata)}</div></header>', focus_html, '<div class="ledger">']
    for number, key in enumerate(('priorities', 'completed', 'progress', 'unfinished'), start=1):
        items = result[key]
        md += ['## ' + LABELS[key], '']
        html += [f'<section class="chapter chapter-{key}"><header class="chapter-head">'
                 f'<div class="chapter-no">{number:02d}</div><h2>{LABELS[key]}</h2>'
                 + (f'<div class="chapter-count">{len(items)} 项</div>' if items else '')
                 + '</header><div class="entries"><ul>']
        if not items:
            md.append('暂无足够依据。')
            html.append('<li class="muted">暂无足够依据。</li>')
        for index, item in enumerate(items):
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
            project_label = literal_markdown(project_label)
            md.append('- **' + project_label + '**\n\n  ' + lines[0] + ''.join('\n  ' + line for line in lines[1:]) + '\n\n  '
                      + ' '.join(f'[{ref}](#{ref.lower()})' for ref in item['refs']))
        md.append('')
        html.append('</ul></div></section>')
    html.append('</div><details class="sources" open><summary>来源摘录'
                f'<span class="count">{len(record["evidence"])} 条</span></summary>')
    md += ['## 来源摘录', '']
    for item in record['evidence']:
        timestamp = datetime.fromisoformat(item['time']).astimezone(config.timezone).strftime('%Y-%m-%d %H:%M')
        source = {'codex': 'Codex', 'claude_code': 'Claude Code', 'dsh': 'DSH', 'browser_history': '浏览历史', 'git': 'Git', 'capture': '收藏'}.get(item['source'], item['source'])
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
    html += ['</details><footer>' + escape(caveat) + '</footer></main></html>']
    root = config.root / 'briefings' / day
    write_if_changed(root.with_suffix('.md'), '\n'.join(md))
    write_if_changed(root.with_suffix('.html'), '\n'.join(html))
