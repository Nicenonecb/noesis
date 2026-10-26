"""Fast screenshot capture and asynchronous local enrichment."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from ..config import private_directory
from ..db import Database
from ..models import Event
from .. import queries
from ..redact import redact, clean_url
from . import browser_bridge
from .render import render_capture


def capture_id(value):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{4}',value):
        raise ValueError('无效的收藏 ID。')
    return value


def screenshot(path, *, window_id=None, region=False):
    args=['screencapture','-x']
    args+=['-i'] if region else (['-o','-l',str(window_id)] if window_id is not None else [])
    result=subprocess.run(args+[str(path)],capture_output=True)
    if result.returncode and window_id is not None and not region:
        result=subprocess.run(['screencapture','-x',str(path)],capture_output=True)
    if result.returncode or not path.exists() or path.stat().st_size==0:
        raise OSError('截图失败或已取消；请检查屏幕录制权限。')
    path.chmod(0o600)


def create_capture(config, *, window_id=None, app='', app_name='', window_title='', region=False, background=True):
    now=datetime.now(config.timezone)
    directory=config.root/'captures'/now.strftime('%Y-%m')
    private_directory(directory)
    while True:
        identity=now.strftime('%Y%m%d-%H%M%S-')+secrets.token_hex(2)
        image=directory/(identity+'.png')
        try:
            fd=os.open(image,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            break
        except FileExistsError:
            continue
    try:
        screenshot(image,window_id=window_id,region=region)
    except OSError:
        image.unlink(missing_ok=True)
        raise
    info=browser_bridge.metadata(app)
    app_name=app_name or (browser_bridge.APPS[app][0] if app in browser_bridge.APPS else app.rsplit('.',1)[-1])
    title=info.get('title') or ' · '.join(part for part in (app_name,window_title) if part) or '屏幕收藏'
    event=Event('capture',identity,'capture',datetime.now(timezone.utc),title=title,
                url=clean_url(info['url']) if info.get('url') else None,
                meta={'app_bundle':app,'app_name':app_name,'window_title':window_title,'screenshot':str(image.relative_to(config.root)),
                      'ocr_status':'pending','note':'','selection':'','page_text_len':0,'text_sections':[],
                      'page_text_error':info.get('page_text_error'),
                      'page_url_hash':hashlib.sha256(info['url'].encode()).hexdigest() if info.get('url') else None,
                      # Store only the redacted URL. The background bridge compares normalized forms.
                      'page_url':clean_url(info['url']) if info.get('url') else None})
    with Database(config.db_path) as db:
        db.insert_event(event)
    render_capture(config,identity)
    if background:
        subprocess.Popen([sys.executable,'-m','noesis','capture-ocr',identity,'--data-dir',str(config.root)],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         start_new_session=True,close_fds=True)
    return {'id':identity,'title':redact(title),'warning':info.get('page_text_error')}


def compose_text(selection,page,ocr,limit):
    text='';sections=[]
    omitted=0
    for name,value in (('选中文字',selection),('网页正文',page),('OCR 文本',ocr)):
        value=redact(value)
        if not value:
            continue
        if len(text)+(2 if text else 0)>=limit:
            omitted+=len(value)
            continue
        if text:
            text+='\n\n'
        start=len(text)
        text+=value[:max(0,limit-start)]
        omitted+=max(0,len(value)-max(0,limit-start))
        sections.append({'name':name,'start':start,'end':len(text)})
    if omitted:
        text+=f'…[truncated {omitted} chars]'
        if sections:
            sections[-1]['end']=len(text)
    return text,sections


def enrich_capture(config, identity):
    identity=capture_id(identity)
    with Database(config.db_path) as db:
        event=queries.capture_by_id(db.connection,identity)
    if event is None:
        raise ValueError('收藏不存在。')
    if event.meta.get('ocr_status')=='done':
        render_capture(config,identity)
        return {'id':identity,'status':'done'}
    image=config.root/event.meta['screenshot']
    maximum=config.values['browser']['max_page_chars']
    page=browser_bridge.page(event.meta['app_bundle'],maximum=maximum,expected_url=event.meta.get('page_url'),
                             expected_hash=event.meta.get('page_url_hash'))
    result={};status='done'
    try:
        process=subprocess.run([str(config.root/'bin/noesis-ocr'),str(image)],capture_output=True,text=True,timeout=60)
        if process.returncode:
            raise OSError('OCR failed')
        result=json.loads(process.stdout)
        if not isinstance(result,dict) or not isinstance(result.get('text'),str):
            raise ValueError('invalid OCR output')
    except (OSError,ValueError,subprocess.SubprocessError):
        status='failed'
        result={}
    text,sections=compose_text(page.get('selection',''),page.get('text',''),result.get('text',''),maximum)
    patch={'selection':page.get('selection','')[:maximum],'page_text_len':len(page.get('text','')),
           'text_root':page.get('text_root'),'text_sections':sections,'ocr_status':status,
           'ocr_ms':result.get('ms'),'page_text_error':page.get('page_text_error'),
           'screenshot_warning':'请检查屏幕录制权限，截图接近纯色' if result.get('uniform') else None,
           'truncated':len(text)>maximum}
    with Database(config.db_path) as db:
        with db.transaction():
            # Read after BEGIN IMMEDIATE so a concurrent annotation is preserved.
            current=queries.capture_by_id(db.connection,identity)
            db.replace_event(replace(current,content=text,title=page.get('title') or current.title))
            db.update_event_meta(current.id,patch)
    render_capture(config,identity)
    warning=patch.get('page_text_error') or patch.get('screenshot_warning')
    if status=='failed' or warning:
        message='截图已保留；OCR 失败，请检查 noesis doctor。' if status=='failed' else (
            '正文未获取，请检查浏览器的 Apple 事件 JavaScript 权限。' if warning=='js_disabled' else str(warning))
        try:
            subprocess.run(['osascript','-e','display notification '+json.dumps(message,ensure_ascii=False)+' with title "NOESIS · 求是"'],
                           capture_output=True,timeout=3)
        except (OSError,subprocess.SubprocessError):
            pass  # Notification availability does not determine capture success.
    from ..runtime import run_logger
    with run_logger(config) as logger:
        logger.info('capture=%s ocr=%s page=%s',identity,status,warning or 'ok')
    return {'id':identity,'status':status,'warning':patch.get('page_text_error') or patch.get('screenshot_warning')}


def annotate(config, identity, note):
    identity=capture_id(identity)
    with Database(config.db_path) as db:
        with db.transaction():
            event=queries.capture_by_id(db.connection,identity)
            if event is None:
                raise ValueError('收藏不存在。')
            db.update_event_meta(event.id,{'note':note})
    render_capture(config,identity)
    return {'id':identity,'annotated':True}
