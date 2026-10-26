"""Regenerate capture Markdown from the current database under a per-file lock."""

from datetime import datetime
import json
from pathlib import Path

from .. import queries
from ..db import Database
from ..runtime import file_lock
from ..redact import redact


from ..files import atomic_write

def single_line(value):
    return str(value or '').replace('\r','').replace('\n',' ⏎ ').replace('```','ʼʼʼ')


def render_capture(config, identity):
    with file_lock(config.root/'run'/f'capture-{identity}.lock'):
        with Database(config.db_path) as db:
            event=queries.capture_by_id(db.connection,identity)
            if event is None:
                raise ValueError('收藏不存在。')
        meta=event.meta
        path=config.root/Path(meta['screenshot']).with_suffix('.md')
        lines=['---','type: capture','id: '+json.dumps(identity),'title: '+json.dumps(event.title,ensure_ascii=False),
               'time: '+json.dumps(event.ts),'---',f'# {single_line(event.title)}','',
               f"时间：{datetime.fromisoformat(event.ts).astimezone(config.timezone).isoformat()}",
               f"应用：{single_line(meta.get('app_name') or meta.get('app_bundle'))}",'']
        if event.url:
            lines.extend([f'网址：<{event.url}>',''])
        lines.extend(['## 备注','',meta.get('note','').replace('```','ʼʼʼ'),'','## 截图','',f"![[{meta['screenshot']}]]",''])
        for section in meta.get('text_sections',[]):
            lines.extend(['## '+section['name'],'',event.content[section['start']:section['end']].replace('```','ʼʼʼ'),''])
        lines.extend([f"OCR：{meta.get('ocr_status','pending')}",''])
        atomic_write(path,redact('\n'.join(lines)))
        return path
