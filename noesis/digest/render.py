"""Local morning report, rendered from validated data without remote assets or scripts."""

from html import escape
import json

from ..files import atomic_write
from ..capture.render import single_line

LABELS = {'completed': '昨日成果', 'progress': '进行中的工作', 'unfinished': '未完成与待确认', 'priorities': '今日建议 · 待你确认'}
CSS = '''body{margin:0;background:#f4f3ed;color:#20342c;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
main{max-width:960px;margin:auto;padding:40px 24px}header{border-bottom:1px solid #ccd4c9;padding-bottom:26px;margin-bottom:26px}
.brand{letter-spacing:.16em;color:#577564;font-size:13px}h1{font-size:34px;line-height:1.3;margin:12px 0}h2{font-size:20px;margin-top:0}
.muted{color:#65766b;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
section{padding:24px;background:white;border:1px solid #dce2d8;border-radius:14px}.focus{background:#e6efdf;border-color:#aec5a0}
ul{padding-left:22px;margin-bottom:0}li{margin:12px 0}a{color:#39724d}summary{cursor:pointer;font-weight:600}
details{margin-top:24px;padding:20px;background:#fff;border-radius:12px}.evidence{padding:14px 0;border-top:1px solid #e1e5de}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:13px;line-height:1.65;color:#47584d}footer{margin-top:22px}
@media(max-width:700px){.grid{grid-template-columns:1fr}h1{font-size:28px}main{padding:24px 16px}}'''


def write_briefing(config, record):
    day = record['delivery_day']
    result = record['result']
    metadata = f"总结日期 {record['source_day']} · 来源 {sum(record['source_counts'].values())} 条 · 引用摘录 {len(record['evidence'])} 条"
    caveat = 'AI 根据活动记录归纳，完成状态仍需核实；今日重点是建议。'
    if record['omitted_events']:
        caveat += f" 本次输入未包含 {record['omitted_events']} 条事件。"
    unhealthy = [name for name, status in record['source_health'].items() if status != 'ok']
    if unhealthy:
        caveat += ' 来源采集未全部成功：' + '、'.join(unhealthy) + '。'
    md = ['---', 'type: morning-briefing', 'date: ' + day,
          'source_date: ' + record['source_day'], 'model: ' + json.dumps(record['model']), '---',
          f'# {day} 晨报', '', result['summary'], '', metadata, '', caveat, '']
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
            f'<title>NOESIS 晨报 · {day}</title><style>{CSS}</style><main>',
            f'<header><div class="brand">NOESIS · 求是 / MORNING BRIEF</div><h1>{day}，从昨天继续。</h1>',
            f'<p>{escape(result["summary"])}</p><div class="muted">{escape(metadata)}</div></header><div class="grid">']
    for key in ('priorities', 'completed', 'progress', 'unfinished'):
        md += ['## ' + LABELS[key], '']
        html += [f'<section class="{"focus" if key == "priorities" else ""}"><h2>{LABELS[key]}</h2><ul>']
        if not result[key]:
            md.append('暂无足够依据。')
            html.append('<li class="muted">暂无足够依据。</li>')
        for item in result[key]:
            refs = ' '.join(f'<a href="#{ref}">[{ref}]</a>' for ref in item['refs'])
            html.append(f'<li>{escape(item["text"])} <small>{refs}</small></li>')
            md.append('- ' + single_line(item['text']) + ' ' + ' '.join(f'[{ref}](#{ref.lower()})' for ref in item['refs']))
        md.append('')
        html.append('</ul></section>')
    html.append('</div><details open><summary>查看来源摘录</summary>')
    md += ['## 来源摘录', '']
    for item in record['evidence']:
        label = ' · '.join(str(item.get(key) or '') for key in ('source', 'project', 'time'))
        html.append(f'<div class="evidence" id="{item["id"]}"><strong>{item["id"]}</strong> '
                    f'<span class="muted">{escape(label)}</span><p>{escape(item["title"])}</p>'
                    f'<pre>{escape(item["text"])}</pre></div>')
        md += ['### ' + item['id'], '', single_line(label), '', single_line(item['title']), '',
               item['text'].replace('```', 'ʼʼʼ'), '']
    html += ['</details><footer class="muted">' + escape(caveat) + '</footer></main></html>']
    root = config.root / 'briefings' / day
    atomic_write(root.with_suffix('.md'), '\n'.join(md))
    atomic_write(root.with_suffix('.html'), '\n'.join(html))
